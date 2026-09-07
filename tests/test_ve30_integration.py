"""
test_ve30_integration.py — Testes Automatizados de Integração do Smartwatch VE30 com a IA HealthTech
"""

import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["TESTING"] = "1"

from src.api_server import (
    app,
    ingest_wearable_reading,
    ingest_wearable_batch,
    get_patient_latest_telemetry,
    get_patient_telemetry_history,
    WearableTelemetryRequest,
    WearableBatchIngestRequest,
)
from src.ingestion.real.hband_normalizer import HBandNormalizer
from src.ingestion.real.hband_schemas import HBandRealtimeIngest, HBandDeviceInfo


class TestVe30Integration(unittest.TestCase):

    def setUp(self):
        self.normalizer = HBandNormalizer()
        self.patient_id = "PAT-VE30-TEST-001"
        self.device_id = "VE30-E4:65:08:AA:BB:CC"

    def test_ve30_realtime_ingest_and_ai_pipeline(self):
        """Valida se a telemetria do VE30 passa por Denoising, UKF, Diagnóstico e Consenso Multi-Agente."""
        req = WearableTelemetryRequest(
            patient_id=self.patient_id,
            device_id=self.device_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            heart_rate=76.0,
            spo2=98.5,
            skin_temp=33.4,
            blood_pressure_sys=122.0,
            blood_pressure_dia=81.0,
            hrv_rmssd=44.0,
            steps=1250,
            wear_status=True,
            ppg_signal=[500.0, 520.0, 560.0, 610.0, 580.0, 530.0, 505.0, 495.0],
            filter_type="BMO"
        )

        res = ingest_wearable_reading(req)

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["patient_id"], self.patient_id)
        self.assertEqual(res["device_id"], self.device_id)

        # 1. Validação de Dados Fantasmas inferidos pelo UKF
        self.assertIn("phantom_data", res)
        phantom = res["phantom_data"]
        self.assertIn("systolic_bp", phantom)
        self.assertIn("diastolic_bp", phantom)
        self.assertIn("spo2", phantom)
        self.assertIn("vagal_tone", phantom)
        self.assertIn("glucose", phantom)

        # 2. Validação de Detecção de Anomalias
        self.assertIn("anomaly_detection", res)
        self.assertIn("alerta", res["anomaly_detection"])

        # 3. Validação do Parecer do Conselho Clínico Multi-Agente
        self.assertIn("multi_agent_consensus", res)
        consensus = res["multi_agent_consensus"]
        self.assertIn("consensus_risk", consensus)
        self.assertIn("action_summary", consensus)
        self.assertIn("probabilities", consensus)

        # 4. Validação de Diagnóstico Ontológico (CID-10 / SNOMED CT)
        self.assertIn("diagnostic_hypotheses", res)
        self.assertIn("clinical_codes", res)

    def test_ve30_batch_history_sync(self):
        """Valida a sincronização em lote de blocos de 5 minutos de memória flash do VE30."""
        samples = [
            {
                "timestamp": "2026-08-19 14:00:00",
                "heart_rate": 72.0,
                "spo2": 98.0,
                "blood_pressure_sys": 120.0,
                "blood_pressure_dia": 80.0,
                "hrv": 45.0,
                "step_count": 240,
            },
            {
                "timestamp": "2026-08-19 14:05:00",
                "heart_rate": 75.0,
                "spo2": 97.5,
                "blood_pressure_sys": 122.0,
                "blood_pressure_dia": 81.0,
                "hrv": 43.0,
                "step_count": 310,
            },
        ]

        batch_req = WearableBatchIngestRequest(
            patient_id=self.patient_id,
            device_id=self.device_id,
            readings=samples
        )

        res = ingest_wearable_batch(batch_req)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["processed_samples"], 2)

    def test_ve30_patient_history_retrieval(self):
        """Valida a consulta do histórico e da leitura mais recente."""
        # Garantir ao menos uma leitura ingerida
        ingest_wearable_reading(WearableTelemetryRequest(
            patient_id=self.patient_id,
            device_id=self.device_id,
            heart_rate=75.0,
            spo2=98.0
        ))

        latest = get_patient_latest_telemetry(self.patient_id)
        self.assertEqual(latest["patient_id"], self.patient_id)
        self.assertIn("raw_telemetry", latest)

        history = get_patient_telemetry_history(self.patient_id, limit=5)
        self.assertEqual(history["patient_id"], self.patient_id)
        self.assertGreaterEqual(history["total_records"], 1)

    def test_hband_normalizer_conversion(self):
        """Valida que o HBandNormalizer traduz corretamente objetos HBandRealtimeIngest para a API."""
        hband_payload = HBandRealtimeIngest(
            patient_id="PAT-HBAND-TEST-99",
            device=HBandDeviceInfo(
                device_id="HBAND-VE30-77",
                vendor="hband",
                model="VE30",
                firmware_version="v2.1.4",
                battery_level=92.0
            ),
            heart_rate=82.0,
            spo2=99.0,
            skin_temp=33.6,
            blood_pressure_sys=124.0,
            blood_pressure_dia=82.0,
            hrv_rmssd=48.0,
            filter_type="BMO"
        )

        api_dict = self.normalizer.to_wearable_ingest(hband_payload)
        self.assertEqual(api_dict["patient_id"], "PAT-HBAND-TEST-99")
        self.assertEqual(api_dict["device_id"], "HBAND-VE30-77")
        self.assertEqual(api_dict["heart_rate"], 82.0)
        self.assertEqual(api_dict["spo2"], 99.0)

        # Ingerir via API endpoint
        req = WearableTelemetryRequest(**api_dict)
        res = ingest_wearable_reading(req)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["patient_id"], "PAT-HBAND-TEST-99")


if __name__ == "__main__":
    unittest.main()