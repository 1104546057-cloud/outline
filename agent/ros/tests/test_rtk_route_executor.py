import time
import unittest

from rtk_route_executor import RtkRouteExecutor, sample_route_points


def point(longitude):
    return {"longitude": longitude, "latitude": 22.35}


class RtkRouteExecutorTests(unittest.TestCase):
    def wait_finished(self, executor, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = executor.status()
            if not status["active"]:
                return status
            time.sleep(0.01)
        self.fail("路线执行器未在测试时限内结束")

    def test_sampling_preserves_last_point(self):
        points = [point(113.57), point(113.570001), point(113.57003)]
        sampled = sample_route_points(points, 2.0)
        self.assertEqual(sampled[0], points[0])
        self.assertEqual(sampled[-1], points[-1])
        self.assertEqual(len(sampled), 2)

    def test_executes_waypoints_until_complete(self):
        goal_status = {"label": "SUCCEEDED"}
        sent = []
        executor = RtkRouteExecutor(
            send_goal=lambda longitude, latitude, yaw: sent.append((longitude, latitude, yaw)) or {},
            read_goal_status=lambda: goal_status,
            read_health=lambda: {"valid": True},
            cancel_goal=lambda: None,
            hard_stop=lambda: None,
            waypoint_spacing_m=0.1,
            poll_interval_sec=0.01,
        )
        executor.start({
            "networkId": "network-test",
            "distanceM": 6.0,
            "path": [point(113.57), point(113.57002), point(113.57004)],
        })
        status = self.wait_finished(executor)
        self.assertEqual(status["state"], "completed")
        self.assertEqual(status["progressPct"], 100.0)
        self.assertEqual(len(sent), 3)

    def test_aborted_waypoint_fails_route(self):
        executor = RtkRouteExecutor(
            send_goal=lambda longitude, latitude, yaw: {},
            read_goal_status=lambda: {"label": "ABORTED", "text": "blocked"},
            read_health=lambda: {"valid": True},
            cancel_goal=lambda: None,
            hard_stop=lambda: None,
            poll_interval_sec=0.01,
        )
        executor.start({
            "networkId": "network-test",
            "distanceM": 3.0,
            "path": [point(113.57), point(113.57003)],
        })
        status = self.wait_finished(executor)
        self.assertEqual(status["state"], "failed")
        self.assertIn("blocked", status["error"])

    def test_invalid_rtk_fails_route(self):
        executor = RtkRouteExecutor(
            send_goal=lambda longitude, latitude, yaw: {},
            read_goal_status=lambda: {},
            read_health=lambda: {"valid": False, "lastError": "GGA not fixed"},
            cancel_goal=lambda: None,
            hard_stop=lambda: None,
            poll_interval_sec=0.01,
        )
        executor.start({
            "networkId": "network-test",
            "distanceM": 3.0,
            "path": [point(113.57), point(113.57003)],
        })
        status = self.wait_finished(executor)
        self.assertEqual(status["state"], "failed")
        self.assertIn("GGA not fixed", status["error"])


if __name__ == "__main__":
    unittest.main()
