import unittest
from datetime import datetime
from src.fhir.builders import (
    build_patient,
    build_device,
    build_observation,
    build_flag,
    build_game_theory_flag,
    build_bundle,
    resource_to_dict
)
from src.fhir.validator import validate_resource, validate_bundle
from src.datalake.schemas.base import DeviceBinding, DeviceType, TelemetrySource


class TestFhirInteroperability(unittest.TestCase):

    def test_patient_resource_validation(self):
        pat = build_patient(patient_id="PAT-001", gender="female", birth_date="1992-04-10")
        pat_dict = resource_to_dict(pat)
        is_valid, errors = validate_resource(pat_dict)
        self.assertTrue(is_valid, f"Validation errors: {errors}")
        self.assertEqual(pat_dict["resourceType"], "Patient")

    def test_observation_resource_validation(self):
        obs = build_observation(
            observation_id="OBS-001",
            patient_id="PAT-001",
            metric="heart_rate",
            value=74.0,
            effective_datetime=datetime.utcnow()
        )
        obs_dict = resource_to_dict(obs)
        is_valid, errors = validate_resource(obs_dict)
        self.assertTrue(is_valid, f"Validation errors: {errors}")
        self.assertEqual(obs_dict["resourceType"], "Observation")

    def test_game_theory_flag_validation(self):
        flag = build_game_theory_flag(
            flag_id_or_assessment="FLAG-GT-001",
            patient_id="PAT-001",
            ama_evasion_risk=0.25,
            overtreatment_pressure=0.40,
            discharge_assurance=0.75,
            team_deadlock_risk=0.15,
            recommendation="Align care protocols"
        )
        flag_dict = resource_to_dict(flag)
        is_valid, errors = validate_resource(flag_dict)
        self.assertTrue(is_valid, f"Validation errors: {errors}")
        self.assertEqual(flag_dict["resourceType"], "Flag")

    def test_bundle_validation(self):
        pat = build_patient(patient_id="PAT-002", birth_date="1980-01-01")
        obs = build_observation(
            observation_id="OBS-002",
            patient_id="PAT-002",
            metric="spo2",
            value=98.0,
            effective_datetime=datetime.utcnow()
        )
        bundle = build_bundle(resources=[pat, obs], bundle_id="BUN-001")
        bundle_dict = resource_to_dict(bundle)
        val_res = validate_bundle(bundle_dict)
        self.assertTrue(val_res["bundle_valid"], f"Bundle validation errors: {val_res.get('bundle_errors')}")
        self.assertEqual(bundle_dict["resourceType"], "Bundle")


if __name__ == "__main__":
    unittest.main()
