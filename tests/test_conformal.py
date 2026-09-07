import unittest
import numpy as np
from src.clinical_intelligence.conformal.split_conformal import SplitConformalPredictor


class TestConformalPrediction(unittest.TestCase):

    def test_conformal_coverage_guarantee(self):
        np.random.seed(42)
        n_cal = 200
        # Probabilidades calibradas simuladas (2 horizontes)
        probs = np.random.uniform(0.1, 0.9, size=(n_cal, 2))
        labels = (probs > 0.5).astype(int)
        
        predictor = SplitConformalPredictor(alpha=0.10) # 90% coverage
        stats = predictor.calibrate(probs, labels, horizon_names=["event_6h", "event_24h"])
        
        self.assertTrue(predictor.calibrated)
        self.assertIn("event_6h", stats)
        self.assertIn("event_24h", stats)
        
        # Test predict_interval
        low, high = predictor.predict_interval(0.70, "event_6h")
        self.assertTrue(0.0 <= low <= 0.70 <= high <= 1.0)
        
        # Test predict_set
        pred_set = predictor.predict_set(0.85, "event_6h")
        self.assertIsInstance(pred_set, list)
        self.assertIn(1, pred_set)


if __name__ == "__main__":
    unittest.main()
