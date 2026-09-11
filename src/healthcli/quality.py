import logging
from datetime import date
from typing import Any, Dict, Literal, Optional, cast

import pandas as pd
from pydantic import ValidationError

from healthcli.fhir_models import Observation, Patient, Quantity, VitalSigns


def dataset_overview(df: pd.DataFrame, logger: logging.Logger) -> Dict[str, Any]:
    """
    Logs basic dataset dimensions and returns structural metadata.
    """
    columns = df.columns.tolist()
    overview: Dict[str, Any] = {
        "rows": len(df),
        "columns": columns,
        "dtypes": df.dtypes.astype(str).to_dict(),
    }

    logger.info(
        "Dataset overview: rows=%d, columns=%d",
        overview["rows"],
        len(columns),
    )

    return overview


def missing_summary(df: pd.DataFrame, logger: logging.Logger, config: Dict[str, Any],) -> pd.DataFrame:
    """
    Summarise missing values per column and log data quality warnings
    based on configured thresholds.
    """
    missing_count = df.isna().sum()
    missing_ratio = missing_count / len(df)

    summary = (
        missing_count
        .to_frame(name="missing_count")
        .assign(missing_ratio=missing_ratio)
        .sort_values("missing_ratio", ascending=False)
    )

    max_missing = missing_ratio.max()
    worst_column = missing_ratio.idxmax()

    warning_threshold = config["quality"]["missing"]["warning_threshold"]
    critical_threshold = config["quality"]["missing"]["critical_threshold"]

    logger.info("Missing value summary calculated")

    if max_missing > warning_threshold:
        logger.warning(
            "Missing values detected (max_ratio=%.2f, column=%s)",
            max_missing,
            worst_column,
        )

    if max_missing > critical_threshold:
        logger.error(
            "Critical missing data level detected (max_ratio=%.2f, column=%s)",
            max_missing,
            worst_column,
        )

    return cast(pd.DataFrame, summary)


def _normalize_gender(value: Any) -> Literal["male", "female", "other", "unknown"]:
    if pd.isna(value):
        return "unknown"

    gender = str(value).strip().lower()
    if gender == "male":
        return "male"
    if gender == "female":
        return "female"
    if gender == "other":
        return "other"

    return "unknown"


def _describe_validation_error(resource: str, row_index: Any, exc: ValidationError) -> str:
    """Summarize a Pydantic ValidationError by field and error type only.

    `str(exc)` and `exc.errors()` both embed the rejected value by default
    (Pydantic's `input_value`), which would leak raw field data -- including
    patient identifiers -- into logs and the HTML report. This keeps only
    the row position, the offending field path, and the error category.
    """
    field_errors = exc.errors(include_url=False, include_input=False, include_context=False)
    reasons = ", ".join(f"{'.'.join(str(p) for p in e['loc']) or resource}:{e['type']}" for e in field_errors)
    return f"{resource} row {row_index}: {reasons}"


