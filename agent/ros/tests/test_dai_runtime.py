import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dai_runtime import (
    DaiServiceGuard,
    apply_inference_transition,
    gpu_ready_from_payload,
    gpu_released_from_payload,
    parse_systemctl_show,
)


class GpuReadyTests(unittest.TestCase):
    def test_nested_tensorrt_detection_is_ready(self):
        service = {"active": True, "main_pid": 56999, "active_state": "active"}
        detector = {
            "online": True,
            "detection": {"backend": "tensorrt", "target": "gpu", "precision": "fp16"},
        }
        self.assertTrue(gpu_ready_from_payload(service, detector))

    def test_top_level_cpu_backend_is_not_ready(self):
        service = {"active": True, "main_pid": 1, "active_state": "active"}
        detector = {"online": True, "backend": "pytorch", "target": "cpu"}
        self.assertFalse(gpu_ready_from_payload(service, detector))

    def test_zero_pid_is_not_ready(self):
        service = {"active": False, "main_pid": 0, "active_state": "inactive"}
        detector = {"online": True, "detection": {"backend": "tensorrt", "target": "gpu"}}
        self.assertFalse(gpu_ready_from_payload(service, detector))
        self.assertTrue(gpu_released_from_payload(service))

    def test_parse_systemctl_show_pid(self):
        parsed = parse_systemctl_show("MainPID=0\nActiveState=inactive\nUnitFileState=disabled\n")
        self.assertEqual(parsed["main_pid"], 0)
        self.assertEqual(parsed["active_state"], "inactive")


class InferenceControlTests(unittest.TestCase):
    def test_repeat_start_does_not_spawn_extra_service(self):
        service = DaiServiceGuard()
        first = apply_inference_transition(True, service, lambda: {"enabled": True}, lambda: {"enabled": False})
        second = apply_inference_transition(True, service, lambda: {"enabled": True}, lambda: {"enabled": False})
        self.assertEqual(first["pid"], second["pid"])
        self.assertEqual(service.start_count, 2)
        self.assertTrue(service.active)

    def test_repeat_stop_stays_pid_zero(self):
        service = DaiServiceGuard()
        apply_inference_transition(True, service, lambda: {"enabled": True}, lambda: {"enabled": False})
        first = apply_inference_transition(False, service, lambda: {"enabled": True}, lambda: {"enabled": False})
        second = apply_inference_transition(False, service, lambda: {"enabled": True}, lambda: {"enabled": False})
        self.assertEqual(first["pid"], 0)
        self.assertEqual(second["pid"], 0)
        self.assertTrue(second["gpu_released"] if "gpu_released" in second else service.snapshot()["gpu_released"])
        self.assertEqual(service.pid, 0)

    def test_start_failure_rolls_back_to_stopped(self):
        service = DaiServiceGuard()
        service.fail_next_start = True
        with self.assertRaises(RuntimeError):
            apply_inference_transition(True, service, lambda: {"enabled": True}, lambda: {"enabled": False})
        self.assertEqual(service.pid, 0)
        self.assertFalse(service.active)

    def test_sender_failure_stops_service(self):
        service = DaiServiceGuard()

        def boom():
            raise RuntimeError("sender failed")

        with self.assertRaises(RuntimeError):
            apply_inference_transition(True, service, boom, lambda: {"enabled": False})
        self.assertEqual(service.pid, 0)

    def test_lock_serializes_clicks(self):
        service = DaiServiceGuard()
        errors = []

        def worker():
            try:
                apply_inference_transition(True, service, lambda: {"enabled": True}, lambda: {"enabled": False})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertTrue(service.active)
        self.assertEqual(service.pid, 1000)


class HeartbeatContractTests(unittest.TestCase):
    def test_control_commands_run_in_executor(self):
        source = (Path(__file__).resolve().parents[1] / "robot_control_server.py").read_text(encoding="utf-8")
        self.assertIn("run_in_executor(None, execute_command", source)
        self.assertIn("recognition_control", source)
        self.assertIn('if command.get("type") not in {"recognition_control", "recognition_status", "ping"}:', source)

    def test_stop_keeps_video_preserved_and_pid_zero(self):
        service = DaiServiceGuard()
        apply_inference_transition(True, service, lambda: {"enabled": True}, lambda: {"enabled": False})
        stopped = apply_inference_transition(False, service, lambda: {"enabled": True}, lambda: {"enabled": False})
        self.assertEqual(stopped["pid"], 0)
        self.assertTrue(stopped["video_preserved"])
        self.assertTrue(stopped["gpu_released"])

    def test_camera_status_ready_is_independent_of_detector(self):
        camera_source = (Path(__file__).resolve().parents[1] / "ros_camera_server.py").read_text(encoding="utf-8")
        self.assertIn('"ready": frame is not None', camera_source)
        self.assertIn("def set_enabled(self, enabled: bool)", camera_source)
        self.assertNotIn("httpd.shutdown()", camera_source.split("def set_enabled", 1)[1].split("def stop", 1)[0])


if __name__ == "__main__":
    unittest.main()
