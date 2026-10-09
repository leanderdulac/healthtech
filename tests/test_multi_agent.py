"""
test_multi_agent.py — Testes Unitários do Conselho Clínico Multi-Agente (Dempster-Shafer)
"""

import unittest
from src.clinical_intelligence.agents import (
    SpecialistOpinion,
    CardiologyAgent,
    PulmonologyAgent,
    IntensivistTriageAgent,
    ClinicalConsensusCoordinator,
)


class TestMultiAgentConsensus(unittest.TestCase):

    def setUp(self):
        self.coordinator = ClinicalConsensusCoordinator()
        self.cardio = CardiologyAgent()
        self.pulmo = PulmonologyAgent()
        self.triage = IntensivistTriageAgent()

    def test_cardiology_agent_stable_and_critical(self):
        # Paciente estável
        stable_op = self.cardio.evaluate(
            vitals={"heart_rate": 72.0, "hrv_rmssd": 45.0},
            phantom_data={"systolic_bp": {"estimate": 120.0}, "diastolic_bp": {"estimate": 80.0}},
            hemodynamics={"pwv_bramwell_hill": 7.2}
        )
        self.assertEqual(stable_op.risk_level, "low")
        self.assertGreater(stable_op.mass_assignment["Normal"], 0.6)

        # Paciente instável / crítico
        crit_op = self.cardio.evaluate(
            vitals={"heart_rate": 135.0, "hrv_rmssd": 12.0},
            phantom_data={"systolic_bp": {"estimate": 185.0}, "diastolic_bp": {"estimate": 115.0}},
            hemodynamics={"pwv_bramwell_hill": 14.5}
        )
        self.assertEqual(crit_op.risk_level, "critical")
        self.assertGreater(crit_op.mass_assignment["Critical"], 0.5)

    def test_pulmonology_stays_silent_without_a_reading(self):
        silent = self.pulmo.evaluate(
            vitals={"heart_rate": 80.0},
            phantom_data={"spo2": {"estimate": 80.0}},
        )
        self.assertEqual(silent.risk_level, "insufficient")
        self.assertEqual(silent.mass_assignment["Theta"], 1.0)
        self.assertNotIn("97", silent.rationale)
        self.assertNotIn("16", silent.rationale)
        self.assertNotIn("est_spo2", silent.supporting_biomarkers)

        measured = self.pulmo.evaluate(vitals={"spo2": 96.0})
        self.assertIn("96", measured.rationale)
        self.assertNotIn("16", measured.rationale)
        self.assertNotIn("respiratory_rate", measured.supporting_biomarkers)

    def test_cardiology_does_not_invent_a_normal_reading(self):
        silent = self.cardio.evaluate(vitals={})
        self.assertEqual(silent.risk_level, "insufficient")
        self.assertNotIn("75", silent.rationale)
        self.assertNotIn("120", silent.rationale)

    def test_empty_reading_is_not_called_stable(self):
        consensus = self.coordinator.reach_consensus(
            patient_id="PAT-EMPTY",
            vitals={},
        )
        self.assertEqual(consensus["consensus_risk"], "INSUFFICIENT")
        pulmo = consensus["specialist_opinions"][1]
        self.assertNotIn("97", pulmo["rationale"])
        self.assertNotIn("16", pulmo["rationale"])

    def test_pulmonology_agent_hypoxemia(self):
        # Descompensação respiratória
        pulmo_crit = self.pulmo.evaluate(
            vitals={"spo2": 86.0, "respiratory_rate": 28.0},
            phantom_data={"spo2": {"estimate": 87.0}}
        )
        self.assertEqual(pulmo_crit.risk_level, "critical")
        self.assertGreater(pulmo_crit.mass_assignment["Critical"], 0.5)

    def test_dempster_shafer_combination_rule(self):
        m1 = {"Critical": 0.7, "Elevated": 0.2, "Normal": 0.05, "Theta": 0.05}
        m2 = {"Critical": 0.8, "Elevated": 0.1, "Normal": 0.05, "Theta": 0.05}

        fused, conflict_k = ClinicalConsensusCoordinator.combine_dempster_shafer(m1, m2)
        
        # A probabilidade de Critical deve ser reforçada pelo consenso
        self.assertGreater(fused["Critical"], 0.8)
        self.assertGreaterEqual(conflict_k, 0.0)
        self.assertAlmostEqual(sum(fused.values()), 1.0, places=4)

    def test_reach_consensus_full_pipeline_and_fhir(self):
        vitals = {"heart_rate": 130.0, "spo2": 87.0, "respiratory_rate": 26.0}
        phantom = {
            "systolic_bp": {"estimate": 180.0},
            "diastolic_bp": {"estimate": 110.0},
            "spo2": {"estimate": 87.0}
        }
        consensus = self.coordinator.reach_consensus(
            patient_id="PAT-ICU-TEST-99",
            vitals=vitals,
            phantom_data=phantom,
            hemodynamics={"pwv_bramwell_hill": 13.0}
        )

        self.assertEqual(consensus["patient_id"], "PAT-ICU-TEST-99")
        self.assertIn(consensus["consensus_risk"], ["CRITICAL", "ELEVATED"])
        self.assertIn("fhir_diagnostic_report", consensus)
        
        # Validar integridade FHIR DiagnosticReport
        fhir = consensus["fhir_diagnostic_report"]
        self.assertEqual(fhir["resourceType"], "DiagnosticReport")
        self.assertEqual(fhir["subject"]["reference"], "Patient/PAT-ICU-TEST-99")
        self.assertTrue(len(fhir["conclusion"]) > 0)


if __name__ == "__main__":
    unittest.main()
