from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass
class RuleResult:
    """
    Simple data container for the output of a single data quality rule.

    @dataclass is used here to automatically generate:
    __init__
    __repr__
    __eq__

    This avoids boilerplate code and clearly signals that this class
    exists only to hold structured data.
    """
    rule: str                            # Name of the rule that produced this result
    severity: str                        # "OK", "WARNING", or "ERROR"
    message: str                         # Human-readable explanation
    affected_rows: Optional[int] = None  # Optional quantitative impact


class ClinicalRule(ABC):
    """
    Abstract Base Class defining the interface for all clinical data quality rules.

    This class does NOT implement any rule logic itself.
    Instead, it defines a contract that all concrete rules must follow.

    @abstractmethod is used to enforce that:
    - every subclass MUST implement apply()
    - incomplete rule implementations fail fast at runtime
    """
    name: str  # Identifier used for reporting and logging

    @abstractmethod
    def apply(self, df: pd.DataFrame) -> List[RuleResult]:
        """
        Execute the rule against the input DataFrame.

        Must be implemented by all subclasses.
        Returns one or more RuleResult objects.
        """
        pass


class PatientSexConsistencyRule(ClinicalRule):
    """
    Concrete implementation of a clinical data quality rule.

    This rule checks whether a single patient_id is associated
    with multiple recorded sex values, which may indicate data entry or linkage errors.
    """
    name = "patient_sex_consistency"

    def apply(self, df: pd.DataFrame) -> List[RuleResult]:
        """
        Implements the rule-specific logic defined by the ClinicalRule contract.
        """
        if "patient_id" not in df.columns or "sex" not in df.columns:
            return [
                RuleResult(
                    rule=self.name,
                    severity="WARNING",
                    message="Required columns (patient_id, sex) are missing",
                )
            ]

        # Count number of unique sex values per patient
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
    Concrete rule checking whether age values fall within a plausible human range.
    This is a general sanity check and does not encode dataset or disease specific clinical criteria.
    """
    name = "age_plausibility"

    def apply(self, df: pd.DataFrame) -> List[RuleResult]:
        """
        Rule-specific implementation required by ClinicalRule.
        """
        if "age" not in df.columns:
            return [
                RuleResult(
                    rule=self.name,
                    severity="WARNING",
                    message="Column 'age' is missing",
                )
            ]

        # Identify implausible values
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