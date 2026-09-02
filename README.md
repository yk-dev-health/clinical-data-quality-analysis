# Clinical Data Quality Analysis

An auditable Python pipeline for finding structural, clinical, and interoperability defects before EHR or clinical-trial data reaches analytics, research, or downstream services.

## Executive summary

Healthcare data can be syntactically valid and clinically unusable at the same time. This project combines deterministic clinical rules, a strict FHIR R4-inspired Pydantic v2 validation boundary, missingness analysis, and reproducible HTML/PDF reporting in one CLI workflow.

## System architecture

```mermaid

flowchart LR
	A[CSV / EHR extract] --> B[Chunked reader]
	B --> C[Memory optimizer]
	C --> D[Schema and FHIR R4 validation]
	D --> E[Clinical rule engine]
	E --> F[Quality metrics]
	F --> G[HTML / PDF report]
	D --> H[Audit-safe structured logs]
	C --> I[Memory metrics]
```

## Key engineering accomplishments

- **Measured memory optimization:** numeric downcasting and safe category conversion are measured per pass. The sample dataset achieved a 14.1% reduction; results are schema- and data-dependent and emitted as `before_bytes`, `after_bytes`, and `reduction_ratio`.
- **FHIR R4-inspired validation boundary:** strict `Patient`, `Observation`, `Quantity`, `Reference`, and `CodeableConcept` models reject unknown fields, invalid identifiers, future birth dates, and malformed LOINC/SNOMED CT code shapes. This is not a complete FHIR conformance validator.
- **Chunked ingestion:** `iter_csv_chunks` reads large CSV inputs incrementally. The current reporting path materializes optimized chunks into a final DataFrame, so it is not yet a fully streaming multi-GB architecture.
- **Non-mutating validation:** validators consume mapped values without mutating the input frame. The optimizer intentionally returns a transformed copy, preserving a deterministic comparison boundary.
- **Clinical rules:** missingness thresholds, demographic coherence, vital-sign plausibility, and temporal anomalies remain independently testable.

## Benchmark and performance data

These are representative engineering targets, not universal guarantees. Run the optimizer against the target schema and record its emitted metrics before making capacity claims.

| Workload | Execution mode | Expected engineering outcome |
| --- | --- | --- |
| Sample mixed CSV | One optimized pass | 14.1% measured memory reduction |
| 100k-row mixed CSV | One optimized pass | Dataset-specific reduction metrics |
| Multi-GB CSV | `chunksize` configured in pipeline | Incremental reads; final report still materializes data |
| Low-cardinality strings | Pandas `category` | Dictionary encoding where it reduces deep memory |
| FHIR resource mapping | Pydantic v2 | Deterministic accepted/rejected resource counts |

## Quickstart

```bash
python -m pip install -e ".[dev]"
healthcli quality --data data/diabetic_data.csv --config config/config.yaml
healthcli pipeline --data data/diabetic_data.csv --config config/config.yaml --output output
pytest -q
mypy src/healthcli
```

To tune bounded ingestion, add the following to `config/config.yaml`:

```yaml
pipeline:
	chunk_size: 10000
```

Docker execution mounts the input and output directories:

```bash
docker build -t clinical-data-quality-analysis .
docker run --rm -v "${PWD}/data:/data" -v "${PWD}/output:/output" clinical-data-quality-analysis pipeline --data /data/diabetic_data.csv --config /app/config/config.yaml --output /output
```

The pipeline produces `missing_summary.csv`, `quality_report.html`, and a PDF when WeasyPrint system dependencies are available. Logs belong in a controlled environment and must not contain direct identifiers.

## Scope and planned production integrations

This repository currently implements a local, batch-oriented CSV pipeline. Pub/Sub ingestion, Redis-backed idempotency, and BigQuery storage are **not implemented** and are not represented as completed capabilities. A production cloud deployment could evolve the current boundaries as follows:

```mermaid
flowchart LR
	A[Pub/Sub event] --> B[Validation worker]
	B --> C[Redis idempotency key]
	B --> D[BigQuery raw table]
	B --> E[BigQuery validated table]
	B --> F[Dead-letter / rejected records]
```

The next engineering steps would be defining a versioned message schema, using an `event_id` or content hash for idempotent retries, writing raw and validated records to separate BigQuery tables, and adding emulator-based integration tests.

## Project layout

```text
src/healthcli/
	data_loader.py             # Input checks and simple ingestion
	memory_optimizer.py        # Downcasting, categories, and memory metrics
	fhir_validator.py          # Strict FHIR R4 resource boundary
	clinical_rules_extended.py # Domain-specific data quality rules
	quality.py                 # Aggregation and reporting inputs
	pipeline.py                # Chunk orchestration and output contract
	quality_report.py          # Jinja2 and WeasyPrint reports
tests/                       # Unit and integration tests
```

## Technology and engineering practice

Python 3.9+, Pandas, NumPy, Pydantic v2, Jinja2, WeasyPrint, PyYAML, and `structlog` are used with a typed, testable module boundary. Development dependencies include pytest, coverage tooling, pandas stubs, and mypy. CI runs tests with coverage and mypy; formatting, security scanning, and cloud emulator integration tests remain recommended additions.

## Interview defense guide

**How do you handle multi-GB datasets with Pandas?**  I use `read_csv(..., chunksize=...)`, optimize each chunk immediately, and accumulate bounded metrics rather than retaining raw chunks. For reports that require row-level context, I use a separate materialized sink; for production-scale jobs I switch that sink to partitioned Parquet or aggregate-only output. The chunk size is configuration, so it can be tuned against container memory and throughput.

**Why Pydantic over Cerberus or Great Expectations?**  Pydantic gives this Python service typed resource contracts, composable nested FHIR objects, clear `ValidationError` paths, and a direct API boundary. Great Expectations remains valuable for dataset-level expectations, so I would use it at the batch quality gate rather than force either tool to replace the other. Terminology existence is intentionally delegated to a versioned ValueSet or terminology server; the repository code only provides a deterministic format stub.

**How do you ensure GDPR compliance with local logs?**  Logs are treated as operational data: identifiers are hashed or omitted before logging, payloads and full validation errors are not emitted by default, retention and access are controlled, and the output directory is excluded from source control. I would add a DPIA, data-flow record, encryption at rest, least-privilege service accounts, and automated log-redaction tests before processing real UK patient data. This demo uses synthetic/public-style data and is not a clinical system.
