import os
import unittest
from unittest.mock import patch

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
        from src.api_server import get_status
        status = get_status()
        self.assertIn("status", status)
        self.assertEqual(status["status"], "online")
        self.assertIn("config", status)
        self.assertIn("simulation_running", status["config"])


if __name__ == "__main__":
    unittest.main()
