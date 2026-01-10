"""
Entry point for clinical data quality analysis.

This module controls the overall workflow of the analysis.
It loads the configuration and dataset, runs data quality checks,
and logs results for transparency.

This file does not contain analysis logic.
All analysis steps are implemented in separate modules
to keep the pipeline simple, reusable, and easy to test.
"""

from data_loader import load_csv_data
from quality import (
    dataset_overview,
    missing_summary,
    numeric_summary,
    exclusion_candidates,
    categorical_summary,
)
from logging_utils import setup_logger
from config_loader import load_config

def main():
    """
    This function loads the configuration and dataset,
    runs each data quality check, and manages logging.
    """

    data_path = "data/diabetic_data.csv"
    config_path = "config/config.yaml"

    # Load config for logging and analysis parameters
    config = load_config(config_path)
    log_level = config["logging"]["level"]
    log_dir = config["logging"]["log_dir"]

    logger = setup_logger(__name__, level=log_level, log_dir=log_dir)
    logger.info("Starting clinical data quality analysis")
    logger.info("Configuration loaded from: %s", config_path)

    # Load data
    logger.info("Loading dataset from: %s", data_path)
    df = load_csv_data(data_path)

    # Dataset overview
    overview = dataset_overview(df, logger)
    print("=== Dataset Overview ===")
    print(overview)

    # Missing values analysis
    missing = missing_summary(df, logger, config)
    print("\n=== Missing Value Summary (Top columns) ===")
    top_n = config["quality"]["missing"]["report_top_n_columns"]
    print(missing.head(top_n))

    # Numeric summary (decision support)
    if config["quality"]["numeric_summary"]["enabled"]:
        numeric = numeric_summary(df, logger)
        print("\n=== Numeric Summary (Top rows) ===")
        print(numeric.head())

    # Exclusion candidates (decision support only)
    candidates = exclusion_candidates(missing, logger, config)
    print("\n=== Exclusion Candidates (Decision Support) ===")
    print(candidates)

    # Categorical summary (decision support)
    categorical = categorical_summary(df, logger, config)
    print("\n=== Categorical Summary (Top values per column) ===")
    for col, summary in categorical.items():
        print(f"\n[{col}]")
        print(summary)

    logger.info("Data quality analysis completed successfully")

if __name__ == "__main__":
    main()