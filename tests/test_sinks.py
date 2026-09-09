import json

import pandas as pd
import pytest

from healthcli.sinks import DataFrameSink, ParquetSink, RejectedRecordSink


def test_dataframe_sink_concatenates_chunks():
    sink = DataFrameSink()
    sink.write(pd.DataFrame({"a": [1, 2]}))
    sink.write(pd.DataFrame({"a": [3, 4]}))
    sink.finalize()
    assert list(sink.result["a"]) == [1, 2, 3, 4]


def test_dataframe_sink_result_before_finalize_raises():
    sink = DataFrameSink()
    with pytest.raises(RuntimeError):
        _ = sink.result


def test_dataframe_sink_handles_no_chunks():
    sink = DataFrameSink()
    sink.finalize()
    assert sink.result.empty


def test_parquet_sink_writes_all_rows_across_chunks(tmp_path):
    output_path = tmp_path / "out.parquet"
    sink = ParquetSink(str(output_path))
    sink.write(pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}))
    sink.write(pd.DataFrame({"a": [3, 4], "b": ["z", "w"]}))
    sink.finalize()

    result = pd.read_parquet(output_path)
    assert len(result) == 4
    assert sink.rows_written == 4


def test_parquet_sink_tolerates_differing_categorical_encoding_per_chunk(tmp_path):
    output_path = tmp_path / "out.parquet"
    sink = ParquetSink(str(output_path))
    # Simulate per-chunk memory optimization producing a categorical dtype
    # in one chunk but not another for the same logical column.
    chunk1 = pd.DataFrame({"code": pd.Series(["A", "B"], dtype="category")})
    chunk2 = pd.DataFrame({"code": pd.Series(["C", "D"], dtype="object")})
    sink.write(chunk1)
    sink.write(chunk2)
    sink.finalize()

    result = pd.read_parquet(output_path)
    assert len(result) == 4
    assert set(result["code"]) == {"A", "B", "C", "D"}


def test_parquet_sink_tolerates_widening_integer_range_across_chunks(tmp_path):
    output_path = tmp_path / "out.parquet"
    sink = ParquetSink(str(output_path))
    # Simulate per-chunk memory optimization downcasting to different
    # integer widths because each chunk's own value range differs.
    chunk1 = pd.DataFrame({"n": pd.array([1, 2, 100], dtype="int8")})
    chunk2 = pd.DataFrame({"n": pd.array([129, 200], dtype="int16")})
    sink.write(chunk1)
    sink.write(chunk2)
    sink.finalize()

    result = pd.read_parquet(output_path)
    assert len(result) == 5
    assert sorted(result["n"]) == [1, 2, 100, 129, 200]


def test_parquet_sink_skips_empty_chunks(tmp_path):
    output_path = tmp_path / "out.parquet"
    sink = ParquetSink(str(output_path))
    sink.write(pd.DataFrame({"a": [1]}))
    sink.write(pd.DataFrame({"a": []}))
    sink.finalize()
    assert sink.rows_written == 1


def test_rejected_record_sink_writes_metadata_only(tmp_path):
    output_path = tmp_path / "rejected.jsonl"
    sink = RejectedRecordSink(str(output_path))
    sink.write_rejection(chunk_number=1, row_index=5, reason="invalid_integer")
    sink.write_rejection(chunk_number=1, row_index=9, reason="out_of_vocabulary")
    sink.finalize()

    lines = output_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert record == {"chunk_number": 1, "row_index": 5, "reason": "invalid_integer"}
    assert sink.rejected_count == 2
