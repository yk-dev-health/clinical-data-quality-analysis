from pathlib import Path
import logging
from typing import Dict, Iterator, List, Optional, Tuple

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
from healthcli.schema_validator import (
    DatasetSchema,
    FieldErrorCount,
    SchemaValidationResult,
    load_schema,
    validate_schema,
)
from healthcli.sinks import DataFrameSink, ParquetSink, RecordSink, RejectedRecordSink
from healthcli.streaming_metrics import StreamingMetricAggregator
from healthcli.idempotency import (
    PIPELINE_VERSION,
    IdempotencyChecker,
    ProcessingManifest,
    RunIdentity,
    compute_dataset_hash,
)


class SchemaValidationFailed(ValueError):
    """Raised when a dataset fails schema validation before rules execute."""

    def __init__(self, result: SchemaValidationResult) -> None:
        self.result = result
        super().__init__(
            f"Dataset failed schema validation (schema_version={result.schema_version}, "
            f"missing_columns={len(result.missing_columns)}, field_errors={result.total_field_errors})"
        )


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


def process_chunks_streaming(
    data_path: str,
    chunk_size: int,
    logger: logging.Logger,
    sink: RecordSink,
) -> Tuple[MemoryOptimizationMetrics, Dict[str, int], StreamingMetricAggregator, int]:
    """Optimize and validate each chunk, writing it to `sink` without concatenation.

    Unlike `process_chunks`, this never holds more than one chunk in memory
    at a time (beyond whatever the sink itself buffers): every optimized
    chunk is written to `sink` immediately and dropped. Missingness metrics
    are accumulated incrementally via `StreamingMetricAggregator`, so a full
    materialized DataFrame is never required for reporting.
    """
    optimizer = PandasMemoryOptimizer(logger=logger)
    aggregator = StreamingMetricAggregator()
    before_bytes = after_bytes = numeric_columns = categorical_columns = 0
    fhir_totals = {"patients_validated": 0, "patient_errors": 0, "observations_validated": 0, "observation_errors": 0}
    chunk_count = 0

    for chunk_number, chunk in enumerate(iter_csv_chunks(data_path, chunk_size), start=1):
        optimized, metrics = optimizer.optimize(chunk)
        sink.write(optimized)
        aggregator.add_chunk(optimized)
        before_bytes += metrics.before_bytes
        after_bytes += metrics.after_bytes
        numeric_columns += metrics.numeric_columns
        categorical_columns += metrics.categorical_columns
        for key, value in validate_fhir_chunk(optimized).items():
            fhir_totals[key] += value
        logger.info("processed chunk=%d rows=%d", chunk_number, len(chunk))
        chunk_count = chunk_number

    sink.finalize()
    if chunk_count == 0:
        raise ValueError(f"Dataset is empty: {data_path}")
    metrics = MemoryOptimizationMetrics(before_bytes, after_bytes, numeric_columns, categorical_columns)
    return metrics, fhir_totals, aggregator, aggregator.total_rows


def process_chunks(
    data_path: str,
    chunk_size: int,
    logger: logging.Logger,
) -> Tuple[pd.DataFrame, MemoryOptimizationMetrics, Dict[str, int]]:
    """Optimize and validate each chunk, materializing a single report DataFrame.

    Kept for callers (and the HTML/PDF report) that need row-level access to
    the full dataset. Internally this is now just `process_chunks_streaming`
    with a `DataFrameSink` -- the materialized path is one sink choice among
    several, not a separate code path.
    """
    sink = DataFrameSink()
    metrics, fhir_totals, _aggregator, _rows = process_chunks_streaming(data_path, chunk_size, logger, sink)
    return sink.result, metrics, fhir_totals


