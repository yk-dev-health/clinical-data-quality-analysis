import pandas as pd

from healthcli.clinical_rules import PatientSexConsistencyRule, AgePlausibilityRule

def test_patient_sex_inconsistency_detected():
    df = pd.DataFrame(
        {
            "patient_id": [1, 1, 2],
            "sex": ["M", "F", "F"],
        }
    )

    rule = PatientSexConsistencyRule()
    results = rule.apply(df)

    assert len(results) == 1
    assert results[0].severity == "ERROR"


def test_patient_sex_consistent_ok():
    df = pd.DataFrame(
        {
            "patient_id": [1, 1, 2],
            "sex": ["M", "M", "F"],
        }
    )

    rule = PatientSexConsistencyRule()
    results = rule.apply(df)

    assert results[0].severity == "OK"


def test_age_plausibility_flags_invalid_age():
    df = pd.DataFrame({"age": [-1, 25, 200]})

    rule = AgePlausibilityRule()
    results = rule.apply(df)

    assert results[0].severity == "WARNING"
    assert results[0].affected_rows == 2
