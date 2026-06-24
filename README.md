# Clinical Data Quality Analysis

A rule-based validation pipeline for structured healthcare data.

This repository demonstrates a reproducible approach to detecting missing values, schema violations, invalid formats, and clinically unrealistic entries before downstream analytics.

## What it does

- Validates schema and required fields
- Checks value ranges and clinical plausibility
- Separates critical errors from non-critical issues
- Generates reproducible quality reports

## Usage

Run data quality analysis:

```bash
healthcli quality --data data/diabetic_data.csv --config config/config.yaml
```

Run the pipeline and write outputs:

```bash
healthcli pipeline --data data/diabetic_data.csv --config config/config.yaml --output output
```

The pipeline writes a missing data summary and logs progress to `logs/`.

## Highlights

- Rule-based validation for transparency and repeatability
- Modular layers for loading, validation, and reporting
- Pydantic models for structured type and plausibility checks
- Optional HTML/PDF report generation

## Tech stack

- Python 3.9+
- Pandas, NumPy
- Pydantic v2
- Jinja2
- WeasyPrint
- Matplotlib
- PyYAML

## Why this matters

This pattern is useful for clinical ETL, audit-ready data validation, and health analytics pipelines where early detection of data issues improves trust and downstream reliability.
