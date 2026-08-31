import tempfile
import unittest
from pathlib import Path

from rtk_road_network import RoadWorkspace


FIXED = {"valid": True, "quality": 4, "lastError": ""}
INVALID = {"valid": False, "quality": 5, "lastError": "RTK 尚未达到 Fixed"}


class RoadWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = RoadWorkspace(
            Path(self.temp_dir.name),
            min_record_spacing_m=0.0,
            network_spacing_m=0.1,
            merge_radius_m=0.35,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_line(self, start_lon, count=5, lat=22.349278):
        for index in range(count):
            self.workspace.add_fix(
                start_lon + index * 0.00001,
                lat,
                5.0,
                2,
                0.0001,
                0.0001,
                FIXED,
                1000.0 + index,
            )

    def test_collection_requires_fixed_and_auto_pauses_invalid_fixes(self):
        with self.assertRaisesRegex(RuntimeError, "Fixed"):
            self.workspace.start("测试", INVALID)
        self.workspace.start("测试道路", FIXED)
        self.add_line(113.58410, count=2)
        accepted = self.workspace.add_fix(
            113.58413, 22.349278, 5.0, 2, None, None, INVALID, 1003.0
        )
        self.assertFalse(accepted)
        status = self.workspace.status()
        self.assertTrue(status["qualityPaused"])
        self.assertEqual(status["pointCount"], 2)
        self.assertEqual(status["skippedInvalid"], 1)

    def test_pause_resume_stop_and_persistence(self):
        self.workspace.start("主路", FIXED)
        self.add_line(113.58410, count=3)
        self.workspace.pause()
        self.assertFalse(self.workspace.add_fix(
            113.58414, 22.349278, 5.0, 2, None, None, FIXED, 1004.0
        ))
        self.workspace.resume(FIXED)
        self.workspace.add_fix(113.58414, 22.349278, 5.0, 2, None, None, FIXED, 1004.0)
        summary = self.workspace.stop()
        self.assertEqual(summary["statistics"]["pointCount"], 4)
        stored = self.workspace.get_track(summary["id"])
        self.assertEqual(stored["coordinateSystem"], "WGS-84")
        self.assertEqual(len(stored["points"]), 4)
        self.assertFalse(self.workspace.status()["active"])

    def test_build_network_and_plan(self):
        self.workspace.start("横向道路", FIXED)
        self.add_line(113.58410, count=8)
        first = self.workspace.stop()
        network = self.workspace.build_network("校园道路", [first["id"]])
        self.assertGreaterEqual(network["statistics"]["nodeCount"], 2)
        plan = self.workspace.plan(
            network["id"],
            113.58410,
            22.349278,
            113.58417,
            22.349278,
            max_snap_m=2.0,
        )
        self.assertGreater(len(plan["path"]), 1)
        self.assertGreater(plan["distanceM"], 0.0)
        self.assertLess(plan["goalSnapDistanceM"], 1.0)

    def test_plan_rejects_goal_outside_snap_limit(self):
        self.workspace.start("短路", FIXED)
        self.add_line(113.58410, count=4)
        track = self.workspace.stop()
        network = self.workspace.build_network("短路网络", [track["id"]])
        with self.assertRaisesRegex(ValueError, "目标距离道路网络"):
            self.workspace.plan(
                network["id"],
                113.58410,
                22.349278,
                113.58500,
                22.35000,
                max_snap_m=2.0,
            )

    def test_straight_spacing_and_turn_density(self):
        workspace = RoadWorkspace(
            Path(self.temp_dir.name) / "adaptive",
            min_record_spacing_m=1.0,
            turn_record_spacing_m=0.5,
            turn_threshold_deg=12.0,
        )
        workspace.start("自适应采样", FIXED)
        origin_lon = 113.58410
        origin_lat = 22.349278
        metres_per_lon_degree = 111320.0 * 0.925
        metres_per_lat_degree = 111320.0

        def add_metres(east, north, timestamp):
            return workspace.add_fix(
                origin_lon + east / metres_per_lon_degree,
                origin_lat + north / metres_per_lat_degree,
                5.0, 2, 0.0001, 0.0001, FIXED, timestamp,
            )

        self.assertTrue(add_metres(0.0, 0.0, 1000.0))
        self.assertFalse(add_metres(0.5, 0.0, 1001.0))
        self.assertTrue(add_metres(1.05, 0.0, 1002.0))
        self.assertTrue(add_metres(1.05, 0.55, 1003.0))
        status = workspace.status()
        self.assertEqual(status["pointCount"], 3)
        self.assertEqual(status["recordSpacingM"], 1.0)
        self.assertEqual(status["turnRecordSpacingM"], 0.5)


if __name__ == "__main__":
    unittest.main()
