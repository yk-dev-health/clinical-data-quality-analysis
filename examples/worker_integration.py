"""Example: how an event-driven worker (e.g. healthcare-data-pipeline) invokes
this repository's clinical quality engine through the typed contract in
`healthcli.contracts`.

This script uses local, in-memory fakes for every piece of cloud
infrastructure a real worker would own -- Pub/Sub delivery, a Redis-backed
idempotency store, and BigQuery raw/validated/dead-letter tables. None of
those fakes are part of the quality engine's public surface; they exist only
so this example runs without any cloud credentials. Swapping a fake for the
real client (google-cloud-pubsub, redis-py, google-cloud-bigquery) is the
calling worker's job, not this repository's.

Run:
    python examples/worker_integration.py
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from healthcli.contracts import ProcessingRequest, ProcessingResult, RecordOutcome, process_request

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("worker_integration_example")


# --- Fakes standing in for infrastructure the worker owns, not this repo ---


class FakePubSubMessage:
    """Stands in for a delivered Pub/Sub message with ack/nack semantics."""

    def __init__(self, message_id: str, request: ProcessingRequest) -> None:
        self.message_id = message_id
        self.request = request
        self.acked = False
        self.nacked = False

    def ack(self) -> None:
        self.acked = True

    def nack(self) -> None:
        self.nacked = True


class FakeIdempotencyStore:
    """Stands in for a Redis SETNX-based idempotency key check."""

    def __init__(self) -> None:
        self._seen: set = set()

    def acquire(self, key: str) -> bool:
        """Return True if this is the first time `key` has been seen."""
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


@dataclass
class FakeBigQuerySink:
    """Stands in for separate raw/validated/dead-letter BigQuery tables."""

    validated_rows: List[Dict] = field(default_factory=list)
    dead_letter: List[Dict] = field(default_factory=list)

    def insert_validated(self, request_id: str, result: ProcessingResult) -> None:
        self.validated_rows.append({"request_id": request_id, "validated_count": result.validated_count})

    def insert_dead_letter(self, request_id: str, result: ProcessingResult) -> None:
        self.dead_letter.append(
            {
                "request_id": request_id,
                "rejected_count": result.rejected_count,
                "reasons": [r.error_type for r in result.rejected_records],
            }
        )


# --- The worker itself: this is the part a real repo would keep ---


class ClinicalValidationWorker:
    """Minimal worker loop showing where idempotency and quality validation fit.

    Mirrors the ordering required by the integration contract:
    1. Acquire idempotency (skip if already processed) -- before ack.
    2. Invoke the clinical quality engine via `process_request`.
    3. Map VALIDATED -> BigQuery validated table + ack.
       Map REJECTED   -> BigQuery dead-letter table + ack (permanent failure,
                          not a transport-level error, so it is *not* nacked).
    4. Any unexpected exception from the engine is a transient/infra failure
       and is nacked so Pub/Sub retries delivery -- it must not be quarantined.
    """

    def __init__(
        self,
        idempotency_store: FakeIdempotencyStore,
        sink: FakeBigQuerySink,
        schema_path: str,
    ) -> None:
        self.idempotency_store = idempotency_store
        self.sink = sink
        self.schema_path = schema_path

    def handle_message(self, message: FakePubSubMessage) -> Optional[ProcessingResult]:
        if not self.idempotency_store.acquire(message.message_id):
            logger.info("Skipping duplicate delivery: message_id=%s", message.message_id)
            message.ack()
            return None

        try:
            result = process_request(message.request, schema_path=self.schema_path, logger=logger)
        except Exception:
            logger.exception("Transient failure processing message_id=%s; requesting redelivery", message.message_id)
            message.nack()
            raise

        if result.outcome == RecordOutcome.VALIDATED:
            self.sink.insert_validated(message.request.request_id, result)
        else:
            self.sink.insert_dead_letter(message.request.request_id, result)

        # Idempotency commit already happened (acquire()); ack now that the
        # outcome -- validated or permanently rejected -- has been persisted.
        message.ack()
        return result


def main() -> None:
    schema_path = str(__file__).replace("worker_integration.py", "../config/schema.yaml")

    worker = ClinicalValidationWorker(
        idempotency_store=FakeIdempotencyStore(),
        sink=FakeBigQuerySink(),
        schema_path=schema_path,
    )

    good_request = ProcessingRequest(
        request_id="req-001",
        records=[
            {"patient_nbr": "1", "gender": "Male", "age": 45},
            {"patient_nbr": "2", "gender": "Female", "age": 60},
        ],
    )
    bad_request = ProcessingRequest(
        request_id="req-002",
        records=[{"patient_nbr": "3", "gender": "Unknown", "age": "not-a-number"}],
    )

    message1 = FakePubSubMessage("msg-1", good_request)
    message2 = FakePubSubMessage("msg-2", bad_request)
    duplicate_delivery = FakePubSubMessage("msg-1", good_request)  # same message_id redelivered

    worker.handle_message(message1)
    worker.handle_message(message2)
    worker.handle_message(duplicate_delivery)

    logger.info("acked=%s nacked=%s (message1)", message1.acked, message1.nacked)
    logger.info("acked=%s nacked=%s (message2)", message2.acked, message2.nacked)
    logger.info("acked=%s (duplicate, should be True without reprocessing)", duplicate_delivery.acked)
    logger.info("validated rows in BigQuery sink: %s", worker.sink.validated_rows)
    logger.info("dead-letter rows in BigQuery sink: %s", worker.sink.dead_letter)


if __name__ == "__main__":
    main()
