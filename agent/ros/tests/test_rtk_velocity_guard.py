import math
import json
from pathlib import Path
import unittest

from rtk_velocity_guard import RtkVelocityGuard


class VelocityGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.outputs = []
        self.guard = RtkVelocityGuard(lambda v, w: self.outputs.append((v, w)),
                                      clock=lambda: self.now)
        self.guard.arm()

    def command(self, v, w, dt=0.125):
        self.now += dt
        self.guard.command(v, w)

    def test_turn_reversal_is_bounded(self):
        for w in [0.22] * 5 + [-0.22] * 5:
            previous = self.guard.angular
            self.command(0.2, w)
            self.assertLessEqual(abs(self.outputs[-1][1]), 0.2 / 1.78)
            self.assertLessEqual(abs(self.outputs[-1][1] - previous), 0.050001)

    def test_stop_bypasses_slew_and_latches(self):
        self.command(0.2, 0.2)
        self.guard.stop()
        self.assertEqual(self.outputs[-1], (0, 0))
        self.command(0.2, 0.2)
        self.assertEqual(self.outputs[-1], (0, 0))
        self.guard.arm()
        self.command(0.2, 0.2)
        self.assertGreater(self.outputs[-1][0], 0)

    def test_planner_zero_is_immediate_and_can_resume(self):
        self.command(0.2, 0.2)
        self.command(0, 0)
        self.assertEqual(self.outputs[-1], (0, 0))
        self.command(0.2, 0.2)
        self.assertGreater(self.outputs[-1][0], 0)

    def test_timeout_cannot_be_revived_by_late_command(self):
        self.command(0.2, 0.2)
        self.now += 0.6
        self.guard.check_timeout()
        self.command(0.2, 0.2)
        self.assertEqual(self.outputs[-1], (0, 0))
        self.assertFalse(self.guard.enabled)

    def test_late_callback_detects_timeout_before_watchdog(self):
        self.command(0.2, 0.2)
        self.command(0.2, 0.2, dt=0.6)
        self.assertFalse(self.guard.enabled)
        self.assertEqual(self.outputs[-1], (0, 0))

    def test_invalid_and_stationary_commands(self):
        self.command(0, 0.2)
        self.assertEqual(self.outputs[-1], (0, 0))
        self.command(0.2, math.nan)
        self.assertFalse(self.guard.enabled)

    def test_speed_reduction_prioritizes_curvature(self):
        for _ in range(4):
            self.command(0.2, 0.2)
        self.command(0.01, 0.2)
        self.assertLessEqual(abs(self.outputs[-1][1]), 0.01 / 1.78)

    def test_waypoint_handoff_does_not_reset_smoothing(self):
        self.command(0.2, 0.2)
        previous = self.guard.angular
        self.guard.arm()
        self.assertEqual(self.guard.angular, previous)

    def test_recorded_run_preserves_stops_and_physical_bounds(self):
        rows = json.loads((Path(__file__).parent / 'fixtures' / 'rtk_sway_commands.json').read_text())
        for timestamp, v, w in rows:
            self.now = timestamp
            self.guard.command(v, w)
            actual_v, actual_w = self.outputs[-1]
            self.assertTrue(self.guard.enabled, 'unexpected stream timeout')
            self.assertEqual(actual_v, v)
            self.assertLessEqual(abs(actual_w), abs(v) / 1.78 + 1e-9)
            if v == 0:
                self.assertEqual(actual_w, 0)
        self.assertEqual(len(self.outputs), len(rows))


if __name__ == '__main__':
    unittest.main()
