import pathlib
import sys
import unittest


ROS_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROS_DIR))

from rtk_navigation_core import RtkHealthTracker, RtkThresholds, haversine_m


class RtkHealthTrackerTests(unittest.TestCase):
    def make_tracker(self):
        return RtkHealthTracker(
            RtkThresholds(
                stale_sec=2.0,
                gga_stale_sec=2.0,
                min_jump_m=1.0,
                max_jump_speed_mps=3.0,
                recovery_fixes=2,
            )
        )

    def test_requires_fresh_gga_quality_four(self):
        tracker = self.make_tracker()
        tracker.update_fix(22.349278, 113.584101, received_at=100.0)
        tracker.update_gga(5, received_at=100.0)
        self.assertFalse(tracker.snapshot(100.5)["valid"])
        tracker.update_gga(4, received_at=100.5)
        self.assertTrue(tracker.snapshot(100.5)["valid"])
        self.assertFalse(tracker.snapshot(103.0)["valid"])

    def test_jump_is_rejected_and_latched(self):
        tracker = self.make_tracker()
        tracker.update_gga(4, received_at=100.0)
        self.assertTrue(tracker.update_fix(22.349278, 113.584101, received_at=100.0))
        self.assertFalse(tracker.update_fix(22.350278, 113.584101, received_at=100.1))
        status = tracker.snapshot(100.1)
        self.assertTrue(status["jump"]["active"])
        self.assertFalse(status["valid"])
        self.assertAlmostEqual(status["position"]["latitude"], 22.349278)

    def test_jump_recovers_only_after_stable_fixes(self):
        tracker = self.make_tracker()
        tracker.update_gga(4, received_at=100.0)
        tracker.update_fix(22.349278, 113.584101, received_at=100.0)
        tracker.update_fix(22.350278, 113.584101, received_at=100.1)
        tracker.update_fix(22.349279, 113.584101, received_at=100.5)
        self.assertTrue(tracker.snapshot(100.5)["jump"]["active"])
        tracker.update_fix(22.349280, 113.584101, received_at=101.0)
        tracker.update_gga(4, received_at=101.0)
        self.assertTrue(tracker.snapshot(101.0)["valid"])

    def test_haversine_is_in_metres(self):
        self.assertGreater(haversine_m(0.0, 0.0, 0.0, 0.001), 110.0)
        self.assertLess(haversine_m(0.0, 0.0, 0.0, 0.001), 112.0)


if __name__ == "__main__":
    unittest.main()
