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


if __name__ == "__main__":
    unittest.main(argv=["first-arg-is-ignored"], exit=False)
