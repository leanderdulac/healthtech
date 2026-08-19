import unittest
import numpy as np
from src.hemodynamics.operators import VectorCalculus3D
from src.hemodynamics.models import Grid3D, ScalarField3D, VectorField3D
from src.hemodynamics.windkessel import (
    Windkessel4EParams,
    Windkessel4ESimulator,
    BaroreflexParams
)


class TestHemodynamics(unittest.TestCase):

    def test_vector_calculus_divergence_curl(self):
        # Create small 3D grid
        x, y, z = np.meshgrid(
            np.linspace(0, 1, 8),
            np.linspace(0, 1, 8),
            np.linspace(0, 1, 8),
            indexing="ij"
        )
        grid = Grid3D(x=x, y=y, z=z)
        
        # Velocity field: fx = y, fy = -x, fz = 0 (vortex around z)
        vf = VectorField3D(fx=y, fy=-x, fz=np.zeros_like(z), grid=grid)
        
        div = VectorCalculus3D.divergence(vf)
        curl = VectorCalculus3D.curl(vf)
        
        self.assertEqual(div.values.shape, (8, 8, 8))
        self.assertEqual(curl.fx.shape, (8, 8, 8))
        # Divergence of pure vortex is 0
        self.assertTrue(np.allclose(div.values[1:-1, 1:-1, 1:-1], 0, atol=1e-1))

    def test_windkessel_4element_rk4_simulation(self):
        params = Windkessel4EParams(Rp=1.0, C=1.3, Zc=0.05, L=0.005)
        sim = Windkessel4ESimulator(params=params)
        
        time, flow = sim.generate_ejection_flow(heart_rate=72.0, stroke_volume=70.0, fs=200.0, num_cycles=4)
        res = sim.simulate(time, flow, initial_pressure=80.0)
        
        self.assertIn("systolic_bp", res)
        self.assertIn("diastolic_bp", res)
        self.assertIn("mean_arterial_pressure", res)
        
        # PAS > PAD, physiologically realistic range
        self.assertGreater(res["systolic_bp"], res["diastolic_bp"])
        self.assertTrue(90.0 <= res["systolic_bp"] <= 180.0)
        self.assertTrue(50.0 <= res["diastolic_bp"] <= 110.0)

    def test_pulse_wave_velocity(self):
        sim = Windkessel4ESimulator()
        pwv = sim.compute_pulse_wave_velocity(distensibility=0.002)
        # Normal arterial PWV is between 4 and 15 m/s
        self.assertTrue(4.0 <= pwv <= 15.0)

    def test_baroreflex_feedback(self):
        sim = Windkessel4ESimulator()
        # High blood pressure (MAP = 120 mmHg) should reflexively decrease HR and Rp
        res_high_p = sim.evaluate_baroreflex(current_map=120.0, current_hr=80.0)
        self.assertLess(res_high_p["adjusted_heart_rate"], 80.0)


if __name__ == "__main__":
    unittest.main()
