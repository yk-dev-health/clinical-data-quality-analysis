"""Small, strict FHIR R4 resource validation boundary.

This module intentionally validates resource shape and terminology format. A
production deployment should replace the terminology stubs with an approved
FHIR terminology server or versioned local ValueSet.
"""

import re
from datetime import date, datetime
from typing import Any, ClassVar, Dict, Literal, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

FHIR_ID = r"^[A-Za-z0-9\-\.]{1,64}$"
LOINC_PATTERN = re.compile(r"^\d{1,5}-\d$")
SNOMED_PATTERN = re.compile(r"^\d{6,18}$")


def _has_valid_loinc_check_digit(value: str) -> bool:
    """Validate the Modulus 10 check digit used by LOINC identifiers."""
    if not LOINC_PATTERN.fullmatch(value):
        return False
    digits, check_digit = value.split("-")
    total = 0
    for position, digit in enumerate(reversed(digits), start=1):
        product = int(digit) * (2 if position % 2 else 1)
        total += sum(int(part) for part in str(product))
    return (10 - (total % 10)) % 10 == int(check_digit)


class FHIRResource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Identifier(FHIRResource):
    value: str = Field(min_length=1, max_length=128)


class Coding(FHIRResource):
    system: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=1, max_length=64)
    display: Optional[str] = Field(default=None, max_length=255)

    @field_validator("code")
    @classmethod
    def validate_terminology_code(cls, value: str, info) -> str:
        system = info.data.get("system", "")
        if system == "http://loinc.org" and not _has_valid_loinc_check_digit(value):
            raise ValueError("LOINC code must have a valid Modulus 10 check digit")
        if system == "http://snomed.info/sct" and not SNOMED_PATTERN.fullmatch(value):
            raise ValueError("SNOMED CT code must contain 6 to 18 digits")
        return value


class CodeableConcept(FHIRResource):
    coding: list[Coding] = Field(min_length=1)


class Reference(FHIRResource):
    reference: str = Field(pattern=r"^Patient/[A-Za-z0-9\-.]{1,64}$")


class Quantity(FHIRResource):
    value: float = Field(strict=True, ge=-1_000_000_000, le=1_000_000_000)
    unit: str = Field(min_length=1, max_length=64)
    code: Optional[Coding] = None


class Patient(FHIRResource):
    resourceType: Literal["Patient"] = "Patient"
    id: str = Field(pattern=FHIR_ID)
    identifier: list[Identifier] = Field(default_factory=list)
    gender: Literal["male", "female", "other", "unknown"] = "unknown"
    birthDate: Optional[date] = None

    @field_validator("birthDate")
    @classmethod
    def birth_date_not_in_future(cls, value: Optional[date]) -> Optional[date]:
        if value and value > date.today():
            raise ValueError("birthDate cannot be in the future")
        return value


class Observation(FHIRResource):
    resourceType: Literal["Observation"] = "Observation"
    id: str = Field(pattern=FHIR_ID)
    status: Literal["registered", "preliminary", "final", "amended", "cancelled", "entered-in-error", "unknown"]
    code: CodeableConcept
    subject: Reference
    valueQuantity: Optional[Quantity] = None
    effectiveDateTime: Optional[datetime] = None


class VitalSigns(Observation):
    """Observation subtype enforcing physiologically plausible vital-sign ranges.

    Range checks are keyed by the observation's LOINC code, so callers must
    map the source column to the matching code (see `VITAL_SIGN_LOINC_CODES`).
    """

    VITAL_RANGES: ClassVar[dict[str, tuple[float, float]]] = {
        "8480-6": (50, 250),  # Systolic blood pressure (mmHg)
        "8867-4": (30, 200),  # Heart rate (bpm)
        "8310-5": (35, 42),  # Body temperature (C)
        "59408-5": (50, 100),  # Oxygen saturation (%)
    }

    @field_validator("valueQuantity")
    @classmethod
    def validate_vital_range(cls, value: Optional[Quantity], info) -> Optional[Quantity]:
        if value is None:
            return value

        code_obj: Optional[CodeableConcept] = info.data.get("code")
        loinc_code = code_obj.coding[0].code if code_obj and code_obj.coding else None
        bounds = cls.VITAL_RANGES.get(loinc_code) if loinc_code else None
        if bounds is None:
            return value

        low, high = bounds
        if value.value < low or value.value > high:
            raise ValueError(f"Value {value.value} {value.unit} outside plausible range [{low}, {high}]")
        return value


VITAL_SIGN_LOINC_CODES = {
    "systolic_bp": "8480-6",
    "heart_rate": "8867-4",
    "temperature": "8310-5",
    "spo2": "59408-5",
}


LAB_LOINC_CODES = {
    "max_glu_serum": "2345-7",
    "A1Cresult": "4548-4",
}


