"""Deterministic idempotency for batch pipeline re-runs.

Re-running the same dataset through the pipeline should not re-emit
already-validated output. This module defines:

- A whole-file content hash (`dataset_hash`), combined with the schema
  version and a pipeline version string, so that a config/logic change is
  visible as a different processing identity even for byte-identical input.
- A canonical per-row hash, used as the manifest's duplicate-detection key.
  Row hashes are derived from field values via SHA-256 and are never
  reversible back to the original values, and no raw identifier (e.g.
  `patient_nbr`) is ever used as a manifest or log key on its own.
- A JSON-backed processing manifest recording which row hashes have already
  been processed under which run identity, so re-running an unchanged
  dataset reports rows as already-processed rather than duplicating them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Set, cast

import pandas as pd

PIPELINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class RunIdentity:
    """Identifies one (dataset, schema, pipeline-version) processing run."""

    dataset_hash: str
    schema_version: str
    pipeline_version: str

    @property
    def run_id(self) -> str:
        digest = hashlib.sha256(
            f"{self.dataset_hash}:{self.schema_version}:{self.pipeline_version}".encode("utf-8")
        ).hexdigest()
        return digest[:16]


@dataclass
class IdempotencyMetrics:
    """Outcome of checking a batch of rows against the processing manifest."""

    total_rows: int = 0
    new_rows: int = 0
    duplicate_rows: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {"total_rows": self.total_rows, "new_rows": self.new_rows, "duplicate_rows": self.duplicate_rows}


def compute_dataset_hash(data_path: str, chunk_bytes: int = 1024 * 1024) -> str:
    """Hash a file's full byte content without loading it into memory at once."""
    hasher = hashlib.sha256()
    with open(data_path, "rb") as handle:
        while True:
            block = handle.read(chunk_bytes)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


def compute_row_hash(row: pd.Series, columns: Iterable[str]) -> str:
    """Compute a deterministic, order-independent hash of selected row fields.

    Values are canonicalized (stripped, lower-cased for strings, stable
    float formatting) so that whitespace or type-representation differences
    do not change the row's identity for duplicate-detection purposes. The
    hash is one-way: it cannot be used to recover the original field values,
    so it is safe to persist and log directly.

    Kept for callers that need a single row's hash; `compute_row_hashes`
    below is the vectorized equivalent used for whole-chunk hashing.
    """
    parts: List[str] = []
    for column in sorted(columns):
        value = row.get(column)
        if pd.isna(value):
            parts.append(f"{column}=<null>")
        elif isinstance(value, float):
            parts.append(f"{column}={value:.10g}")
        else:
            parts.append(f"{column}={str(value).strip().lower()}")
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonicalize_column(series: pd.Series, column: str) -> pd.Series:
    """Vectorized per-column canonicalization matching `compute_row_hash`'s formatting.

    Column dtype alone cannot decide the formatting rule: an `object`-dtype
    column loaded from mixed sources may hold real Python floats alongside
    strings, and `compute_row_hash` formats each *value* by its own type
    (`.10g` for floats, stripped/lower-cased text otherwise). A plain
    `is_float_dtype` check on the column would miss floats hiding in an
    object column, so floats are masked out and formatted separately
    regardless of the column's overall dtype.
    """
    # Categorical columns must be decategorized before per-value masking: a
    # categorical `.map()` operates on the category labels, not the actual
    # per-row values, so `.where(mask).map(...)` on one would run the
    # formatter over every category label rather than the masked rows.
    if isinstance(series.dtype, pd.CategoricalDtype):
        series = series.astype("object")

    is_null = series.isna()
    is_float = series.map(lambda v: isinstance(v, float), na_action="ignore").astype("boolean").fillna(False)

    text_formatted = series.astype("string").str.strip().str.lower()
    float_formatted = series.where(is_float).map(lambda v: f"{v:.10g}", na_action="ignore")

    formatted = text_formatted.where(~is_float, float_formatted)
    return cast(pd.Series, f"{column}=" + formatted.where(~is_null, "<null>"))


def compute_row_hashes(df: pd.DataFrame, columns: Iterable[str]) -> pd.Series:
    """Vectorized form of `compute_row_hash` applied to every row of `df`.

    Builds the same "|"-joined canonical string per row via column-wise
    (not row-wise) pandas operations, then hashes each resulting string.
    Hashing itself is inherently per-value (SHA-256 has no vectorized
    form), but the expensive canonicalization work runs once per column
    instead of once per row.
    """
    sorted_columns = sorted(columns)
    canonical_parts = [_canonicalize_column(df[column], column) for column in sorted_columns]

    if not canonical_parts:
        return pd.Series("", index=df.index)

    canonical = canonical_parts[0]
    for part in canonical_parts[1:]:
        canonical = canonical + "|" + part

    return canonical.map(lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest())


class ProcessingManifest:
    """A JSON-persisted record of which row hashes have been processed, per run identity.

    The manifest is keyed by `RunIdentity.run_id` so that a pipeline-version
    or schema-version bump is explicit and auditable: rows processed under
    an old identity are not silently treated as duplicates of a new one.
    """

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._data: Dict[str, List[str]] = {}
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as handle:
                self._data = json.load(handle)

    def processed_hashes(self, run_id: str) -> Set[str]:
        return set(self._data.get(run_id, []))

    def record(self, run_id: str, row_hashes: Iterable[str]) -> None:
        existing = set(self._data.get(run_id, []))
        existing.update(row_hashes)
        self._data[run_id] = sorted(existing)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2, sort_keys=True)


class IdempotencyChecker:
    """Tracks row identity within one run and reports duplicate/new counts."""

    def __init__(self, manifest: ProcessingManifest, run_identity: RunIdentity, hash_columns: Iterable[str]) -> None:
        self.manifest = manifest
        self.run_identity = run_identity
        self.hash_columns = list(hash_columns)
        self._seen_this_run: Set[str] = set(manifest.processed_hashes(run_identity.run_id))
        self._new_this_run: List[str] = []
        self.metrics = IdempotencyMetrics()

    def process_chunk(self, chunk: pd.DataFrame) -> pd.DataFrame:
        """Return the subset of `chunk` not already recorded as processed."""
        columns = [c for c in self.hash_columns if c in chunk.columns]
        if not columns:
            self.metrics.total_rows += len(chunk)
            self.metrics.new_rows += len(chunk)
            return chunk

        row_hashes = compute_row_hashes(chunk, columns)
        is_duplicate = row_hashes.isin(self._seen_this_run)

        self.metrics.total_rows += len(chunk)
        self.metrics.duplicate_rows += int(is_duplicate.sum())
        self.metrics.new_rows += int((~is_duplicate).sum())

        keep_mask = ~is_duplicate
        new_hashes = row_hashes[keep_mask]
        self._seen_this_run.update(new_hashes)
        self._new_this_run.extend(new_hashes)

        return cast(pd.DataFrame, chunk.loc[keep_mask])

    def commit(self) -> None:
        """Persist newly processed row hashes to the manifest."""
        self.manifest.record(self.run_identity.run_id, self._new_this_run)
        self.manifest.save()
        self._new_this_run = []
