"""Small, strict FHIR R4 resource validation boundary.

This module intentionally validates resource shape and terminology format. A
production deployment should replace the terminology stubs with an approved
FHIR terminology server or versioned local ValueSet.
"""

from datetime import date, datetime
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


FHIR_ID = r"^[A-Za-z0-9\-\.]{1,64}$"
LOINC_PATTERN = re.compile(r"^\d{1,5}-\d$")
SNOMED_PATTERN = re.compile(r"^\d{6,18}$")


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
        if system == "http://loinc.org" and not LOINC_PATTERN.fullmatch(value):
            raise ValueError("LOINC code must have the form 'digits-check_digit'")
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


def validate_loinc_code(code: str) -> bool:
    """Return whether a code has a valid LOINC-shaped representation.

    This is a format stub, not a claim that the code exists in the current
    LOINC release. Existence should be checked against a licensed ValueSet.
    """
    return bool(LOINC_PATTERN.fullmatch(code))


def validate_snomed_code(code: str) -> bool:
    """Return whether a code has a valid SNOMED CT identifier shape."""
    return bool(SNOMED_PATTERN.fullmatch(code))
