from pathlib import Path
import logging
from typing import Dict, Iterator, List, Tuple

import pandas as pd
from pydantic import ValidationError

from healthcli.clinical_rules_extended import run_clinical_rules
from healthcli.config_loader import load_config
from healthcli.data_loader import load_csv_data
from healthcli.fhir_validator import CodeableConcept, Coding, Observation, Patient, Quantity, Reference
from healthcli.logging_utils import setup_logger
from healthcli.memory_optimizer import MemoryOptimizationMetrics, PandasMemoryOptimizer
from healthcli.quality import fhir_validation_summary, missing_summary
from healthcli.quality_report import QualityReportGenerator


def ingest(data_path: str) -> Tuple[object, int]:
    df = load_csv_data(data_path)
    return df, len(df)


def iter_csv_chunks(data_path: str, chunk_size: int) -> Iterator[pd.DataFrame]:
    """Stream a CSV file in bounded-size chunks."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be greater than zero")
    path = Path(data_path)
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")
    yield from pd.read_csv(path, chunksize=chunk_size)


def validate_fhir_chunk(frame: pd.DataFrame) -> Dict[str, int]:
    """Validate FHIR resources mapped from common tabular fields."""
    result = {"patients_validated": 0, "patient_errors": 0, "observations_validated": 0, "observation_errors": 0}
    if "patient_nbr" in frame.columns:
        for row in frame.itertuples(index=True):
            try:
                Patient(id=str(getattr(row, "patient_nbr")), gender="unknown")
                result["patients_validated"] += 1
            except ValidationError:
                result["patient_errors"] += 1

    loinc_columns = {"max_glu_serum": "2345-7", "A1Cresult": "4548-4"}
    if "patient_nbr" in frame.columns:
        for column, loinc in loinc_columns.items():
            if column not in frame.columns:
                continue
            for row in frame.itertuples(index=True):
                value = getattr(row, column)
                if pd.isna(value):
                    continue
                try:
                    Observation(
                        id=f"obs-{row.Index}-{column}",
                        status="final",
                        code=CodeableConcept(
                            coding=[Coding(system="http://loinc.org", code=loinc)]
                        ),
                        subject=Reference(
                            reference=f"Patient/{getattr(row, 'patient_nbr')}"
                        ),
                        valueQuantity=Quantity(value=float(value), unit="mg/dL"),
                    )
                    result["observations_validated"] += 1
                except (TypeError, ValueError, ValidationError):
                    result["observation_errors"] += 1
    return result


def process_chunks(
    data_path: str,
    chunk_size: int,
    logger: logging.Logger,
) -> Tuple[pd.DataFrame, MemoryOptimizationMetrics, Dict[str, int]]:
    """Optimize and validate each chunk before materializing report input."""
    optimizer = PandasMemoryOptimizer(logger=logger)
    chunks: List[pd.DataFrame] = []
    before_bytes = after_bytes = numeric_columns = categorical_columns = 0
    fhir_totals = {"patients_validated": 0, "patient_errors": 0, "observations_validated": 0, "observation_errors": 0}

    for chunk_number, chunk in enumerate(iter_csv_chunks(data_path, chunk_size), start=1):
        optimized, metrics = optimizer.optimize(chunk)
        chunks.append(optimized)
        before_bytes += metrics.before_bytes
        after_bytes += metrics.after_bytes
        numeric_columns += metrics.numeric_columns
        categorical_columns += metrics.categorical_columns
        for key, value in validate_fhir_chunk(optimized).items():
            fhir_totals[key] += value
        logger.info("processed chunk=%d rows=%d", chunk_number, len(chunk))

    if not chunks:
        raise ValueError(f"Dataset is empty: {data_path}")
    metrics = MemoryOptimizationMetrics(before_bytes, after_bytes, numeric_columns, categorical_columns)
    return pd.concat(chunks, ignore_index=True), metrics, fhir_totals


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

    logger.info("Pipeline started: ingest -> optimize -> validate -> transform")

    chunk_size = int(config.get("pipeline", {}).get("chunk_size", 10000))
    df, memory_metrics, fhir_r4_summary = process_chunks(data_path, chunk_size, logger)
    rows = len(df)
    logger.info("Ingested %d rows from %s", rows, data_path)

    results = validate(df, config)
    results["fhir_r4_summary"] = fhir_r4_summary
    results["memory_metrics"] = memory_metrics

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save a simple CSV of missing summary
    ms = results.get("missing_summary")
    if isinstance(ms, pd.DataFrame):
        ms.to_csv(out_dir / "missing_summary.csv")
        logger.info("Missing summary written to %s", out_dir / "missing_summary.csv")

    # Generate HTML and PDF quality reports
    generator = QualityReportGenerator(logger=logger)
    html_path = out_dir / "quality_report.html"
    pdf_path = out_dir / "quality_report.pdf"

    missing_summary_for_report = {}
    if isinstance(ms, pd.DataFrame):
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
