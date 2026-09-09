"""Typed integration contract for external worker callers (e.g. healthcare-data-pipeline).

The quality engine in this repository is designed to be invoked as a library
from an event-driven worker that owns its own delivery semantics (Pub/Sub
ack/nack, Redis idempotency keys, retries, dead-lettering). This module is
the stable boundary between the two: a typed request in, a typed result out,
and a `RecordSink` Protocol for where validated/rejected output goes. Nothing
here imports Pub/Sub, Redis, or BigQuery clients -- those are the calling
worker's responsibility, not this engine's.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from healthcli.schema_validator import DatasetSchema, load_schema, validate_schema_per_row
from healthcli.sinks import RecordSink  # re-exported: the worker-facing sink contract

CONTRACT_VERSION = "1.0"


class RecordOutcome(str, Enum):
    """How the worker should treat one processed record."""

    VALIDATED = "validated"
    REJECTED = "rejected"


class ProcessingRequest(BaseModel):
    """One unit of work handed to the clinical quality engine by a worker.

    `records` is a list of plain field dicts (already deserialized from
    whatever transport the worker uses -- Pub/Sub message bodies, a batch
    file, etc.). The engine does not care how the worker obtained them or
    how it will acknowledge them; it only validates and classifies.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contract_version: str = Field(default=CONTRACT_VERSION)
    request_id: str = Field(min_length=1, description="Idempotency/correlation key set by the calling worker")
    schema_version: Optional[str] = Field(
        default=None, description="Expected dataset schema version; None uses the engine's configured default"
    )
    records: List[Dict[str, Any]] = Field(min_length=1)


class RejectedRecord(BaseModel):
    """One record that failed validation, with a reason but no raw payload.

    Row values are intentionally never included: the worker's quarantine
    path may forward this object to logs or a dead-letter store, and a
    payload field here would defeat the "PHI-minimized" requirement.
    """

    model_config = ConfigDict(extra="forbid")

    record_index: int
    reason: str
    error_type: str


class ProcessingResult(BaseModel):
    """Outcome of validating one `ProcessingRequest`.

    `outcome` gives the worker a single field to branch on: VALIDATED means
    every record in the request passed and can be committed/acked; REJECTED
    means at least one record failed and the worker should route the
    request (or just its rejected records, depending on worker granularity)
    to quarantine while still acking the request itself, per the "permanent
    validation failures are quarantined and acknowledged" contract.
    """

    model_config = ConfigDict(extra="forbid")

    contract_version: str = Field(default=CONTRACT_VERSION)
    request_id: str
    outcome: RecordOutcome
    schema_version: str
    total_records: int
    validated_count: int
    rejected_count: int
    rejected_records: List[RejectedRecord] = Field(default_factory=list)
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def build(
        cls,
        request_id: str,
        schema_version: str,
        total_records: int,
        rejected_records: Optional[List[RejectedRecord]] = None,
    ) -> "ProcessingResult":
        rejected_records = rejected_records or []
        rejected_count = len(rejected_records)
        validated_count = total_records - rejected_count
        return cls(
            request_id=request_id,
            outcome=RecordOutcome.REJECTED if rejected_count else RecordOutcome.VALIDATED,
            schema_version=schema_version,
            total_records=total_records,
            validated_count=validated_count,
            rejected_count=rejected_count,
            rejected_records=rejected_records,
        )


def process_request(
    request: ProcessingRequest,
    schema_path: str = "config/schema.yaml",
    logger: Optional[logging.Logger] = None,
) -> ProcessingResult:
    """Validate one `ProcessingRequest` and return a typed `ProcessingResult`.

    This is the single call a worker needs after acquiring idempotency for a
    message: pass in the deserialized records, get back which ones validated
    and which were rejected (with a reason and error type, never the
    original field values). The worker maps `outcome` to its own ack/nack
    and quarantine logic; this function has no opinion about Pub/Sub, Redis,
    or BigQuery.
    """
    logger = logger or logging.getLogger("healthcli.contracts")
    schema: DatasetSchema = load_schema(schema_path)

    df = pd.DataFrame.from_records(request.records)
    row_rejections = validate_schema_per_row(df, schema)

    rejections_by_row: Dict[int, List[str]] = defaultdict(list)
    for rejection in row_rejections:
        rejections_by_row[rejection.row_index].append(f"{rejection.column}:{rejection.error_type}")

    rejected_records = [
        RejectedRecord(
            record_index=row_index,
            reason="; ".join(reasons),
            error_type=reasons[0].split(":", 1)[1],
        )
        for row_index, reasons in sorted(rejections_by_row.items())
    ]

    result = ProcessingResult.build(
        request_id=request.request_id,
        schema_version=schema.version,
        total_records=len(request.records),
        rejected_records=rejected_records,
    )
    logger.info(
        "Processed request request_id=%s outcome=%s validated=%d rejected=%d",
        result.request_id,
        result.outcome.value,
        result.validated_count,
        result.rejected_count,
    )
    return result


__all__ = [
    "CONTRACT_VERSION",
    "RecordOutcome",
    "ProcessingRequest",
    "RejectedRecord",
    "ProcessingResult",
    "RecordSink",
    "process_request",
]
