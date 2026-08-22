import pandas as pd
import pytest
from pydantic import ValidationError

from healthcli.fhir_validator import Observation, Patient, validate_loinc_code
from healthcli.memory_optimizer import PandasMemoryOptimizer


def test_memory_optimizer_downcasts_and_reports_savings():
    frame = pd.DataFrame({"value": [1, 2, 3], "status": ["final", "final", "final"]})

    optimized, metrics = PandasMemoryOptimizer().optimize(frame)

    assert str(optimized["value"].dtype) == "int8"
    assert metrics.after_bytes < metrics.before_bytes
    assert metrics.reduction_ratio > 0


def test_patient_rejects_future_birth_date():
    with pytest.raises(ValidationError):
        Patient(id="p-1", birthDate="2999-01-01")


def test_observation_requires_loinc_shaped_code():
    with pytest.raises(ValidationError):
        Observation(
            id="obs-1",
            status="final",
            code={"coding": [{"system": "http://loinc.org", "code": "bad"}]},
            subject={"reference": "Patient/p-1"},
        )

    assert validate_loinc_code("2345-7")
