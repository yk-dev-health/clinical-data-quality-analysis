import logging

import pandas as pd
import pytest

from healthcli.quality import fhir_validation_summary, missing_summary


@pytest.fixture
def logger():
    return logging.getLogger("test.quality")


def test_missing_summary_reports_counts_and_ratios(logger):
    df = pd.DataFrame({"a": [1, None, 3], "b": [1, 2, 3]})
    config = {"quality": {"missing": {"warning_threshold": 0.9, "critical_threshold": 0.99}}}

    summary = missing_summary(df, logger, config)

    assert summary.loc["a", "missing_count"] == 1
    assert summary.loc["a", "missing_ratio"] == pytest.approx(1 / 3)
    assert summary.loc["b", "missing_count"] == 0


def test_fhir_validation_summary_counts_valid_patients(logger):
    df = pd.DataFrame({"patient_nbr": ["1", "2"], "gender": ["male", "female"]})

    summary = fhir_validation_summary(df, logger)

    assert summary["patients_validated"] == 2
    assert summary["patient_errors"] == 0
    assert summary["errors"] == []


def test_fhir_validation_summary_never_leaks_rejected_patient_identifier(logger):
    df = pd.DataFrame(
        {
            "patient_nbr": ["SECRET-PATIENT-ID-000123"],
            "gender": ["male"],
            "birthDate": ["2999-01-01"],
        }
    )

    summary = fhir_validation_summary(df, logger)

    assert summary["patient_errors"] == 1
    serialized = str(summary)
    assert "SECRET-PATIENT-ID-000123" not in serialized
    assert "2999-01-01" not in serialized
    # The error is still informative: row index, field, and error category.
    assert "birthDate" in summary["errors"][0]


def test_fhir_validation_summary_never_leaks_rejected_vital_sign_value(logger):
    df = pd.DataFrame(
        {
            "patient_nbr": ["1"],
            "gender": ["male"],
            "systolic_bp": [999999],
        }
    )

    summary = fhir_validation_summary(df, logger)

    assert summary["observation_errors"] == 1
    serialized = str(summary)
    assert "999999" not in serialized
    assert "systolic_bp" in summary["errors"][0]


def test_fhir_validation_summary_skips_when_columns_missing(logger):
    df = pd.DataFrame({"other_column": [1, 2, 3]})

    summary = fhir_validation_summary(df, logger)

    assert summary["patients_validated"] == 0
    assert summary["patient_errors"] == 0
