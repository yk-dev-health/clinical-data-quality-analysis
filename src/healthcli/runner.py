from typing import List

import pandas as pd

from healthcli.clinical_rules import ClinicalRule, RuleResult


class RuleRunner:
    """
    Executes a list of ClinicalRule objects against a DataFrame.
    """

    def __init__(self, rules: List[ClinicalRule]):
        self.rules = rules

    def run(self, df: pd.DataFrame) -> List[RuleResult]:
        results: List[RuleResult] = []

        for rule in self.rules:
            rule_results = rule.apply(df)
            results.extend(rule_results)

        return results