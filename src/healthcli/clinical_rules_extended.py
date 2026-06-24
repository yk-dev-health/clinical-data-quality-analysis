"""
Clinical domain-specific validation rules.

These rules encode medical knowledge about data coherence, plausibility,
and clinical patterns. They operate on pandas DataFrames and return
structured RuleResult objects for analysis and reporting.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import pandas as pd


@dataclass
class RuleResult:
    """
    Structured result from a validation rule.
    
    Attributes:
        rule_name: Name of the rule (e.g., 'ClinicalCoherenceRule')
        violations: List of row indices that violate the rule
        count: Number of violations
        severity: 'ERROR' or 'WARNING'
        details: Dict with additional context (e.g., age threshold, value range)
    """
    rule_name: str
    violations: List[int] = field(default_factory=list)
    count: int = 0
    severity: str = "WARNING"
    details: Dict = field(default_factory=dict)


class ClinicalCoherenceRule:
    """
    Validates age/lab coherence.
    
    Example: Pediatric patients (age < 12) with glucose > 300 mg/dL is unusual
    and should be flagged as a WARNING (possibly misrecorded age or severe DKA).
    
    Similarly, geriatric patients (age >= 65) with creatinine > 2.0 mg/dL
    is expected but still flagged if combined with other risk factors.
    """
    
    def apply(self, df: pd.DataFrame, logger: logging.Logger = None) -> RuleResult:
        """
        Check age/lab value coherence.
        
        Returns violations where:
        - Age < 12 AND glucose > 300: WARNING (pediatric hyperglycemia)
        - Age >= 65 AND creatinine > 2.0: WARNING (geriatric renal impairment)
        """
        result = RuleResult(rule_name="ClinicalCoherenceRule", severity="WARNING")
        violations = []
        
        # Check pediatric hyperglycemia (age < 12 and glucose > 300)
        if "age" in df.columns and "glucose" in df.columns:
            pediatric_hyperglycemia = (
                (df["age"] < 12) & (pd.to_numeric(df["glucose"], errors="coerce") > 300)
            )
            violations.extend(df[pediatric_hyperglycemia].index.tolist())
        
        # Check geriatric renal impairment (age >= 65 and creatinine > 2.0)
        if "age" in df.columns and "creatinine" in df.columns:
            geriatric_renal = (
                (df["age"] >= 65) & (pd.to_numeric(df["creatinine"], errors="coerce") > 2.0)
            )
            violations.extend(df[geriatric_renal].index.tolist())
        
        result.violations = list(set(violations))  # Remove duplicates
        result.count = len(result.violations)
        
        if logger:
            logger.warning(
                f"{result.rule_name}: found {result.count} age/lab coherence violations"
            )
        
        return result


class VitalSignAnomalyRule:
    """
    Detects temporal anomalies in vital sign sequences.
    
    Flags measurements that change > 50% in a single reading
    (e.g., systolic BP jumping from 120 to 180 mmHg between consecutive
    measurements for the same patient). This may indicate:
    - Data entry error
    - Equipment malfunction
    - Rapid decompensation (rare but critical)
    
    NOTE: Requires data sorted by patient_id and timestamp.
    """
    
    def detect_spike(
        self, df: pd.DataFrame, vital_column: str, threshold_pct: float = 50.0
    ) -> List[int]:
        """
        Detect > 50% change in a vital sign within same patient.
        
        Returns list of row indices with anomalies.
        """
        if vital_column not in df.columns:
            return []
        
        anomalies = []
        
        # Group by patient_id, sort by timestamp
        if "patient_id" not in df.columns:
            return anomalies
        
        for patient_id, group in df.groupby("patient_id", sort=False):
            if "timestamp" in group.columns:
                group = group.sort_values("timestamp")
            
            values = pd.to_numeric(group[vital_column], errors="coerce").values
            indices = group.index.tolist()
            
            # Compare consecutive measurements
            for i in range(1, len(values)):
                prev_val = values[i - 1]
                curr_val = values[i]
                
                # Skip if either value is NaN or zero
                if pd.isna(prev_val) or pd.isna(curr_val) or prev_val == 0:
                    continue
                
                # Calculate percentage change
                pct_change = abs((curr_val - prev_val) / prev_val) * 100
                
                if pct_change > threshold_pct:
                    anomalies.append(indices[i])
        
        return anomalies
    
    def apply(self, df: pd.DataFrame, logger: logging.Logger = None) -> RuleResult:
        """
        Check for vital sign anomalies (spikes > 50%) in systolic BP, heart rate, etc.
        """
        result = RuleResult(rule_name="VitalSignAnomalyRule", severity="WARNING")
        violations = []
        
        # Check common vital signs
        for vital in ["systolic_bp", "heart_rate", "temperature", "spo2"]:
            violations.extend(self.detect_spike(df, vital))
        
        result.violations = list(set(violations))
        result.count = len(result.violations)
        
        if logger:
            logger.warning(f"{result.rule_name}: found {result.count} vital sign anomalies")
        
        return result


class MissingDataThresholdRule:
    """
    Context-aware missing data detection.
    
    Different columns have different acceptable missing rates:
    - patient_id: Must be 100% complete (0% missing allowed)
    - age: Low tolerance (~5% missing)
    - lab values: Moderate tolerance (~20% missing)
    - vitals: Higher tolerance (~30% missing)
    """
    
    # Default thresholds: column_name -> max_missing_pct
    DEFAULT_THRESHOLDS = {
        "patient_id": 0.0,
        "age": 5.0,
        "gender": 10.0,
        "glucose": 20.0,
        "creatinine": 20.0,
        "systolic_bp": 30.0,
        "heart_rate": 30.0,
        "temperature": 30.0,
        "spo2": 30.0,
    }
    
    def apply(
        self,
        df: pd.DataFrame,
        thresholds: Optional[Dict[str, float]] = None,
        logger: logging.Logger = None,
    ) -> RuleResult:
        """
        Check missing data rates against context-aware thresholds.
        
        Returns violations for columns exceeding threshold.
        """
        result = RuleResult(rule_name="MissingDataThresholdRule", severity="WARNING")
        
        if thresholds is None:
            thresholds = self.DEFAULT_THRESHOLDS
        
        violations = []
        details_by_column = {}
        
        for col in df.columns:
            missing_pct = (df[col].isna().sum() / len(df)) * 100
            threshold = thresholds.get(col, 50.0)  # Default 50% if not specified
            
            details_by_column[col] = {
                "missing_pct": round(missing_pct, 2),
                "threshold_pct": threshold,
                "exceeds": missing_pct > threshold,
            }
            
            if missing_pct > threshold:
                violations.append(col)
        
        result.violations = violations
        result.count = len(violations)
        result.details = details_by_column
        
        if logger:
            logger.warning(
                f"{result.rule_name}: {result.count} column(s) exceed missing data threshold"
            )
            for col in violations:
                info = details_by_column[col]
                logger.warning(
                    f"  {col}: {info['missing_pct']}% missing (threshold: {info['threshold_pct']}%)"
                )
        
        return result


def run_clinical_rules(
    df: pd.DataFrame, logger: logging.Logger = None
) -> Dict[str, RuleResult]:
    """
    Execute all clinical validation rules on the DataFrame.
    
    Returns dict mapping rule_name -> RuleResult for further analysis.
    
    Usage:
        results = run_clinical_rules(df, logger)
        for rule_name, result in results.items():
            print(f"{rule_name}: {result.count} violations")
    """
    if logger is None:
        logger = logging.getLogger("healthcli.clinical_rules_extended")
    
    results = {}
    
    # Run each rule
    coherence_rule = ClinicalCoherenceRule()
    results["ClinicalCoherenceRule"] = coherence_rule.apply(df, logger)
    
    vital_anomaly_rule = VitalSignAnomalyRule()
    results["VitalSignAnomalyRule"] = vital_anomaly_rule.apply(df, logger)
    
    missing_rule = MissingDataThresholdRule()
    results["MissingDataThresholdRule"] = missing_rule.apply(df, logger=logger)
    
    return results
