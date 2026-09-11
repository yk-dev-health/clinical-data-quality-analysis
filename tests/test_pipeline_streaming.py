import logging
from pathlib import Path

import pandas as pd
import pytest
import yaml

from healthcli.pipeline import process_chunks, process_chunks_streaming, run_pipeline_streaming
from healthcli.sinks import ParquetSink

REQUIRED_COLUMNS = ["patient_nbr", "gender", "age"]


def _write_sample_csv(path: Path, rows: int = 30) -> None:
    lines = ["patient_nbr,gender,age"]
    for i in range(rows):
        gender = "Male" if i % 2 == 0 else "Female"
        lines.append(f"{1000 + i},{gender},{20 + (i % 50)}")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_schema(path: Path) -> None:
    path.write_text(
        """
schema_version: "1.0"
columns:
  patient_nbr:
    required: true
    dtype: string
  gender:
    required: true
    dtype: string
    vocabulary: [Male, Female]
  age:
    required: true
    dtype: integer
"""
    )


def test_streaming_and_materialized_paths_produce_same_row_count(tmp_path):
    csv_path = tmp_path / "data.csv"
    _write_sample_csv(csv_path, rows=25)
    logger = logging.getLogger("test.streaming")

    materialized_df, _metrics, _fhir = process_chunks(str(csv_path), chunk_size=10, logger=logger)

    parquet_path = tmp_path / "out.parquet"
    sink = ParquetSink(str(parquet_path))
    _metrics2, _fhir2, aggregator, total_rows = process_chunks_streaming(
        str(csv_path), chunk_size=10, logger=logger, sink=sink
    )

    assert len(materialized_df) == total_rows == 25
    streamed_df = pd.read_parquet(parquet_path)
    assert len(streamed_df) == 25


def test_run_pipeline_streaming_end_to_end(tmp_path):
    csv_path = tmp_path / "data.csv"
    _write_sample_csv(csv_path, rows=40)

    schema_path = tmp_path / "schema.yaml"
    _write_schema(schema_path)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "logging": {"level": "INFO", "log_dir": str(tmp_path / "logs")},
                "pipeline": {"chunk_size": 7},
                "schema": {"path": str(schema_path), "fail_on_invalid": True},
            }
        )
    )

    output_dir = tmp_path / "output"
    exit_code = run_pipeline_streaming(str(csv_path), str(config_path), str(output_dir))

    assert exit_code == 0
    assert (output_dir / "validated_records.parquet").exists()
    assert (output_dir / "rejected_records.jsonl").exists()
    assert (output_dir / "missing_summary.csv").exists()

    result_df = pd.read_parquet(output_dir / "validated_records.parquet")
    assert len(result_df) == 40


def test_run_pipeline_streaming_fails_fast_on_schema_violation(tmp_path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("patient_nbr,gender,age\n1,Male,forty\n2,Female,30\n")

    schema_path = tmp_path / "schema.yaml"
    _write_schema(schema_path)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "logging": {"level": "INFO", "log_dir": str(tmp_path / "logs")},
                "pipeline": {"chunk_size": 10},
                "schema": {"path": str(schema_path), "fail_on_invalid": True},
            }
        )
    )

    from healthcli.pipeline import SchemaValidationFailed

    with pytest.raises(SchemaValidationFailed):
        run_pipeline_streaming(str(csv_path), str(config_path), str(tmp_path / "output"))
