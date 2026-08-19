import unittest
import numpy as np
from src.phantom_data.state_space_model import (
    ExtendedKalmanFilter,
    UnscentedKalmanFilter,
    PhysiologicalTransitionModel,
    WearableObservationModel
)
from src.phantom_data.adaptive_ukf import AdaptiveUnscentedKalmanFilter
from src.phantom_data.hrv_analysis import HRVAnalyzer


class TestPhantomDataEngine(unittest.TestCase):

    def test_ekf_filter_steps(self):
        ekf = ExtendedKalmanFilter(dim_x=5, dim_z=4, dt=1.0)
        trans = PhysiologicalTransitionModel()
        obs = WearableObservationModel()
        
        # Prediction
        x_pred, P_pred = ekf.predict(trans.f, trans.F_jacobian)
        self.assertEqual(len(x_pred), 5)
        self.assertEqual(P_pred.shape, (5, 5))
        
        # Update with synthetic wearable observation [HR, HRV, Temp, Activity]
        z = np.array([72.0, 42.0, 33.1, 0.0])
        x_up, P_up = ekf.update(z, obs.h, obs.H_jacobian)
        self.assertEqual(len(x_up), 5)
        self.assertTrue(np.all(np.diag(P_up) > 0))

    def test_adaptive_ukf_sage_husa(self):
        aukf = AdaptiveUnscentedKalmanFilter(dim_x=5, dim_z=4)
        trans = PhysiologicalTransitionModel()
        obs = WearableObservationModel()
        
        aukf.predict(lambda x: trans.f(x, dt=1.0))
        z = np.array([75.0, 40.0, 33.2, 0.0])
        res = aukf.update(z, obs.h)
        
        self.assertIn("state", res)
        self.assertIn("innovation", res)
        self.assertIn("adaptive_r_diag", res)
        self.assertEqual(len(res["state"]), 5)

    def test_observability_gramian(self):
        aukf = AdaptiveUnscentedKalmanFilter(dim_x=5, dim_z=4)
        A = np.eye(5) * 0.98
        H = np.zeros((4, 5))
        H[0, 0] = 0.3
        H[1, 3] = 0.8
        H[2, 2] = 0.01
        H[3, 4] = 0.1
        
        obs_res = aukf.compute_observability_gramian(A, H, horizon=8)
        self.assertIn("condition_number", obs_res)
        self.assertIn("is_observable", obs_res)
        self.assertTrue(obs_res["min_eigenvalue"] >= 0.0)

    def test_hrv_time_frequency_entropy(self):
        # 100 RR intervals around 800ms (75 bpm)
        rr = np.random.normal(800.0, 40.0, size=120)
        analyzer = HRVAnalyzer(fs=4.0)
        
        time_metrics = analyzer.compute_time_domain(rr)
        self.assertIn("sdnn", time_metrics)
        self.assertIn("rmssd", time_metrics)
        self.assertIn("pnn50", time_metrics)
        self.assertTrue(time_metrics["sdnn"] > 0)
        
        freq_metrics = analyzer.compute_frequency_domain(rr)
        self.assertIn("lf_hf_ratio", freq_metrics)
        self.assertIn("total_power", freq_metrics)
        
        entropy_metrics = analyzer.compute_nonlinear(rr)
        self.assertIn("sample_entropy", entropy_metrics)


if __name__ == "__main__":
    unittest.main()