def run_schema_validation(df: pd.DataFrame, config: dict, logger: logging.Logger) -> SchemaValidationResult:
    """Validate dataset shape/type/vocabulary before clinical rules execute.

    Raises `SchemaValidationFailed` when `schema.fail_on_invalid` is true
    (the default) and the dataset does not conform. Only counts are logged;
    rejected cell values are never included.
    """
    schema_config = config.get("schema", {})
    schema_path = schema_config.get("path", "config/schema.yaml")
    fail_on_invalid = bool(schema_config.get("fail_on_invalid", True))

    schema: DatasetSchema = load_schema(schema_path)
    result = validate_schema(df, schema)

    if result.is_valid:
        logger.info("Schema validation passed: schema_version=%s rows=%d", result.schema_version, result.total_rows)
    else:
        logger.error(
            "Schema validation failed: schema_version=%s missing_columns=%d field_errors=%d",
            result.schema_version,
            len(result.missing_columns),
            result.total_field_errors,
        )
        if fail_on_invalid:
            raise SchemaValidationFailed(result)

    return result


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


def run_pipeline_streaming(data_path: str, config_path: str, output_dir: str) -> int:
    """Run the pipeline in streaming mode: chunks go straight to a Parquet sink.

    No `pd.concat` and no full in-memory DataFrame at any point. Schema
    validation and missingness metrics are computed incrementally per chunk;
    rejected rows are written to a JSON-lines sidecar with counts and reasons
    only. Trades the row-level HTML/PDF report (which needs the whole
    dataset for its chart and per-rule affected-row listing) for the ability
    to process datasets far larger than available memory.
    """
    config = load_config(config_path)
    logger = setup_logger(
        "healthcli.pipeline",
        level=config.get("logging", {}).get("level", "INFO"),
        log_dir=config.get("logging", {}).get("log_dir", "logs"),
    )
    logger.info("Streaming pipeline started: ingest -> optimize -> validate (no materialization)")

    schema_config = config.get("schema", {})
    schema_path = schema_config.get("path", "config/schema.yaml")
    fail_on_invalid = bool(schema_config.get("fail_on_invalid", True))
    schema = load_schema(schema_path)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_sink = ParquetSink(str(out_dir / "validated_records.parquet"))
    rejected_sink = RejectedRecordSink(str(out_dir / "rejected_records.jsonl"))

    idempotency_config = config.get("idempotency", {})
    idempotency_enabled = bool(idempotency_config.get("enabled", False))
    idempotency_checker: Optional[IdempotencyChecker] = None
    if idempotency_enabled:
        dataset_hash = compute_dataset_hash(data_path)
        run_identity = RunIdentity(
            dataset_hash=dataset_hash, schema_version=schema.version, pipeline_version=PIPELINE_VERSION
        )
        manifest = ProcessingManifest(idempotency_config.get("manifest_path", "output/processing_manifest.json"))
        hash_columns = idempotency_config.get("hash_columns") or schema.column_names()
        idempotency_checker = IdempotencyChecker(manifest, run_identity, hash_columns)
        logger.info(
            "Idempotency enabled: run_id=%s dataset_hash=%s...", run_identity.run_id, dataset_hash[:12]
        )

    chunk_size = int(config.get("pipeline", {}).get("chunk_size", 10000))
    optimizer = PandasMemoryOptimizer(logger=logger)
    aggregator = StreamingMetricAggregator()
    before_bytes = after_bytes = numeric_columns = categorical_columns = 0
    schema_missing_columns_seen: set = set()
    schema_field_error_totals: Dict[str, int] = {}
    total_rows = 0
    chunk_count = 0

    for chunk_number, chunk in enumerate(iter_csv_chunks(data_path, chunk_size), start=1):
        optimized, chunk_metrics = optimizer.optimize(chunk)
        before_bytes += chunk_metrics.before_bytes
        after_bytes += chunk_metrics.after_bytes
        numeric_columns += chunk_metrics.numeric_columns
        categorical_columns += chunk_metrics.categorical_columns

        chunk_schema_result = validate_schema(optimized, schema)
        schema_missing_columns_seen.update(chunk_schema_result.missing_columns)
        for error in chunk_schema_result.field_errors:
            key = f"{error.column}:{error.error_type}"
            schema_field_error_totals[key] = schema_field_error_totals.get(key, 0) + error.row_count

        if idempotency_checker is not None:
            optimized = idempotency_checker.process_chunk(optimized)

        aggregator.add_chunk(optimized)
        parquet_sink.write(optimized)
        total_rows += len(optimized)
        chunk_count = chunk_number
        logger.info("processed chunk=%d rows=%d (streaming)", chunk_number, len(optimized))

    parquet_sink.finalize()
    rejected_sink.finalize()
    if idempotency_checker is not None:
        idempotency_checker.commit()
        logger.info(
            "Idempotency summary: total=%d new=%d duplicate=%d",
            idempotency_checker.metrics.total_rows,
            idempotency_checker.metrics.new_rows,
            idempotency_checker.metrics.duplicate_rows,
        )

    if chunk_count == 0:
        raise ValueError(f"Dataset is empty: {data_path}")

    is_valid = not schema_missing_columns_seen and not schema_field_error_totals
    if not is_valid:
        logger.error(
            "Schema validation failed (streaming): schema_version=%s missing_columns=%d field_error_kinds=%d",
            schema.version,
            len(schema_missing_columns_seen),
            len(schema_field_error_totals),
        )
        if fail_on_invalid:
            result = SchemaValidationResult(
                schema_version=schema.version,
                is_valid=False,
                total_rows=total_rows,
                missing_columns=sorted(schema_missing_columns_seen),
                field_errors=[
                    FieldErrorCount(column=key.split(":", 1)[0], error_type=key.split(":", 1)[1], row_count=count)
                    for key, count in schema_field_error_totals.items()
                ],
            )
            raise SchemaValidationFailed(result)
    else:
        logger.info("Schema validation passed (streaming): schema_version=%s rows=%d", schema.version, total_rows)

    memory_metrics = MemoryOptimizationMetrics(before_bytes, after_bytes, numeric_columns, categorical_columns)
    missing_df = aggregator.missing_summary()
    missing_df.to_csv(out_dir / "missing_summary.csv")

    logger.info(
        "Streaming pipeline completed: rows=%d chunks=%d reduction_ratio=%.3f rejected=%d",
        total_rows,
        chunk_count,
        memory_metrics.reduction_ratio,
        rejected_sink.rejected_count,
    )
    logger.info(
        "Validated records written to %s, rejected metadata written to %s",
        out_dir / "validated_records.parquet",
        out_dir / "rejected_records.jsonl",
    )
    return 0


