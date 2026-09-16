import json
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import recognition_store as store


class RecognitionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        store.DATA_DIR = self.tmpdir
        store.DATA_FILE = self.tmpdir / "recognition_events.json"
        store.AI_DIR = self.tmpdir / "ai_analysis" / "recognition"
        store._LAST_SIGNATURE.clear()

    def test_record_contains_closed_loop_fields(self):
        jpeg = b"\xff\xd8fakejpeg\xff\xd9"
        events = store.record_detections(
            [{"label": "person", "confidence": 0.86, "bbox": {"x": 10, "y": 20, "width": 30, "height": 40}}],
            source="camera",
            device_id=2,
            device_name="室外巡检车",
            jpeg_bytes=jpeg,
            latency_ms=312,
            recognized_at="2026-09-16 12:00:00",
        )
        self.assertEqual(len(events), 1)
        event = events[0]
        for key in (
            "id",
            "device_id",
            "device_name",
            "subject",
            "confidence",
            "bbox",
            "time",
            "image",
            "latency_ms",
        ):
            self.assertIn(key, event)
        self.assertEqual(event["device_id"], 2)
        self.assertEqual(event["device_name"], "室外巡检车")
        self.assertEqual(event["subject"], "person")
        self.assertEqual(event["confidence"], 86)
        self.assertEqual(event["bbox"]["width"], 30)
        self.assertEqual(event["time"], "2026-09-16 12:00:00")
        self.assertEqual(event["latency_ms"], 312)
        self.assertTrue((self.tmpdir / event["image"]).is_file())
        sidecar = store.AI_DIR / f"{event['id']}.json"
        self.assertTrue(sidecar.is_file())
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(payload["device_id"], 2)
        self.assertEqual(payload["labels"], ["person"])

    def test_list_events_filters_device_and_time(self):
        store.record_detections(
            [{"label": "clock", "confidence": 0.7, "bbox": {}}],
            device_id=2,
            device_name="车A",
            recognized_at="2026-09-16 10:00:00",
            latency_ms=200,
        )
        store._LAST_SIGNATURE.clear()
        store.record_detections(
            [{"label": "person", "confidence": 0.8, "bbox": {}}],
            device_id=3,
            device_name="车B",
            recognized_at="2026-09-16 11:00:00",
            latency_ms=210,
        )
        only_two = store.list_events(device_id=2)
        self.assertEqual(len(only_two), 1)
        self.assertEqual(only_two[0]["subject"], "clock")
        later = store.list_events(since="2026-09-16 10:30:00")
        self.assertEqual(len(later), 1)
        self.assertEqual(later[0]["device_id"], 3)
        persisted = json.loads(store.DATA_FILE.read_text(encoding="utf-8"))
        self.assertEqual(len(persisted), 2)

    def test_reload_from_disk(self):
        store.record_detections(
            [{"label": "bag", "confidence": 0.5, "bbox": {"x": 0, "y": 0, "width": 8, "height": 8}}],
            device_id=2,
            device_name="室外巡检车",
            latency_ms=90,
        )
        store._LAST_SIGNATURE.clear()
        reloaded = store.list_events(limit=10)
        self.assertEqual(reloaded[0]["subject"], "bag")


if __name__ == "__main__":
    unittest.main()
