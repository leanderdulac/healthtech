"""
test_api_server.py — Testes Unitários dos Endpoints da API Server FastAPI
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["TESTING"] = "1"


class TestApiServer(unittest.TestCase):

    def test_app_metadata(self):
        from src.api_server import app
        self.assertEqual(app.title, "HealthTech Advanced API Server")
        self.assertTrue(len(app.routes) > 0)

    def test_root_redirect(self):
        from src.api_server import read_root
        response = read_root()
        self.assertEqual(response.status_code, 307)
        self.assertTrue("dashboard" in response.headers["location"])

    def test_get_status_structure(self):
        with patch("src.api_server.dl_manager.load_latest_knowledge", return_value=[]):
            from src.api_server import get_status
            status = get_status()
            self.assertIn("status", status)
            self.assertEqual(status["status"], "online")
            self.assertIn("config", status)
            self.assertIn("simulation_running", status["config"])

    def test_simulate_windkessel_endpoint(self):
        from src.api_server import simulate_windkessel_4e, WindkesselSimRequest
        req = WindkesselSimRequest(Rp=1.0, C=1.2, Zc=0.05, L=0.005, hr=75.0, sv=70.0, duration_s=1.0)
        res = simulate_windkessel_4e(req)
        self.assertIn("time", res)
        self.assertIn("pressure", res)
        self.assertIn("metrics", res)
        self.assertGreater(res["metrics"]["systolic_bp"], res["metrics"]["diastolic_bp"])
        self.assertGreater(res["metrics"]["pwv_bramwell_hill"], 0.0)

    def test_solve_triage_endpoint(self):
        from src.api_server import solve_triage_game, TriageSolveRequest
        req = TriageSolveRequest(icu_capacity=10, ward_capacity=40, icu_demand=12, ward_demand=30, high_risk_fraction=0.3)
        res = solve_triage_game(req)
        self.assertIn("nash_equilibrium", res)
        self.assertIn("pareto_frontier", res)
        self.assertIn("clinical_recommendation", res)

    def test_evaluate_clinical_consensus_endpoint(self):
        from src.api_server import evaluate_clinical_consensus, MultiAgentConsensusRequest
        req = MultiAgentConsensusRequest(
            patient_id="PAT-TEST-001",
            vitals={"heart_rate": 72.0, "spo2": 98.0},
            phantom_data={"systolic_bp": {"estimate": 120.0}, "diastolic_bp": {"estimate": 80.0}}
        )
        res = evaluate_clinical_consensus(req)
        self.assertIn("consensus_risk", res)
        self.assertIn("consensus_probabilities", res)
        self.assertIn("fhir_diagnostic_report", res)


if __name__ == "__main__":
    unittest.main(argv=["first-arg-is-ignored"], exit=False)