def run_idempotency_check(
    df: pd.DataFrame,
    data_path: str,
    schema_version: str,
    config: dict,
    logger: logging.Logger,
) -> Optional[Tuple[pd.DataFrame, Dict[str, int]]]:
    """Filter out rows already recorded as processed under the current run identity.

    Returns `None` when idempotency is disabled in config, otherwise the
    de-duplicated frame and a metrics dict (never containing raw identifiers).
    """
    idempotency_config = config.get("idempotency", {})
    if not bool(idempotency_config.get("enabled", False)):
        return None

    dataset_hash = compute_dataset_hash(data_path)
    run_identity = RunIdentity(
        dataset_hash=dataset_hash, schema_version=schema_version, pipeline_version=PIPELINE_VERSION
    )
    manifest = ProcessingManifest(idempotency_config.get("manifest_path", "output/processing_manifest.json"))
    hash_columns = idempotency_config.get("hash_columns") or list(df.columns)
    checker = IdempotencyChecker(manifest, run_identity, hash_columns)

    logger.info("Idempotency enabled: run_id=%s dataset_hash=%s...", run_identity.run_id, dataset_hash[:12])
    new_rows_df = checker.process_chunk(df)
    checker.commit()
    logger.info(
        "Idempotency summary: total=%d new=%d duplicate=%d",
        checker.metrics.total_rows,
        checker.metrics.new_rows,
        checker.metrics.duplicate_rows,
    )
    return new_rows_df, checker.metrics.as_dict()


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

    schema_result = run_schema_validation(df, config, logger)

    idempotency_outcome = run_idempotency_check(df, data_path, schema_result.schema_version, config, logger)
    if idempotency_outcome is not None:
        df, idempotency_metrics = idempotency_outcome
    else:
        idempotency_metrics = None

    results = validate(df, config)
    results["schema_validation"] = schema_result
    results["fhir_r4_summary"] = fhir_r4_summary
    results["memory_metrics"] = memory_metrics
    if idempotency_metrics is not None:
        results["idempotency"] = idempotency_metrics

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
