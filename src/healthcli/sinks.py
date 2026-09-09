"""Pluggable output sinks for streamed, chunked pipeline processing.

A `RecordSink` receives one optimized chunk at a time and is responsible for
persisting or accumulating it. This decouples `pipeline.process_chunks` from
any single output strategy: a full in-memory DataFrame (`DataFrameSink`,
today's behaviour, kept for the HTML/PDF report path) or an incremental
Parquet file (`ParquetSink`) that never holds more than one chunk in memory.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Protocol, runtime_checkable

import pandas as pd

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - exercised only when pyarrow is absent
    pa = None
    pq = None


@runtime_checkable
class RecordSink(Protocol):
    """Receives validated record chunks during streaming pipeline processing."""

    def write(self, chunk: pd.DataFrame) -> None:
        """Persist or accumulate one chunk. Called once per processed chunk."""
        ...

    def finalize(self) -> None:
        """Flush and release any resources. Called once after the last chunk."""
        ...


class DataFrameSink:
    """Accumulates chunks into a single in-memory DataFrame.

    This is the materialized/backward-compatible sink: it reproduces the
    pre-streaming behaviour (`pd.concat` of every optimized chunk) for
    callers such as the HTML report generator that need row-level access to
    the full dataset. It does not scale to multi-GB inputs by design.
    """

    def __init__(self) -> None:
        self._chunks: List[pd.DataFrame] = []
        self._result: Optional[pd.DataFrame] = None

    def write(self, chunk: pd.DataFrame) -> None:
        self._chunks.append(chunk)

    def finalize(self) -> None:
        self._result = pd.concat(self._chunks, ignore_index=True) if self._chunks else pd.DataFrame()
        self._chunks = []

    @property
    def result(self) -> pd.DataFrame:
        if self._result is None:
            raise RuntimeError("finalize() must be called before reading result")
        return self._result


class ParquetSink:
    """Streams chunks directly to a Parquet file without materializing the dataset.

    Each chunk is written as its own row group via a single open
    `ParquetWriter`, so peak memory is bounded by one chunk rather than the
    whole dataset.
    """

    def __init__(self, output_path: str) -> None:
        if pa is None or pq is None:
            raise RuntimeError("pyarrow is required for ParquetSink but is not installed")
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._writer: Optional["pq.ParquetWriter"] = None
        self.rows_written = 0

    def write(self, chunk: pd.DataFrame) -> None:
        if chunk.empty:
            return
        # Per-chunk memory optimization picks numeric width and categorical
        # encoding independently for each chunk based on that chunk's own
        # value range/cardinality (e.g. chunk 1 downcasts to int8 because
        # its max value is 100, chunk 5 needs int16 because it sees 129).
        # A single open ParquetWriter needs one fixed schema, so every
        # chunk is normalized back to stable, sufficiently wide types
        # before being written -- the optimizer's savings only ever
        # mattered for in-process pandas memory, not for the sink's schema.
        normalized = chunk.copy()
        for column in normalized.columns:
            dtype = normalized[column].dtype
            if isinstance(dtype, pd.CategoricalDtype):
                normalized[column] = normalized[column].astype(dtype.categories.dtype)
            elif pd.api.types.is_integer_dtype(dtype):
                normalized[column] = normalized[column].astype("int64")
            elif pd.api.types.is_float_dtype(dtype):
                normalized[column] = normalized[column].astype("float64")

        table = pa.Table.from_pandas(normalized, preserve_index=False)
        if self._writer is None:
            self._writer = pq.ParquetWriter(str(self.output_path), table.schema)
        elif not table.schema.equals(self._writer.schema):
            table = table.cast(self._writer.schema)
        self._writer.write_table(table)
        self.rows_written += len(chunk)

    def finalize(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None


class RejectedRecordSink:
    """Persists rejected-record metadata (counts and reasons, never raw payloads).

    Writes one JSON-lines record per rejected row containing only the row's
    positional index, the originating chunk number, and the rejection
    reason/category -- never the row's field values, so it is safe to keep
    alongside operational logs.
    """

    def __init__(self, output_path: str) -> None:
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.output_path.open("w", encoding="utf-8")
        self.rejected_count = 0

    def write_rejection(self, chunk_number: int, row_index: int, reason: str) -> None:
        import json

        record = {"chunk_number": chunk_number, "row_index": row_index, "reason": reason}
        self._handle.write(json.dumps(record) + "\n")
        self.rejected_count += 1

    def finalize(self) -> None:
        self._handle.close()
