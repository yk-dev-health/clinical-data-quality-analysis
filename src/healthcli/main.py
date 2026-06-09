"""
Entry point for clinical data quality analysis.

This module controls the overall workflow of the analysis.
It loads the configuration and dataset, runs data quality checks,
and logs results for transparency.

This file does not contain analysis logic.
All analysis steps are implemented in separate modules
to keep the pipeline simple, reusable, and easy to test.
"""

from healthcli.cli import build_parser
from healthcli.config_loader import load_config
from healthcli.data_loader import load_csv_data
from healthcli.logging_utils import setup_logger
from healthcli.quality import (
    categorical_summary,
    dataset_overview,
    exclusion_candidates,
    missing_summary,
    numeric_summary,
)


def run_quality(data_path: str, config_path: str) -> int:
    """Run the quality analysis workflow with the provided dataset and config."""
    config = load_config(config_path)
    log_level = config["logging"]["level"]
    log_dir = config["logging"]["log_dir"]

    logger = setup_logger(__name__, level=log_level, log_dir=log_dir)
    logger.info("Starting clinical data quality analysis")
    logger.info("Configuration loaded from: %s", config_path)

    logger.info("Loading dataset from: %s", data_path)
    df = load_csv_data(data_path)

    overview = dataset_overview(df, logger)
    print("=== Dataset Overview ===")
    print(overview)

    missing = missing_summary(df, logger, config)
    print("\n=== Missing Value Summary (Top columns) ===")
    top_n = config["quality"]["missing"]["report_top_n_columns"]
    print(missing.head(top_n))

    if config["quality"]["numeric_summary"]["enabled"]:
        numeric = numeric_summary(df, logger)
        print("\n=== Numeric Summary (Top rows) ===")
        print(numeric.head())

    candidates = exclusion_candidates(missing, logger, config)
    print("\n=== Exclusion Candidates (Decision Support) ===")
    print(candidates)

    categorical = categorical_summary(df, logger, config)
    print("\n=== Categorical Summary (Top values per column) ===")
    for col, summary in categorical.items():
        print(f"\n[{col}]")
        print(summary)

    logger.info("Data quality analysis completed successfully")
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "quality":
        config_path = args.config or "config/config.yaml"
        return run_quality(args.data, config_path)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
