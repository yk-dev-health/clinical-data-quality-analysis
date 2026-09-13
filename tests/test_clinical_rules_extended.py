import pandas as pd

from healthcli.clinical_rules_extended import (
    AgePlausibilityRule,
    ClinicalCoherenceRule,
    MissingDataThresholdRule,
    PatientSexConsistencyRule,
    VitalSignAnomalyRule,
    run_clinical_rules,
)


def test_patient_sex_inconsistency_detected():
    df = pd.DataFrame({"patient_id": [1, 1, 2], "sex": ["M", "F", "F"]})

    result = PatientSexConsistencyRule().apply(df)

    assert result.severity == "ERROR"
    assert result.count == 2
    assert set(result.violations) == {0, 1}


def test_patient_sex_consistent_reports_no_violations():
    df = pd.DataFrame({"patient_id": [1, 1, 2], "sex": ["M", "M", "F"]})

    result = PatientSexConsistencyRule().apply(df)

    assert result.count == 0
    assert result.violations == []


def test_patient_sex_consistency_skips_when_columns_missing():
    df = pd.DataFrame({"other": [1, 2, 3]})

    result = PatientSexConsistencyRule().apply(df)

    assert result.count == 0


def test_age_plausibility_flags_implausible_values():
    df = pd.DataFrame({"age": [-1, 25, 200]})

    result = AgePlausibilityRule().apply(df)

    assert result.severity == "WARNING"
    assert result.count == 2
    assert set(result.violations) == {0, 2}


def test_age_plausibility_all_valid_reports_no_violations():
    df = pd.DataFrame({"age": [0, 45, 120]})

    result = AgePlausibilityRule().apply(df)

    assert result.count == 0


def test_age_plausibility_skips_when_column_missing():
    df = pd.DataFrame({"other": [1, 2, 3]})

    result = AgePlausibilityRule().apply(df)

    assert result.count == 0


def test_clinical_coherence_flags_pediatric_hyperglycemia():
    df = pd.DataFrame({"age": [5, 30], "glucose": [350, 100]})

    result = ClinicalCoherenceRule().apply(df)

    assert result.count == 1
    assert result.violations == [0]


def test_vital_sign_anomaly_detects_spike():
    df = pd.DataFrame(
        {
            "patient_id": [1, 1, 1],
            "timestamp": [1, 2, 3],
            "systolic_bp": [120, 122, 200],
        }
    )

    result = VitalSignAnomalyRule().apply(df)

    assert result.count == 1


def test_vital_sign_anomaly_ignores_cross_patient_jumps():
    """A spike must only be compared against the same patient's previous
    reading, never against a neighboring patient's row."""
    df = pd.DataFrame(
        {
            "patient_id": [1, 2],
            "timestamp": [1, 1],
            "systolic_bp": [120, 400],
        }
    )

    result = VitalSignAnomalyRule().apply(df)

    assert result.count == 0


def test_vital_sign_anomaly_orders_by_timestamp_even_when_rows_are_unsorted():
    df = pd.DataFrame(
        {
            "patient_id": [1, 1, 1],
            "timestamp": [3, 1, 2],
            "systolic_bp": [200, 120, 122],
        }
    )

    result = VitalSignAnomalyRule().detect_spike(df, "systolic_bp")

    # Chronological order is 120 -> 122 -> 200; only the last jump spikes,
    # and it must be reported against the row holding timestamp=3.
    assert result == [0]


def test_vital_sign_anomaly_skips_zero_previous_value():
    df = pd.DataFrame(
        {
            "patient_id": [1, 1],
            "timestamp": [1, 2],
            "systolic_bp": [0, 120],
        }
    )

    result = VitalSignAnomalyRule().detect_spike(df, "systolic_bp")

    assert result == []


def test_missing_data_threshold_flags_column_over_threshold():
    df = pd.DataFrame({"patient_id": [1, None, None]})

    result = MissingDataThresholdRule().apply(df)

    assert "patient_id" in result.violations


def test_run_clinical_rules_includes_all_rules():
    df = pd.DataFrame(
        {
            "patient_id": [1, 1, 2],
            "sex": ["M", "F", "F"],
            "age": [-1, 45, 30],
        }
    )

    results = run_clinical_rules(df)

    assert set(results.keys()) == {
        "ClinicalCoherenceRule",
        "VitalSignAnomalyRule",
        "MissingDataThresholdRule",
        "PatientSexConsistencyRule",
        "AgePlausibilityRule",
    }
    assert results["PatientSexConsistencyRule"].count == 2
    assert results["AgePlausibilityRule"].count == 1
