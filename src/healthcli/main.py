from data_loader import load_csv_data
from quality import (
    dataset_overview,
    missing_summary,
    numeric_summary,
)
from logging_utils import setup_logger
from config_loader import load_config


def main():
    data_path = "data/diabetic_data.csv"
    config_path = "config/config.yaml"

    logger = setup_logger()
    logger.info("Starting clinical data quality analysis")

    # Load config
    config = load_config(config_path)
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
    print(missing.head())

    # Numeric summary
    numeric = numeric_summary(df, logger)

    print("\n=== Numeric Summary (Top rows) ===")
    print(numeric.head())

    logger.info("Data quality analysis completed successfully")


if __name__ == "__main__":
    main()