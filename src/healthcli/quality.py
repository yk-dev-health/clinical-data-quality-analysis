import logging
from typing import Any, Dict, cast

import pandas as pd

from healthcli.fhir_validator import validate_dataframe


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


def fhir_validation_summary(df: pd.DataFrame, logger: logging.Logger) -> Dict[str, Any]:
    """
    Validate dataset patient/lab/vital-sign columns against the strict FHIR
    R4-inspired models in `healthcli.fhir_validator` -- the same models and
    the same row-to-resource mapping used by the streaming pipeline path, so
    results do not depend on which execution mode produced them.
    """
    if "patient_nbr" not in df.columns:
        logger.debug("FHIR validation skipped: patient_nbr column missing")
        return {
            "patients_validated": 0,
            "patient_errors": 0,
            "observations_validated": 0,
            "observation_errors": 0,
            "errors": [],
        }

    summary = validate_dataframe(df)
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