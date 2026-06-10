from pathlib import Path
import logging
from typing import Tuple

from healthcli.data_loader import load_csv_data
from healthcli.config_loader import load_config
from healthcli.logging_utils import setup_logger
from healthcli.quality import missing_summary


def ingest(data_path: str) -> Tuple[object, int]:
    df = load_csv_data(data_path)
    return df, len(df)


def validate(df, config: dict) -> dict:
    # Minimal validation: report missing value summary
    logger = logging.getLogger("healthcli.pipeline")
    summary = missing_summary(df, logger, config)
    return {"missing_summary": summary}


def transform(df, config: dict):
    # Placeholder transform: no-op currently
    return df


def run_pipeline(data_path: str, config_path: str, output_dir: str) -> int:
    config = load_config(config_path)
    logger = setup_logger("healthcli.pipeline", level=config.get("logging", {}).get("level", "INFO"), log_dir=config.get("logging", {}).get("log_dir", "logs"))

    logger.info("Pipeline started: ingest -> validate -> transform")

    df, rows = ingest(data_path)
    logger.info("Ingested %d rows from %s", rows, data_path)

    results = validate(df, config)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save a simple CSV of missing summary
    ms = results.get("missing_summary")
    if hasattr(ms, "to_csv"):
        ms.to_csv(out_dir / "missing_summary.csv")
        logger.info("Missing summary written to %s", out_dir / "missing_summary.csv")

    # Transform (no-op)
    _ = transform(df, config)

    logger.info("Pipeline completed successfully")
    return 0
