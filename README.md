# Clinical Data Quality Analysis

A reproducible, rule-based data validation pipeline for structured healthcare data.

This project demonstrates how to design deterministic validation workflows that detect missing values, schema violations, inconsistent formats, and clinically unrealistic values before downstream analytics or machine learning.

## Overview

Structured healthcare data is often affected by:

- Missing values
- Inconsistent formats
- Invalid data types
- Out-of-range values
- Schema mismatches

If these issues are not identified early, downstream systems become unreliable and potentially misleading.

This project focuses on designing a maintainable validation architecture that makes data quality measurable, reproducible, and operationally manageable.

## Problem Statement

The core challenge is ensuring that tabular healthcare data is reliable before it is used for reporting, analytics, or machine learning.

The validation layer must:

- Enforce schema expectations
- Detect invalid and unrealistic values
- Quantify data quality issues
- Separate critical and non-critical errors
- Produce reproducible outputs


## Architecture

```mermaid
flowchart LR
    A[Input CSV Files]
    B[Data Loading]
    C[Schema Validation]
    D[Rule-Based Quality Checks]
    E[Error Classification]
    F[Quality Report]
    G[Validated Dataset]

    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    E --> G
````


## Validation Strategy

### Schema Validation

Checks required columns, data types, and structural consistency.

### Rule-Based Quality Checks

Detects missing values, invalid ranges, and clinically unrealistic values.

### Error Classification

**Critical errors**

* Prevent reliable processing.
* Stop execution immediately.

**Non-critical errors**

* Logged and isolated.
* Processing continues.

### Reproducibility

The same input always produces the same validation outcome.


## Design Decisions

### Deterministic Rules Over ML

Explicit rules were chosen to maximize interpretability and reproducibility.

### Separation of Concerns

Data loading, validation, and reporting are implemented as distinct layers.

### Tolerant Input Handling

Common formatting variations are normalized before validation.

### Re-runnable Processing

The pipeline can be safely executed multiple times.


## Trade-Offs

| Decision               | Benefit                      | Cost                           |
| ---------------------- | ---------------------------- | ------------------------------ |
| Rule-based validation  | Transparent and reproducible | Manual rule definition         |
| Modular design         | Easier maintenance           | More initial structure         |
| Tolerant preprocessing | Better operability           | Additional normalization logic |


## Skills Demonstrated

* Data Validation Architecture
* Healthcare Data Quality Management
* Schema Design
* Batch Data Processing
* Error Handling Design
* Reproducible Data Pipelines
* Python Refactoring

## Usage

### Quality analysis

Run the rule-based quality analysis for a clinical dataset:

```bash
healthcli quality --data data/diabetic_data.csv --config config/config.yaml
```

### Pipeline execution

Run the reproducible ingest/validate/transform pipeline and write outputs:

```bash
healthcli pipeline --data data/diabetic_data.csv --config config/config.yaml --output output
```

The pipeline writes `missing_summary.csv` to the configured output directory and logs progress to the `logs/` folder.


## Tech Stack

* Python
* Pandas
* openpyxl


## Real-World Relevance

This design pattern is applicable to:

* Clinical data ingestion pipelines
* Healthcare ETL systems
* Data quality control before analytics
* Regulatory and audit-focused environments

## Interview Summary

I designed a reproducible, rule-based validation pipeline that ensures structured healthcare data is reliable before downstream processing.

## One-Line Summary

Designed a deterministic data quality pipeline for structured healthcare data, with a focus on reproducibility, maintainability, and operational reliability.
