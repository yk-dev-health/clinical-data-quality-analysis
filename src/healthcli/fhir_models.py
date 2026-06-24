"""
FHIR-inspired Pydantic models for clinical data validation.

These models provide structured, type-safe definitions for healthcare data
without requiring full FHIR compliance. They capture core clinical fields
and enforce basic medical plausibility constraints.
"""

from datetime import datetime, date
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator


class Patient(BaseModel):
    """
    Simplified FHIR Patient resource.
    
    Core fields:
    - id: Unique patient identifier
    - gender: Biological sex (male/female/other/unknown)
    - birthDate: Date of birth for age calculation
    """
    id: str = Field(..., description="Patient unique identifier (e.g., MRN)")
    gender: Literal["male", "female", "other", "unknown"] = "unknown"
    birthDate: Optional[date] = Field(None, description="Date of birth")
    
    @field_validator("birthDate")
    @classmethod
    def validate_birth_date(cls, v):
        """Birth date cannot be in the future (basic sanity check)."""
        if v and v > date.today():
            raise ValueError("Birth date cannot be in the future")
        return v
    
    def age_years(self) -> Optional[int]:
        """Calculate age in years from birth date."""
        if not self.birthDate:
            return None
        today = date.today()
        return today.year - self.birthDate.year - (
            (today.month, today.day) < (self.birthDate.month, self.birthDate.day)
        )


class Quantity(BaseModel):
    """
    Represents a measured quantity with units.
    Example: 120 mmHg (systolic blood pressure)
    """
    value: float = Field(..., description="Numeric measurement value")
    unit: str = Field(..., description="Unit of measurement")
    code: str = Field(..., description="Unit code (e.g., mmHg, mg/dL)")


class Observation(BaseModel):
    """
    Simplified FHIR Observation resource.
    
    Represents a single clinical measurement (lab test, vital sign, etc).
    
    Core fields:
    - id: Unique observation identifier
    - status: Observation status (preliminary, final, etc)
    - code: What was measured (e.g., glucose, systolic BP)
    - subject: Patient ID reference
    - value: The measured quantity
    - effectiveDateTime: When observation was taken
    """
    id: str = Field(..., description="Observation unique ID")
    status: Literal["preliminary", "final", "amended", "cancelled"] = "final"
    code: str = Field(..., description="Observation code (e.g., glucose, blood-pressure-systolic)")
    subject: str = Field(..., description="Patient ID reference")
    value: Optional[Quantity] = None
    effectiveDateTime: Optional[datetime] = Field(None, description="Observation timestamp")


class VitalSigns(Observation):
    """
    Specialised Observation for vital signs.
    
    Enforces physiologically plausible ranges:
    - Systolic BP: 50–250 mmHg
    - Heart rate: 30–200 bpm
    - Temperature: 35–42 °C
    - SpO2: 50–100%
    """
    code: str = Field(..., description="Vital sign code (e.g., systolic-bp, heart-rate, temperature)")
    
    @field_validator("value")
    @classmethod
    def validate_vital_ranges(cls, v, info):
        """Enforce physiologically plausible ranges based on code."""
        if not v:
            return v
        
        code = info.data.get("code", "").lower()
        val = v.value
        
        # Systolic blood pressure: 50–250 mmHg
        if "systolic" in code or "sbp" in code:
            if val < 50 or val > 250:
                raise ValueError(f"Systolic BP {val} mmHg implausible (normal: 90–120)")
        
        # Heart rate: 30–200 bpm
        elif "heart.rate" in code or "pulse" in code or "hr" in code:
            if val < 30 or val > 200:
                raise ValueError(f"Heart rate {val} bpm implausible (normal: 60–100)")
        
        # Body temperature: 35–42 °C
        elif "temperature" in code or "temp" in code:
            if val < 35 or val > 42:
                raise ValueError(f"Body temperature {val} °C implausible (normal: 36.5–37.5)")
        
        # Oxygen saturation: 50–100%
        elif "oxygen" in code or "spo2" in code or "o2sat" in code:
            if val < 50 or val > 100:
                raise ValueError(f"SpO2 {val}% implausible (normal: 95–100)")
        
        return v