def _describe_validation_error(resource: str, row_index: Any, exc: ValidationError) -> str:
    """Summarize a Pydantic ValidationError by field and error type only.

    `str(exc)` and `exc.errors()` both embed the rejected value by default
    (Pydantic's `input_value`), which would leak raw field data -- including
    patient identifiers -- into logs and the HTML report. This keeps only
    the row position, the offending field path, and the error category.
    """
    field_errors = exc.errors(include_url=False, include_input=False, include_context=False)
    reasons = ", ".join(f"{'.'.join(str(p) for p in e['loc']) or resource}:{e['type']}" for e in field_errors)
    return f"{resource} row {row_index}: {reasons}"


def _normalize_gender(value: Any) -> Literal["male", "female", "other", "unknown"]:
    if pd.isna(value):
        return "unknown"
    gender = str(value).strip().lower()
    if gender == "male":
        return "male"
    if gender == "female":
        return "female"
    if gender == "other":
        return "other"
    return "unknown"


def validate_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    """Validate a tabular dataset's patient/lab/vital-sign columns as FHIR resources.

    This is the single validation path shared by the materialized and
    streaming pipeline modes, and by the standalone `quality` report: both
    map the same source columns to the same strict models, so results do
    not depend on which execution mode produced them.
    """
    summary: Dict[str, Any] = {
        "patients_validated": 0,
        "patient_errors": 0,
        "observations_validated": 0,
        "observation_errors": 0,
        "errors": [],
        "error_details": [],
    }

    if "patient_nbr" in df.columns:
        for idx, row in df.iterrows():
            birth_date = row["birthDate"] if "birthDate" in df.columns and pd.notna(row.get("birthDate")) else None
            try:
                Patient(
                    id=str(row["patient_nbr"]),
                    gender=_normalize_gender(row.get("gender", "unknown")),
                    birthDate=birth_date,
                )
                summary["patients_validated"] += 1
            except ValidationError as exc:
                summary["patient_errors"] += 1
                message = _describe_validation_error("Patient", idx, exc)
                summary["errors"].append(message)
                summary["error_details"].append((idx, message))

        for column, loinc in LAB_LOINC_CODES.items():
            if column not in df.columns:
                continue
            for idx, row in df.iterrows():
                if pd.isna(row[column]):
                    continue
                try:
                    value = float(row[column])
                except (TypeError, ValueError):
                    summary["observation_errors"] += 1
                    message = f"Observation row {idx} column {column}: non-numeric value"
                    summary["errors"].append(message)
                    summary["error_details"].append((idx, message))
                    continue
                try:
                    Observation(
                        id=f"obs-{idx}-{column}".replace("_", "-"),
                        status="final",
                        code=CodeableConcept(coding=[Coding(system="http://loinc.org", code=loinc)]),
                        subject=Reference(reference=f"Patient/{row['patient_nbr']}"),
                        valueQuantity=Quantity(value=value, unit="mg/dL"),
                    )
                    summary["observations_validated"] += 1
                except ValidationError as exc:
                    summary["observation_errors"] += 1
                    message = _describe_validation_error(f"Observation ({column})", idx, exc)
                    summary["errors"].append(message)
                    summary["error_details"].append((idx, message))

        for column, loinc in VITAL_SIGN_LOINC_CODES.items():
            if column not in df.columns:
                continue
            unit = {"systolic_bp": "mmHg", "heart_rate": "bpm", "temperature": "C", "spo2": "%"}[column]
            for idx, row in df.iterrows():
                if pd.isna(row[column]):
                    continue
                try:
                    value = float(row[column])
                except (TypeError, ValueError):
                    summary["observation_errors"] += 1
                    message = f"Vital sign row {idx} column {column}: non-numeric value"
                    summary["errors"].append(message)
                    summary["error_details"].append((idx, message))
                    continue
                try:
                    VitalSigns(
                        id=f"vital-{idx}-{column}".replace("_", "-"),
                        status="final",
                        code=CodeableConcept(coding=[Coding(system="http://loinc.org", code=loinc)]),
                        subject=Reference(reference=f"Patient/{row['patient_nbr']}"),
                        valueQuantity=Quantity(value=value, unit=unit),
                    )
                    summary["observations_validated"] += 1
                except ValidationError as exc:
                    summary["observation_errors"] += 1
                    message = _describe_validation_error(f"Vital sign ({column})", idx, exc)
                    summary["errors"].append(message)
                    summary["error_details"].append((idx, message))

    return summary


def validate_loinc_code(code: str) -> bool:
    """Return whether a code has a valid LOINC-shaped representation.

    This is a format stub, not a claim that the code exists in the current
    LOINC release. Existence should be checked against a licensed ValueSet.
    """
    return _has_valid_loinc_check_digit(code)


def validate_snomed_code(code: str) -> bool:
    """Return whether a code has a valid SNOMED CT identifier shape."""
    return bool(SNOMED_PATTERN.fullmatch(code))
