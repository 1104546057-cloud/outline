import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import detector_client as dc


class RecognitionStatusTests(unittest.TestCase):
    def setUp(self):
        with dc._CACHE_LOCK:
            dc._LAST_DETECTIONS.clear()
            dc._LAST_DETECTIONS.update(
                {"detections": [], "source": "detector", "last_detection_time": 0}
            )
            dc._LAST_BY_DEVICE.clear()
            dc._INFERENCE_CONTROL.clear()

    def test_stop_does_not_treat_12s_cache_as_live(self):
        dc.ingest_detections(
            {
                "detections": [{"label": "clock", "confidence": 0.9, "bbox": {"x": 1, "y": 2, "width": 3, "height": 4}}],
                "detector": {"enabled": True, "latency_ms": 300},
                "source": "camera",
                "camera": "gun",
            },
            device_id=2,
        )
        dc.set_inference_control(2, {"enabled": False, "pid": 0, "gpu_released": True, "state": "inactive"})
        dc.ingest_detections(
            {
                "detections": [{"label": "clock", "confidence": 0.9, "bbox": {"x": 1, "y": 2, "width": 3, "height": 4}}],
                "detector": {"enabled": True, "latency_ms": 300},
                "source": "camera",
                "camera": "gun",
            },
            device_id=2,
        )
        status = dc.get_detector_status(2)
        cached = dc.last_detections(2)
        self.assertFalse(status["enabled"])
        self.assertFalse(status["live"])
        self.assertTrue(status["stopped"])
        self.assertEqual(status["message"], "推理已停止")
        self.assertTrue(status["stale"])
        self.assertTrue(cached["stale"])
        self.assertFalse(cached["live"])
        self.assertEqual(len(cached["detections"]), 1)

    def test_start_marks_live_when_gpu_ready(self):
        dc.set_inference_control(
            2,
            {"enabled": True, "pid": 56999, "gpu_ready": True, "ready": True, "state": "active"},
        )
        status = dc.get_detector_status(2)
        self.assertTrue(status["enabled"])
        self.assertTrue(status["live"])
        self.assertEqual(status["message"], "推理在线")

    def test_dai_timeout_message_is_explicit(self):
        source = (BACKEND_DIR / "routers" / "recognition.py").read_text(encoding="utf-8")
        self.assertIn("timeout=75.0", source)
        self.assertIn("DAI 启动或停止超时", source)
        self.assertIn("10.139.91.78:9100", source)

    def test_zerotier_defaults_are_frozen(self):
        source = (BACKEND_DIR / "config.py").read_text(encoding="utf-8")
        example = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
        devices = (BACKEND_DIR / "vision_devices.json").read_text(encoding="utf-8")
        self.assertIn('os.getenv("DETECTOR_URL", "http://10.139.91.78:9100")', source)
        self.assertNotIn("192.168.31.9", source)
        self.assertIn("http://10.139.91.78:9100", example)
        self.assertIn("http://10.139.91.78:9100", devices)


if __name__ == "__main__":
    unittest.main()
