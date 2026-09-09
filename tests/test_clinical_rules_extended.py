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
