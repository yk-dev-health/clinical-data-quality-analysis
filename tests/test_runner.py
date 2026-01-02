import pandas as pd

from healthcli.clinical_rules import PatientSexConsistencyRule
from healthcli.runner import RuleRunner


def test_runner_executes_rules():
    df = pd.DataFrame({
        "patient_id": [1, 1, 2],
        "sex": ["M", "F", "F"],
    })

    rules = [PatientSexConsistencyRule()]
    runner = RuleRunner(rules)

    results = runner.run(df)

    assert len(results) == 1
    assert results[0].rule == "patient_sex_consistency"
    assert results[0].severity == "ERROR"