import pandas as pd
import pytest

from healthcli.schema_validator import (
    ColumnSpec,
    DatasetSchema,
    SchemaConfigError,
    load_schema,
    validate_schema,
)


def make_schema() -> DatasetSchema:
    return DatasetSchema(
        version="1.0",
        columns=[
            ColumnSpec(name="patient_nbr", required=True, dtype="string"),
            ColumnSpec(name="age", required=True, dtype="integer"),
            ColumnSpec(name="gender", required=True, dtype="string", vocabulary=["Male", "Female"]),
            ColumnSpec(name="bmi", required=False, dtype="float"),
        ]
    )


def test_valid_dataset_passes():
    df = pd.DataFrame(
        {
            "patient_nbr": ["1", "2"],
            "age": [45, 60],
            "gender": ["Male", "Female"],
            "bmi": [22.5, 28.1],
        }
    )
    result = validate_schema(df, make_schema())
    assert result.is_valid
    assert result.missing_columns == []
    assert result.field_errors == []
    assert result.total_rows == 2


def test_missing_required_column_detected():
    df = pd.DataFrame({"age": [45], "gender": ["Male"]})
    result = validate_schema(df, make_schema())
    assert not result.is_valid
    assert "patient_nbr" in result.missing_columns


def test_invalid_type_reported_as_count_only():
    df = pd.DataFrame(
        {
            "patient_nbr": ["1", "2"],
            "age": ["forty-five", 60],
            "gender": ["Male", "Female"],
        }
    )
    result = validate_schema(df, make_schema())
    assert not result.is_valid
    error = next(e for e in result.field_errors if e.column == "age")
    assert error.error_type == "invalid_integer"
    assert error.row_count == 1
    # Structured result must never surface the rejected value itself.
    serialized = str(result.as_dict())
    assert "forty-five" not in serialized


def test_out_of_vocabulary_value_detected():
    df = pd.DataFrame(
        {
            "patient_nbr": ["1", "2"],
            "age": [45, 60],
            "gender": ["Male", "Alien"],
        }
    )
    result = validate_schema(df, make_schema())
    assert not result.is_valid
    error = next(e for e in result.field_errors if e.error_type == "out_of_vocabulary")
    assert error.column == "gender"
    assert error.row_count == 1


def test_optional_column_missing_values_not_flagged_as_type_error():
    df = pd.DataFrame(
        {
            "patient_nbr": ["1", "2"],
            "age": [45, 60],
            "gender": ["Male", "Female"],
            "bmi": [None, 28.1],
        }
    )
    result = validate_schema(df, make_schema())
    assert result.is_valid


def test_load_schema_from_yaml(tmp_path):
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(
        """
schema_version: "2.0"
columns:
  patient_id:
    required: true
    dtype: string
  status:
    required: false
    dtype: string
    vocabulary: [active, inactive]
"""
    )
    schema = load_schema(str(schema_file))
    assert schema.version == "2.0"
    assert schema.column_names() == ["patient_id", "status"]


def test_load_schema_rejects_missing_version(tmp_path):
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text("columns:\n  a:\n    required: true\n    dtype: string\n")
    with pytest.raises(SchemaConfigError):
        load_schema(str(schema_file))


def test_load_schema_rejects_unsupported_dtype(tmp_path):
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(
        'schema_version: "1.0"\ncolumns:\n  a:\n    required: true\n    dtype: weird_type\n'
    )
    with pytest.raises(SchemaConfigError):
        load_schema(str(schema_file))


def test_load_schema_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_schema("does/not/exist.yaml")
