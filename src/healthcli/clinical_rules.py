from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass
class RuleResult:
    """
    Docstring for RuleResult
    """
    rule: str
    severity: str  # "OK", "WARNING", "ERROR"
    message: str
    affected_rows: Optional[int] = None


class ClinicalRule(ABC):
    """
    Internal abstract base class that defines the contract for all clinical data quality checks
    """
    name: str

    @abstractmethod
    def apply(self, df: pd.DataFrame) -> List[RuleResult]:
        pass


class PatientSexConsistencyRule(ClinicalRule):
    """
    Checks whether a single patient_id is associated with multiple sex values.
    """
    name = "patient_sex_consistency"

    def apply(self, df: pd.DataFrame) -> List[RuleResult]:
        """ Apply the patient sex consistency rule. """
        if "patient_id" not in df.columns or "sex" not in df.columns:
            return [
                RuleResult(
                    rule=self.name,
                    severity="WARNING",
                    message="Required columns (patient_id, sex) are missing",
                )
            ]

        inconsistent = (
            df.groupby("patient_id")["sex"]
            .nunique(dropna=True)
            .loc[lambda x: x > 1]
        )

        if inconsistent.empty:
            return [
                RuleResult(
                    rule=self.name,
                    severity="OK",
                    message="No patient-level sex inconsistencies detected",
                    affected_rows=0,
                )
            ]

        return [
            RuleResult(
                rule=self.name,
                severity="ERROR",
                message="Patient has conflicting sex values across records",
                affected_rows=int(inconsistent.sum()),
            )
        ]
    
class AgePlausibilityRule(ClinicalRule):
    """
    Checks whether age values are within a plausible human range.
    """
    name = "age_plausibility"

    def apply(self, df: pd.DataFrame) -> list[RuleResult]:
        if "age" not in df.columns:
            return [
                RuleResult(
                    rule=self.name,
                    severity="WARNING",
                    message="Column 'age' is missing",
                )
            ]

        invalid = df[(df["age"] < 0) | (df["age"] > 120)]

        if invalid.empty:
            return [
                RuleResult(
                    rule=self.name,
                    severity="OK",
                    message="All age values are within plausible range",
                    affected_rows=0,
                )
            ]

        return [
            RuleResult(
                rule=self.name,
                severity="WARNING",
                message="Implausible age values detected",
                affected_rows=len(invalid),
            )
        ]