"""Dataset-level schema validation, executed before clinical rules run.

This module answers a narrower question than the clinical rules or FHIR
validators: "is this dataset shaped the way the pipeline expects?" It checks
column presence, declared dtypes, and controlled-vocabulary membership, and
reports counts rather than the rejected values themselves so that logs and
reports stay audit-safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml

SUPPORTED_DTYPES = {"string", "integer", "float", "boolean"}


class SchemaConfigError(ValueError):
    """Raised when a schema definition file is malformed."""


@dataclass(frozen=True)
class ColumnSpec:
    """Expected shape of a single column."""

    name: str
    required: bool
    dtype: str
    vocabulary: Optional[List[str]] = None


@dataclass(frozen=True)
class DatasetSchema:
    """A versioned collection of column contracts."""

    version: str
    columns: List[ColumnSpec]

    def column_names(self) -> List[str]:
        return [c.name for c in self.columns]


@dataclass(frozen=True)
class FieldErrorCount:
    """Aggregated error count for one column, keyed by error kind.

    Deliberately holds counts only. Rejected values are never retained here
    so this object is safe to log or serialize directly.
    """

    column: str
    error_type: str
    row_count: int


@dataclass(frozen=True)
class SchemaValidationResult:
    """Structured outcome of validating a dataset against a `DatasetSchema`."""

    schema_version: str
    is_valid: bool
    total_rows: int
    missing_columns: List[str] = field(default_factory=list)
    field_errors: List[FieldErrorCount] = field(default_factory=list)

    @property
    def total_field_errors(self) -> int:
        return sum(e.row_count for e in self.field_errors)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "is_valid": self.is_valid,
            "total_rows": self.total_rows,
            "missing_columns": list(self.missing_columns),
            "field_errors": [
                {"column": e.column, "error_type": e.error_type, "row_count": e.row_count}
                for e in self.field_errors
            ],
            "total_field_errors": self.total_field_errors,
        }


def load_schema(schema_path: str) -> DatasetSchema:
    """Load and validate a dataset schema definition from YAML."""
    path = Path(schema_path)
    if not path.exists():
        raise FileNotFoundError(f"Schema file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    version = raw.get("schema_version")
    if not version or not isinstance(version, str):
        raise SchemaConfigError("schema_version must be a non-empty string")

    raw_columns = raw.get("columns")
    if not isinstance(raw_columns, dict) or not raw_columns:
        raise SchemaConfigError("schema must define at least one column under 'columns'")

    columns: List[ColumnSpec] = []
    for name, spec in raw_columns.items():
        spec = spec or {}
        dtype = spec.get("dtype", "string")
        if dtype not in SUPPORTED_DTYPES:
            raise SchemaConfigError(
                f"column '{name}': unsupported dtype '{dtype}' (expected one of {sorted(SUPPORTED_DTYPES)})"
            )
        vocabulary = spec.get("vocabulary")
        if vocabulary is not None and not isinstance(vocabulary, list):
            raise SchemaConfigError(f"column '{name}': vocabulary must be a list")
        columns.append(
            ColumnSpec(
                name=name,
                required=bool(spec.get("required", False)),
                dtype=dtype,
                vocabulary=[str(v) for v in vocabulary] if vocabulary else None,
            )
        )

    return DatasetSchema(version=version, columns=columns)


def _dtype_matches(series: pd.Series, dtype: str) -> pd.Series:
    """Return a boolean mask of values that violate the declared dtype.

    Missing values (NaN/None) are not flagged here; column presence and
    "required" are handled separately so that an optional-but-present column
    with some missing values is not treated as a type error.
    """
    non_null = series.notna()

    if dtype == "string":
        return pd.Series(False, index=series.index)

    if dtype == "integer":
        coerced = pd.to_numeric(series, errors="coerce")
        failed_coercion = coerced.isna() & non_null
        present = coerced.notna()
        non_whole = present & (coerced % 1 != 0)
        return failed_coercion | non_whole

    if dtype == "float":
        coerced = pd.to_numeric(series, errors="coerce")
        return coerced.isna() & non_null

    if dtype == "boolean":
        valid_tokens = {"true", "false", "0", "1", "yes", "no"}
        normalized = series.astype("string").str.strip().str.lower()
        return non_null & ~normalized.isin(valid_tokens)

    return pd.Series(False, index=series.index)


def validate_schema(df: pd.DataFrame, schema: DatasetSchema) -> SchemaValidationResult:
    """Validate a DataFrame against a `DatasetSchema`.

    Returns structured, count-only errors. No rejected cell value is ever
    included in the result, so it is safe to log or persist directly.
    """
    total_rows = len(df)
    missing_columns = [c.name for c in schema.columns if c.required and c.name not in df.columns]

    field_errors: List[FieldErrorCount] = []
    for col in schema.columns:
        if col.name not in df.columns:
            continue

        series = df[col.name]

        type_violations = _dtype_matches(series, col.dtype)
        type_error_count = int(type_violations.sum())
        if type_error_count:
            field_errors.append(
                FieldErrorCount(column=col.name, error_type=f"invalid_{col.dtype}", row_count=type_error_count)
            )

        if col.vocabulary:
            normalized_vocab = {str(v).strip().lower() for v in col.vocabulary}
            present = series.notna()
            normalized_values = series.astype("string").str.strip().str.lower()
            out_of_vocab = present & ~normalized_values.isin(normalized_vocab)
            out_of_vocab_count = int(out_of_vocab.sum())
            if out_of_vocab_count:
                field_errors.append(
                    FieldErrorCount(column=col.name, error_type="out_of_vocabulary", row_count=out_of_vocab_count)
                )

    is_valid = not missing_columns and not field_errors
    return SchemaValidationResult(
        schema_version=schema.version,
        is_valid=is_valid,
        total_rows=total_rows,
        missing_columns=missing_columns,
        field_errors=field_errors,
    )


@dataclass(frozen=True)
class RowRejection:
    """One row's validation failure, keyed by position -- never by field value."""

    row_index: int
    column: str
    error_type: str


def validate_schema_per_row(df: pd.DataFrame, schema: DatasetSchema) -> List[RowRejection]:
    """Validate a DataFrame and return per-row rejections instead of aggregate counts.

    Used by the worker-facing contract (`contracts.process_request`), where a
    caller needs to know which specific records to quarantine. Missing
    required columns still fail the whole batch (returned as rejections for
    every row against that column) since no per-row remediation is possible
    when a column is absent entirely.
    """
    rejections: List[RowRejection] = []

    for col in schema.columns:
        if col.name not in df.columns:
            if col.required:
                rejections.extend(
                    RowRejection(row_index=int(idx), column=col.name, error_type="missing_column")
                    for idx in df.index
                )
            continue

        series = df[col.name]

        type_violations = _dtype_matches(series, col.dtype)
        for idx in df.index[type_violations]:
            rejections.append(RowRejection(row_index=int(idx), column=col.name, error_type=f"invalid_{col.dtype}"))

        if col.vocabulary:
            normalized_vocab = {str(v).strip().lower() for v in col.vocabulary}
            present = series.notna()
            normalized_values = series.astype("string").str.strip().str.lower()
            out_of_vocab = present & ~normalized_values.isin(normalized_vocab)
            for idx in df.index[out_of_vocab]:
                rejections.append(RowRejection(row_index=int(idx), column=col.name, error_type="out_of_vocabulary"))

    return rejections
