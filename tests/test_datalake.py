import unittest
import tempfile
from pathlib import Path
from datetime import datetime
from src.datalake.config import LakehouseConfig
from src.datalake.utils.telemetry_simulator import SimulationConfig
from src.datalake.pipeline.orchestrator import DatalakeOrchestrator


class TestDatalakePipeline(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = LakehouseConfig(base_path=Path(self.temp_dir.name))
        self.orchestrator = DatalakeOrchestrator(self.config)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_medallion_pipeline(self):
        sim_config = SimulationConfig(
            num_patients=2,
            hours=0.1,  # 6 minutes
            hr_interval_seconds=10,
            seed=42
        )
        start_time = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = self.orchestrator.run_full_pipeline(
            simulation_config=sim_config,
            start_time=start_time
        )
        
        self.assertEqual(len(result.patients), 2)
        self.assertGreater(result.ingestion["valid"], 0)
        self.assertGreater(result.silver_rows, 0)
        self.assertTrue(result.quality_bronze_silver["passed"])


if __name__ == "__main__":
    unittest.main()
