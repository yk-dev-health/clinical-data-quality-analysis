from pathlib import Path
import logging
from typing import Tuple

from healthcli.clinical_rules_extended import run_clinical_rules
from healthcli.data_loader import load_csv_data
from healthcli.config_loader import load_config
from healthcli.logging_utils import setup_logger
from healthcli.quality import fhir_validation_summary, missing_summary
from healthcli.quality_report import QualityReportGenerator


def ingest(data_path: str) -> Tuple[object, int]:
    df = load_csv_data(data_path)
    return df, len(df)


def validate(df, config: dict) -> dict:
    logger = logging.getLogger("healthcli.pipeline")
    summary = missing_summary(df, logger, config)
    clinical_violations = run_clinical_rules(df, logger)
    fhir_summary = fhir_validation_summary(df, logger)
    return {
        "missing_summary": summary,
        "clinical_violations": clinical_violations,
        "fhir_summary": fhir_summary,
    }


def transform(df, config: dict):
    # Placeholder transform: no-op currently
    return df


def run_pipeline(data_path: str, config_path: str, output_dir: str) -> int:
    config = load_config(config_path)
    logger = setup_logger(
        "healthcli.pipeline",
        level=config.get("logging", {}).get("level", "INFO"),
        log_dir=config.get("logging", {}).get("log_dir", "logs"),
    )

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

    # Generate HTML and PDF quality reports
    generator = QualityReportGenerator(logger=logger)
    html_path = out_dir / "quality_report.html"
    pdf_path = out_dir / "quality_report.pdf"

    missing_summary_for_report = {}
    if hasattr(ms, "iterrows"):
        for col, row in ms.iterrows():
            missing_summary_for_report[col] = {
                "count": int(row.get("missing_count", 0)),
                "pct": float(row.get("missing_ratio", 0.0)) * 100,
            }

    try:
        generator.generate_html_report(
            df,
            missing_summary=missing_summary_for_report,
            clinical_violations=results.get("clinical_violations"),
            fhir_summary=results.get("fhir_summary"),
            output_path=str(html_path),
        )
        logger.info("HTML report generated: %s", html_path)
    except Exception as exc:
        logger.error("Failed to generate HTML report: %s", exc)

    try:
        generator.generate_pdf_report(str(html_path), str(pdf_path))
        logger.info("PDF report generated: %s", pdf_path)
    except RuntimeError as exc:
        logger.warning("PDF report skipped: %s", exc)
    except Exception as exc:
        logger.error("Failed to generate PDF report: %s", exc)

    # Transform (no-op)
    _ = transform(df, config)

    logger.info("Pipeline completed successfully")
    return 0
