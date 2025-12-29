import pandas as pd
import logging
from typing import Dict, Any


def dataset_overview(df: pd.DataFrame, logger: logging.Logger) -> Dict[str, Any]:
    """
    Logs basic dataset dimensions and returns structural metadata.
    """
    overview = {
        "rows": len(df),
        "columns": df.columns.tolist(),
        "dtypes": df.dtypes.astype(str).to_dict(),
    }

    logger.info(
        "Dataset overview: rows=%d, columns=%d",
        overview["rows"],
        len(overview["columns"]),
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

    return summary