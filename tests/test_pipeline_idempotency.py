import json

import pandas as pd
import yaml

from healthcli.pipeline import run_pipeline_streaming


def _write_sample_csv(path, rows: int = 20) -> None:
    lines = ["patient_nbr,gender,age"]
    for i in range(rows):
        gender = "Male" if i % 2 == 0 else "Female"
        lines.append(f"{2000 + i},{gender},{20 + (i % 50)}")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_schema(path) -> None:
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


def _write_config(path, schema_path, manifest_path, chunk_size=6) -> None:
    path.write_text(
        yaml.dump(
            {
                "logging": {"level": "INFO", "log_dir": str(path.parent / "logs")},
                "pipeline": {"chunk_size": chunk_size},
                "schema": {"path": str(schema_path), "fail_on_invalid": True},
                "idempotency": {
                    "enabled": True,
                    "manifest_path": str(manifest_path),
                    "hash_columns": ["patient_nbr", "gender", "age"],
                },
            }
        )
    )


def test_rerunning_unchanged_dataset_does_not_duplicate_output(tmp_path):
    csv_path = tmp_path / "data.csv"
    _write_sample_csv(csv_path, rows=20)

    schema_path = tmp_path / "schema.yaml"
    _write_schema(schema_path)

    manifest_path = tmp_path / "manifest.json"
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, schema_path, manifest_path)

    output_dir_1 = tmp_path / "output1"
    run_pipeline_streaming(str(csv_path), str(config_path), str(output_dir_1))
    first_run_df = pd.read_parquet(output_dir_1 / "validated_records.parquet")
    assert len(first_run_df) == 20

    output_dir_2 = tmp_path / "output2"
    run_pipeline_streaming(str(csv_path), str(config_path), str(output_dir_2))
    second_run_output = output_dir_2 / "validated_records.parquet"

    # Same dataset, same schema, same pipeline version -> all rows are
    # already recorded in the manifest, so the second run emits none (the
    # sink never opens a file when there is nothing new to write).
    assert not second_run_output.exists()


def test_manifest_records_rows_under_dataset_specific_run_id(tmp_path):
    csv_path = tmp_path / "data.csv"
    _write_sample_csv(csv_path, rows=10)

    schema_path = tmp_path / "schema.yaml"
    _write_schema(schema_path)

    manifest_path = tmp_path / "manifest.json"
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, schema_path, manifest_path)

    run_pipeline_streaming(str(csv_path), str(config_path), str(tmp_path / "output"))

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest_data) == 1
    run_id = next(iter(manifest_data))
    assert len(manifest_data[run_id]) == 10
    # Manifest keys must never be raw patient identifiers.
    assert "2000" not in json.dumps(manifest_data)


def test_changed_dataset_is_processed_as_new(tmp_path):
    schema_path = tmp_path / "schema.yaml"
    _write_schema(schema_path)
    manifest_path = tmp_path / "manifest.json"
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, schema_path, manifest_path)

    csv_path_1 = tmp_path / "data1.csv"
    _write_sample_csv(csv_path_1, rows=5)
    run_pipeline_streaming(str(csv_path_1), str(config_path), str(tmp_path / "output1"))

    csv_path_2 = tmp_path / "data2.csv"
    _write_sample_csv(csv_path_2, rows=8)
    run_pipeline_streaming(str(csv_path_2), str(config_path), str(tmp_path / "output2"))

    second_df = pd.read_parquet(tmp_path / "output2" / "validated_records.parquet")
    assert len(second_df) == 8
