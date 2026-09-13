import pandas as pd

from healthcli.fhir_validator import validate_dataframe


def test_valid_rows_are_cleared_by_the_vectorized_fast_path_without_errors():
    """Rows that are obviously fine (well-formed id, known gender, in-range
    vitals/labs) should validate cleanly -- the fast path is expected to
    clear them without ever needing the per-row Pydantic fallback."""
    df = pd.DataFrame(
        {
            "patient_nbr": ["1", "2", "3"],
            "gender": ["male", "female", "other"],
            "max_glu_serum": [150, 180, None],
            "systolic_bp": [110, 130, 120],
        }
    )

    summary = validate_dataframe(df)

    assert summary["patients_validated"] == 3
    assert summary["patient_errors"] == 0
    assert summary["observation_errors"] == 0
    assert summary["errors"] == []


def test_invalid_patient_id_is_rejected():
    df = pd.DataFrame({"patient_nbr": ["", "2"], "gender": ["male", "female"]})

    summary = validate_dataframe(df)

    assert summary["patient_errors"] == 1
    assert summary["patients_validated"] == 1


def test_future_birth_date_is_rejected():
    df = pd.DataFrame(
        {
            "patient_nbr": ["1"],
            "gender": ["male"],
            "birthDate": ["2999-01-01"],
        }
    )

    summary = validate_dataframe(df)

    assert summary["patient_errors"] == 1
    assert "birthDate" in summary["errors"][0]


def test_unparsable_birth_date_falls_through_to_pydantic_and_is_rejected():
    df = pd.DataFrame({"patient_nbr": ["1"], "gender": ["male"], "birthDate": ["not-a-date"]})

    summary = validate_dataframe(df)

    assert summary["patient_errors"] == 1


def test_valid_past_birth_date_is_accepted_by_the_fast_path():
    df = pd.DataFrame({"patient_nbr": ["1"], "gender": ["male"], "birthDate": ["1990-01-01"]})

    summary = validate_dataframe(df)

    assert summary["patients_validated"] == 1
    assert summary["patient_errors"] == 0


def test_non_numeric_lab_value_is_rejected_without_needing_pydantic():
    df = pd.DataFrame({"patient_nbr": ["1"], "gender": ["male"], "max_glu_serum": ["not-a-number"]})

    summary = validate_dataframe(df)

    assert summary["observation_errors"] == 1
    assert "non-numeric" in summary["errors"][0]


def test_out_of_range_vital_sign_is_rejected():
    df = pd.DataFrame({"patient_nbr": ["1"], "gender": ["male"], "systolic_bp": [999999]})

    summary = validate_dataframe(df)

    assert summary["observation_errors"] == 1
    assert summary["observations_validated"] == 0


def test_in_range_vital_signs_are_all_validated_across_columns():
    df = pd.DataFrame(
        {
            "patient_nbr": ["1", "2", "3"],
            "gender": ["male", "female", "unknown"],
            "systolic_bp": [110, 120, 130],
            "heart_rate": [70, 80, 90],
            "temperature": [36.5, 37.0, 37.2],
            "spo2": [98, 97, 99],
        }
    )

    summary = validate_dataframe(df)

    assert summary["observations_validated"] == 12  # 3 rows x 4 vital columns
    assert summary["observation_errors"] == 0


def test_missing_patient_nbr_column_returns_zeroed_summary():
    df = pd.DataFrame({"other_column": [1, 2, 3]})

    summary = validate_dataframe(df)

    assert summary["patients_validated"] == 0
    assert summary["observations_validated"] == 0
    assert summary["errors"] == []


def test_rejected_values_never_appear_in_error_messages():
    """Audit-safety invariant: error text may name a row index and column,
    but never the rejected value itself (see ADR referenced in
    fhir_validator.py's `_describe_validation_error`)."""
    df = pd.DataFrame(
        {
            "patient_nbr": ["SECRET-ID-999"],
            "gender": ["male"],
            "systolic_bp": [123456],
        }
    )

    summary = validate_dataframe(df)

    serialized = str(summary)
    assert "123456" not in serialized
