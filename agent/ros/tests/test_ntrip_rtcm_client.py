import base64
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch


ROS_DIR = pathlib.Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROS_DIR))

from ntrip_rtcm_client import (
    LatestGga,
    NtripConfig,
    StatusWriter,
    build_ntrip_request,
    normalize_gga_sentence,
    parse_ntrip_response,
)


class NtripRtcmClientTests(unittest.TestCase):
    def config(self):
        return NtripConfig(
            host="rtk.example.test",
            port=8002,
            mountpoint="AUTO",
            username="vehicle-user",
            password="vehicle-password",
        )

    def test_request_contains_ntrip_headers_and_basic_auth(self):
        request = build_ntrip_request(self.config())
        self.assertTrue(request.startswith(b"GET /AUTO HTTP/1.0\r\n"))
        expected = base64.b64encode(b"vehicle-user:vehicle-password")
        self.assertIn(b"Authorization: Basic " + expected, request)
        self.assertTrue(request.endswith(b"\r\n\r\n"))

    def test_parses_http_and_icy_success(self):
        accepted, payload, status = parse_ntrip_response(
            b"HTTP/1.1 200 OK\r\nContent-Type: gnss/data\r\n\r\n\xd3\x00"
        )
        self.assertTrue(accepted)
        self.assertEqual(payload, b"\xd3\x00")
        self.assertEqual(status, "HTTP/1.1 200 OK")

        accepted, payload, status = parse_ntrip_response(b"ICY 200 OK\r\n\xd3\x01")
        self.assertTrue(accepted)
        self.assertEqual(payload, b"\xd3\x01")
        self.assertEqual(status, "ICY 200 OK")

    def test_rejects_auth_failure_without_exposing_credentials(self):
        accepted, payload, status = parse_ntrip_response(
            b"HTTP/1.1 401 Unauthorized\r\n\r\n"
        )
        self.assertFalse(accepted)
        self.assertEqual(payload, b"")
        self.assertEqual(status, "HTTP/1.1 401 Unauthorized")

    def test_gga_normalization_and_freshness(self):
        sentence = "$GNGGA,120000.00,2230.0000,N,11330.0000,E,1,12,0.8,10.0,M,0.0,M,,*00"
        self.assertEqual(normalize_gga_sentence(sentence), (sentence + "\r\n").encode())
        self.assertIsNone(normalize_gga_sentence("$GNRMC,invalid"))
        latest = LatestGga()
        self.assertTrue(latest.update(sentence, received_at=100.0))
        self.assertIsNotNone(latest.fresh(15.0, now=114.9))
        self.assertIsNone(latest.fresh(15.0, now=115.1))

    def test_config_requires_vehicle_only_credentials(self):
        env = {
            "DWC_RTK_CORRECTION_MODE": "ntrip_client",
            "DWC_RTK_NTRIP_HOST": "rtk.ntrip.qxwz.com",
            "DWC_RTK_NTRIP_PORT": "8002",
            "DWC_RTK_NTRIP_MOUNTPOINT": "AUTO",
            "DWC_RTK_NTRIP_USERNAME": "account",
            "DWC_RTK_NTRIP_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=True):
            config = NtripConfig.from_env()
        self.assertEqual(config.serial_device, "/dev/wheeltec_gnss")
        self.assertEqual(config.mountpoint, "AUTO")

    def test_status_file_never_contains_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "status.json"
            StatusWriter(str(path)).write({"connected": True, "bytesReceived": 123})
            content = path.read_text(encoding="utf-8")
            self.assertIn('"connected":true', content)
            self.assertNotIn("password", content.lower())
            self.assertNotIn("username", content.lower())


if __name__ == "__main__":
    unittest.main()
