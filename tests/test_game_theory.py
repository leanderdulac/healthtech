import unittest
from datetime import datetime
from src.clinical_intelligence.models import PatientBaseline, DenoisedSignal, GhostSignal
from src.clinical_intelligence.game_theory import GameTheoryAligner, GameTheoryAssessment
from src.fhir.builders import build_game_theory_flag
from fhir.resources.flag import Flag


class TestGameTheoryEngine(unittest.TestCase):

    def setUp(self):
        self.aligner = GameTheoryAligner()
        self.baseline = PatientBaseline(
            patient_id="PAT-TEST-123",
            name="John Doe",
            birth_date="1980-05-15",
            gender="male",
            resting_hr=72.0,
            baseline_spo2=98.0,
            baseline_hrv=55.0,
            clinical_conditions=["hypertension", "chronic pain"],
            medications=["losartan"],
            allergies=[]
        )

        # Mocking 4 denoised signals with 10 timestamps
        timestamps = [f"2026-07-18T12:00:0{i}Z" for i in range(10)]
        self.signals = {
            "heart_rate": DenoisedSignal(
                metric="heart_rate",
                raw=[72.0 + i for i in range(10)],
                filtered=[72.0 + i for i in range(10)],
                timestamps=timestamps,
                noise_estimate=0.5,
                artifact_ratio=0.01,
                quality_score=0.95
            ),
            "spo2": DenoisedSignal(
                metric="spo2",
                raw=[98.0 for _ in range(10)],
                filtered=[98.0 for _ in range(10)],
                timestamps=timestamps,
                noise_estimate=0.1,
                artifact_ratio=0.0,
                quality_score=0.98
            ),
            "hrv": DenoisedSignal(
                metric="hrv",
                raw=[55.0 for _ in range(10)],
                filtered=[55.0 for _ in range(10)],
                timestamps=timestamps,
                noise_estimate=0.8,
                artifact_ratio=0.02,
                quality_score=0.92
            ),
            "stress": DenoisedSignal(
                metric="stress",
                raw=[30.0 for _ in range(10)],
                filtered=[30.0 for _ in range(10)],
                timestamps=timestamps,
                noise_estimate=2.0,
                artifact_ratio=0.05,
                quality_score=0.85
            )
        }

        self.ghost_signals = [
            GhostSignal(name="autonomic_imbalance", value=0.35, confidence=0.80),
            GhostSignal(name="hidden_hypoxemia", value=0.20, confidence=0.90)
        ]

    def test_evaluate_dynamics_bounds(self):
        assessment = self.aligner.evaluate_dynamics(
            baseline=self.baseline,
            signals=self.signals,
            ghost_signals=self.ghost_signals,
            clinical_complexity_score=0.45
        )

        self.assertIsInstance(assessment, GameTheoryAssessment)
        self.assertEqual(assessment.patient_id, "PAT-TEST-123")
        
        # Verify escores are within bounds [0.05, 0.95]
        for score_name in ["ama_evasion_risk", "overtreatment_pressure", "discharge_assurance", "team_deadlock_risk"]:
            val = getattr(assessment, score_name)
            self.assertTrue(0.05 <= val <= 0.95, f"{score_name} was {val}, out of bounds!")

    def test_evaluate_dynamics_high_risk_sud(self):
        # Patient with substance abuse should have higher AMA evasion risk
        baseline_sud = PatientBaseline(
            patient_id="PAT-SUD-456",
            name="Jane Doe",
            birth_date="1990-01-01",
            gender="female",
            resting_hr=80.0,
            baseline_spo2=97.0,
            baseline_hrv=40.0,
            clinical_conditions=["opioid dependency", "anxiety"],
            medications=[],
            allergies=[]
        )
        
        assessment = self.aligner.evaluate_dynamics(
            baseline=baseline_sud,
            signals=self.signals,
            ghost_signals=self.ghost_signals,
            clinical_complexity_score=0.80
        )
        
        # Should be relatively high due to SUD flag
        self.assertGreater(assessment.ama_evasion_risk, 0.20)

    def test_build_game_theory_flag(self):
        assessment = self.aligner.evaluate_dynamics(
            baseline=self.baseline,
            signals=self.signals,
            ghost_signals=self.ghost_signals,
            clinical_complexity_score=0.45
        )

        flag_resource = build_game_theory_flag(assessment)
        self.assertIsInstance(flag_resource, Flag)
        self.assertEqual(flag_resource.status, "active")
        
        # Verify extensions are present
        self.assertTrue(len(flag_resource.extension) >= 4)
        
        # Test serialization to dict
        flag_dict = flag_resource.dict()
        self.assertEqual(flag_dict["resourceType"], "Flag")
        self.assertEqual(flag_dict["id"], flag_resource.id)


if __name__ == "__main__":
    unittest.main()
