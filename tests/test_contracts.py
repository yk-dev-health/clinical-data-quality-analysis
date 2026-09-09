import pytest
from pydantic import ValidationError

from healthcli.contracts import (
    ProcessingRequest,
    ProcessingResult,
    RecordOutcome,
    process_request,
)


SCHEMA_YAML = """
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


@pytest.fixture
def schema_path(tmp_path):
    path = tmp_path / "schema.yaml"
    path.write_text(SCHEMA_YAML)
    return str(path)


def test_processing_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ProcessingRequest(request_id="r1", records=[{"a": 1}], unexpected_field="x")


def test_processing_request_requires_at_least_one_record():
    with pytest.raises(ValidationError):
        ProcessingRequest(request_id="r1", records=[])


def test_process_request_all_valid_records(schema_path):
    request = ProcessingRequest(
        request_id="req-1",
        records=[
            {"patient_nbr": "1", "gender": "Male", "age": 45},
            {"patient_nbr": "2", "gender": "Female", "age": 60},
        ],
    )
    result = process_request(request, schema_path=schema_path)

    assert isinstance(result, ProcessingResult)
    assert result.outcome == RecordOutcome.VALIDATED
    assert result.total_records == 2
    assert result.validated_count == 2
    assert result.rejected_count == 0
    assert result.rejected_records == []


def test_process_request_flags_invalid_records_without_leaking_values(schema_path):
    request = ProcessingRequest(
        request_id="req-2",
        records=[
            {"patient_nbr": "1", "gender": "Male", "age": 45},
            {"patient_nbr": "2", "gender": "Alien", "age": "not-a-number"},
        ],
    )
    result = process_request(request, schema_path=schema_path)

    assert result.outcome == RecordOutcome.REJECTED
    assert result.validated_count == 1
    assert result.rejected_count == 1

    rejected = result.rejected_records[0]
    assert rejected.record_index == 1
    serialized = result.model_dump_json()
    assert "Alien" not in serialized
    assert "not-a-number" not in serialized


def test_process_request_missing_required_column_rejects_all_rows(schema_path):
    request = ProcessingRequest(
        request_id="req-3",
        records=[{"patient_nbr": "1", "age": 45}, {"patient_nbr": "2", "age": 60}],
    )
    result = process_request(request, schema_path=schema_path)

    assert result.outcome == RecordOutcome.REJECTED
    assert result.rejected_count == 2
    assert all(r.error_type == "missing_column" for r in result.rejected_records)


def test_processing_result_is_json_serializable(schema_path):
    request = ProcessingRequest(
        request_id="req-4",
        records=[{"patient_nbr": "1", "gender": "Male", "age": 45}],
    )
    result = process_request(request, schema_path=schema_path)
    payload = result.model_dump_json()
    assert "req-4" in payload


def test_result_outcome_is_stable_for_same_request(schema_path):
    request = ProcessingRequest(
        request_id="req-5",
        records=[{"patient_nbr": "1", "gender": "Male", "age": 45}],
    )
    result1 = process_request(request, schema_path=schema_path)
    result2 = process_request(request, schema_path=schema_path)
    assert result1.outcome == result2.outcome
    assert result1.validated_count == result2.validated_count
