"""Small, strict FHIR R4 resource validation boundary.

This module intentionally validates resource shape and terminology format. A
production deployment should replace the terminology stubs with an approved
FHIR terminology server or versioned local ValueSet.
"""

import re
from datetime import date, datetime
from typing import Any, ClassVar, Dict, Literal, Optional, cast

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


_GENDER_MAP = {"male": "male", "female": "female", "other": "other"}


def _normalize_gender_series(series: pd.Series) -> pd.Series:
    """Vectorized form of `_normalize_gender` for an entire column."""
    normalized = series.astype("string").str.strip().str.lower()
    return normalized.map(_GENDER_MAP).fillna("unknown")


def _validate_patient_row(idx: Any, patient_nbr: Any, gender: str, birth_date: Any) -> Optional[str]:
    """Run the strict Pydantic `Patient` model for one row and return an error message, if any."""
    try:
        Patient(id=str(patient_nbr), gender=gender, birthDate=birth_date if pd.notna(birth_date) else None)
        return None
    except ValidationError as exc:
        return _describe_validation_error("Patient", idx, exc)


def _validate_observation_row(
    idx: Any, patient_nbr: Any, column: str, loinc: str, value: float, unit: str, resource_label: str
) -> Optional[str]:
    """Run the strict Pydantic `Observation` model for one row and return an error message, if any."""
    try:
        Observation(
            id=f"obs-{idx}-{column}".replace("_", "-"),
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code=loinc)]),
            subject=Reference(reference=f"Patient/{patient_nbr}"),
            valueQuantity=Quantity(value=value, unit=unit),
        )
        return None
    except ValidationError as exc:
        return _describe_validation_error(resource_label, idx, exc)


def _validate_vital_sign_row(
    idx: Any, patient_nbr: Any, column: str, loinc: str, value: float, unit: str, resource_label: str
) -> Optional[str]:
    """Run the strict Pydantic `VitalSigns` model for one row and return an error message, if any."""
    try:
        VitalSigns(
            id=f"vital-{idx}-{column}".replace("_", "-"),
            status="final",
            code=CodeableConcept(coding=[Coding(system="http://loinc.org", code=loinc)]),
            subject=Reference(reference=f"Patient/{patient_nbr}"),
            valueQuantity=Quantity(value=value, unit=unit),
        )
        return None
    except ValidationError as exc:
        return _describe_validation_error(resource_label, idx, exc)


def _validate_patients(df: pd.DataFrame, summary: Dict[str, Any]) -> None:
    """Validate the patient-level columns.

    A vectorized pre-pass (id shape, gender, birth date not in the future)
    clears every row that is obviously fine so Pydantic never runs on them.
    Only the rows that fail -- or are ambiguous (e.g. an unparsable date) --
    pay the per-row Pydantic cost, which is also what produces the audit-safe
    error message.
    """
    id_str = df["patient_nbr"].astype("string")
    id_ok = id_str.notna() & id_str.str.match(FHIR_ID)

    gender_series = _normalize_gender_series(df.get("gender", pd.Series("unknown", index=df.index)))

    if "birthDate" in df.columns:
        parsed_dates = pd.to_datetime(df["birthDate"], errors="coerce")
        has_raw_date = df["birthDate"].notna()
        date_unparsable = has_raw_date & parsed_dates.isna()
        date_in_future = parsed_dates.notna() & (parsed_dates > pd.Timestamp.now())
        date_ok = ~date_unparsable & ~date_in_future
    else:
        date_unparsable = pd.Series(False, index=df.index)
        date_ok = pd.Series(True, index=df.index)

    fast_path_ok = id_ok & date_ok
    needs_pydantic = ~fast_path_ok

    summary["patients_validated"] += int(fast_path_ok.sum())

    if needs_pydantic.any():
        birth_dates = df["birthDate"] if "birthDate" in df.columns else pd.Series(None, index=df.index)
        for idx in df.index[needs_pydantic]:
            message = _validate_patient_row(
                idx, df.at[idx, "patient_nbr"], str(gender_series.at[idx]), birth_dates.at[idx]
            )
            if message is None:
                summary["patients_validated"] += 1
            else:
                summary["patient_errors"] += 1
                summary["errors"].append(message)
                summary["error_details"].append((idx, message))


def _validate_quantity_columns(
    df: pd.DataFrame,
    columns: Dict[str, str],
    summary: Dict[str, Any],
    unit_of: Any,
    ranges: Optional[Dict[str, tuple]],
    resource_noun: str,
    validator: Any,
) -> None:
    """Shared vectorized pre-pass + Pydantic-on-failure path for lab/vital columns.

    For each configured column: coerce to numeric (vectorized), flag
    non-numeric values without needing a model at all, and -- when a
    plausible range is known for the column -- clear in-range rows without
    invoking Pydantic. Only out-of-range or otherwise ambiguous rows fall
    through to the strict per-row model, which also formats the audit-safe
    error message.
    """
    present = df["patient_nbr"].notna()
    for column, loinc in columns.items():
        if column not in df.columns:
            continue

        unit = unit_of(column) if callable(unit_of) else unit_of
        raw = df[column]
        has_value = raw.notna() & present
        numeric = pd.to_numeric(raw, errors="coerce")
        non_numeric = has_value & numeric.isna()

        summary["observation_errors"] += int(non_numeric.sum())
        for idx in df.index[non_numeric]:
            message = f"{resource_noun} row {idx} column {column}: non-numeric value"
            summary["errors"].append(message)
            summary["error_details"].append((idx, message))

        is_numeric = has_value & numeric.notna()
        bounds = ranges.get(loinc) if ranges else None
        if bounds is not None:
            low, high = bounds
            in_range = is_numeric & (numeric >= low) & (numeric <= high)
        else:
            in_range = pd.Series(False, index=df.index)

        summary["observations_validated"] += int(in_range.sum())

        needs_pydantic = is_numeric & ~in_range
        resource_label = f"{resource_noun} ({column})"
        for idx in df.index[needs_pydantic]:
            message = validator(
                idx, df.at[idx, "patient_nbr"], column, loinc, cast(float, numeric.at[idx]), unit, resource_label
            )
            if message is None:
                summary["observations_validated"] += 1
            else:
                summary["observation_errors"] += 1
                summary["errors"].append(message)
                summary["error_details"].append((idx, message))


def validate_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    """Validate a tabular dataset's patient/lab/vital-sign columns as FHIR resources.

    This is the single validation path shared by the materialized and
    streaming pipeline modes, and by the standalone `quality` report: both
    map the same source columns to the same strict models, so results do
    not depend on which execution mode produced them.

    Validation runs as a vectorized pandas pass first; only rows that the
    fast path cannot clear outright (or flags as failing) are ever handed to
    the strict per-row Pydantic models, which remain the source of truth for
    FHIR shape/terminology rules and for audit-safe error messages.
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
        _validate_patients(df, summary)

        _validate_quantity_columns(
            df,
            LAB_LOINC_CODES,
            summary,
            unit_of="mg/dL",
            ranges=None,
            resource_noun="Observation",
            validator=_validate_observation_row,
        )

        vital_units = {"systolic_bp": "mmHg", "heart_rate": "bpm", "temperature": "C", "spo2": "%"}
        _validate_quantity_columns(
            df,
            VITAL_SIGN_LOINC_CODES,
            summary,
            unit_of=lambda column: vital_units[column],
            ranges=VitalSigns.VITAL_RANGES,
            resource_noun="Vital sign",
            validator=_validate_vital_sign_row,
        )

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