def fhir_validation_summary(df: pd.DataFrame, logger: logging.Logger) -> Dict[str, Any]:
    """
    Validate dataset rows against FHIR-inspired Pydantic models.

    This step is designed to demonstrate how clinical tabular data can be
    mapped to patient and observation resources and validated deterministically.
    """
    summary: Dict[str, Any] = {
        "patients_validated": 0,
        "patient_errors": 0,
        "observations_validated": 0,
        "observation_errors": 0,
        "errors": [],
    }

    # Patient-style validation
    if {"patient_nbr", "gender"}.issubset(df.columns):
        for idx, row in df.iterrows():
            birth_date: Optional[date] = (
                row["birthDate"] if "birthDate" in df.columns and pd.notna(row.get("birthDate")) else None
            )

            try:
                Patient(
                    id=str(row["patient_nbr"]),
                    gender=_normalize_gender(row.get("gender", "unknown")),
                    birthDate=birth_date,
                )
                summary["patients_validated"] += 1
            except ValidationError as exc:
                summary["patient_errors"] += 1
                summary["errors"].append(_describe_validation_error("Patient", idx, exc))
    else:
        logger.debug("FHIR patient validation skipped: required columns missing")

    # Observation-style validation for key clinical measurement columns
    lab_columns = ["max_glu_serum", "A1Cresult"]
    if "patient_nbr" in df.columns and any(col in df.columns for col in lab_columns):
        for col in lab_columns:
            if col not in df.columns:
                continue

            for idx, row in df.iterrows():
                if pd.isna(row[col]):
                    continue

                try:
                    value = float(row[col])
                except (TypeError, ValueError):
                    summary["observation_errors"] += 1
                    summary["errors"].append(f"Observation row {idx} column {col}: non-numeric value")
                    continue

                try:
                    Observation(
                        id=f"obs-{idx}-{col}",
                        code=col,
                        subject=str(row["patient_nbr"]),
                        value=Quantity(value=value, unit="mg/dL", code=col),
                    )
                    summary["observations_validated"] += 1
                except ValidationError as exc:
                    summary["observation_errors"] += 1
                    summary["errors"].append(_describe_validation_error(f"Observation ({col})", idx, exc))
    else:
        logger.debug("FHIR observation validation skipped: required columns missing")

    # Additional vital sign validation if the dataset contains those columns.
    vital_sign_cols = {
        "systolic_bp": "mmHg",
        "heart_rate": "bpm",
        "temperature": "C",
        "spo2": "%",
    }
    if "patient_nbr" in df.columns:
        for col, unit in vital_sign_cols.items():
            if col not in df.columns:
                continue

            for idx, row in df.iterrows():
                if pd.isna(row[col]):
                    continue

                try:
                    value = float(row[col])
                except (TypeError, ValueError):
                    summary["observation_errors"] += 1
                    summary["errors"].append(f"Vital sign row {idx} column {col}: non-numeric value")
                    continue

                try:
                    VitalSigns(
                        id=f"vital-{idx}-{col}",
                        code=col,
                        subject=str(row["patient_nbr"]),
                        value=Quantity(value=value, unit=unit, code=col),
                    )
                    summary["observations_validated"] += 1
                except ValidationError as exc:
                    summary["observation_errors"] += 1
                    summary["errors"].append(_describe_validation_error(f"Vital sign ({col})", idx, exc))

    logger.info(
        "FHIR-inspired validation completed: %d patients, %d observations",
        summary["patients_validated"],
        summary["observations_validated"],
    )
    return summary


def numeric_summary(df: pd.DataFrame, logger: logging.Logger,) -> pd.DataFrame:
    """
    Compute basic descriptive statistics for numeric columns.
    """
    numeric_df = df.select_dtypes(include="number")

    if numeric_df.empty:
        logger.warning("No numeric columns detected in dataset")
        return pd.DataFrame()

    summary = numeric_df.describe().T

    logger.info(
        "Numeric summary calculated for %d numeric columns",
        summary.shape[0],
    )

    return cast(pd.DataFrame, summary)


def exclusion_candidates(missing_summary: pd.DataFrame, logger: logging.Logger, config: Dict[str, Any],
) -> pd.DataFrame:
    """
    Identify columns that should be considered for exclusion
    due to high missing ratios (decision support only).
    """
    threshold = config["quality"]["missing"]["exclusion_candidate_threshold"]

    candidates = missing_summary[
        missing_summary["missing_ratio"] >= threshold
    ]

    if candidates.empty:
        logger.info("No exclusion candidates identified based on missing ratio")
    else:
        logger.warning(
            "Exclusion candidates identified: %d columns exceed missing ratio %.2f",
            candidates.shape[0],
            threshold,
        )

        for col, row in candidates.iterrows():
            logger.warning(
                "Candidate column: %s (missing_ratio=%.2f)",
                col,
                row["missing_ratio"],
            )

    return cast(pd.DataFrame, candidates)

def categorical_summary(df: pd.DataFrame, logger: logging.Logger, config: Dict[str, Any],) -> Dict[str, pd.Series]:
    """
    Summarise value counts for categorical columns.
    """
    cat_cols = df.select_dtypes(include="object").columns
    summaries = {}

    top_n = config["quality"]["categorical"]["report_top_n_values"]

    logger.info("Categorical summary started for %d columns", len(cat_cols))

    for col in cat_cols:
        value_counts = df[col].value_counts(dropna=False)
        summaries[col] = value_counts.head(top_n)

        logger.debug("Categorical column '%s': %d unique values", col, value_counts.shape[0],)
        
    logger.info("Categorical summary completed (%d columns analysed)", len(cat_cols),)

    return summaries