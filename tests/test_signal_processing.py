import unittest
import numpy as np
import pandas as pd
from src.signal_processing.physiological_signal_model import (
    OrnsteinUhlenbeckProcess,
    MultivariatePhysiologicalGenerator,
    generate_rr_intervals
)
from src.signal_processing.noise_separation import (
    WaveletDenoiser,
    ButterworthFilter,
    decompose_signal_components
)
from src.signal_processing.sensor_fusion import (
    AdaptiveSensorFusion,
    reconciliar_dados_bayesiano
)


class TestSignalProcessing(unittest.TestCase):

    def test_ornstein_uhlenbeck_dynamics(self):
        ou = OrnsteinUhlenbeckProcess(theta=0.5, mu=70.0, sigma=4.0, dt=1.0)
        series = ou.generate(n_steps=1000, x0=70.0, seed=42)
        
        self.assertEqual(len(series), 1000)
        # Check mean reversion around mu=70
        self.assertTrue(65.0 <= np.mean(series) <= 75.0)
        self.assertTrue(np.std(series) > 0.5)

    def test_multivariate_generator_correlations(self):
        gen = MultivariatePhysiologicalGenerator()
        pop_dict = gen.generate_population(n_individuals=500, seed=42)
        df = pd.DataFrame(pop_dict)
        
        self.assertEqual(len(df), 500)
        self.assertIn("resting_bpm", df.columns)
        self.assertIn("sleep_hours", df.columns)
        self.assertIn("activity_mins", df.columns)
        
        # Negative correlation between resting HR and sleep hours
        corr_hr_sleep = df["resting_bpm"].corr(df["sleep_hours"])
        self.assertLess(corr_hr_sleep, 0.0)

    def test_rr_intervals_generation(self):
        hr_series = [60.0, 75.0, 80.0, 100.0]
        rr = generate_rr_intervals(hr_series, jitter_std_ms=5.0)
        self.assertEqual(len(rr), 4)
        # 60 bpm -> ~1000 ms
        self.assertTrue(900.0 <= rr[0] <= 1100.0)

    def test_wavelet_denoising(self):
        t = np.linspace(0, 10, 256)
        clean = np.sin(2 * np.pi * 0.5 * t)
        noise = np.random.normal(0, 0.3, size=len(t))
        noisy = clean + noise
        
        denoiser = WaveletDenoiser(wavelet="db4", level=3)
        denoised = denoiser.denoise(noisy)
        
        self.assertEqual(len(denoised), len(noisy))
        snr = denoiser.estimate_snr(clean, denoised)
        self.assertTrue(np.isfinite(snr))

    def test_butterworth_filter(self):
        t = np.linspace(0, 1, 200)
        sig = np.sin(2 * np.pi * 5 * t) + np.sin(2 * np.pi * 50 * t)
        
        bf = ButterworthFilter(fs=200.0, order=3)
        lowpassed = bf.lowpass(sig, cutoff=15.0)
        
        self.assertEqual(len(lowpassed), len(sig))
        self.assertTrue(np.std(lowpassed) < np.std(sig))

    def test_bayesian_sensor_fusion(self):
        fusion = AdaptiveSensorFusion(sensor_ids=["s1", "s2"], initial_variance=4.0)
        readings = {"s1": 70.0, "s2": 72.0}
        
        result = fusion.fuse_readings(readings)
        self.assertIn("fused_estimate", result)
        self.assertIn("fused_variance", result)
        self.assertIn("weights", result)
        
        # Fused value must be bounded between readings
        self.assertTrue(70.0 <= result["fused_estimate"] <= 72.0)
        # Fused variance (BLUE) must be strictly lower than individual variance
        self.assertLess(result["fused_variance"], 4.0)


if __name__ == "__main__":
    unittest.main()
