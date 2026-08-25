import os
import pathlib
import select
import socket
import tempfile
import threading
import time
import unittest


ROS_DIR = pathlib.Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROS_DIR))

from ntrip_rtcm_client import LatestGga, NtripConfig, NtripRtcmClient


@unittest.skipUnless(os.name == "posix", "PTY integration test requires Linux")
class NtripRtcmLinuxIntegrationTests(unittest.TestCase):
    def test_receives_rtcm_and_writes_to_existing_tty(self):
        import pty
        import tty

        master_fd, slave_fd = pty.openpty()
        tty.setraw(slave_fd)
        slave_path = os.ttyname(slave_fd)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        host, port = listener.getsockname()
        received = bytearray()
        correction = b"\xd3\x00\x03abc"

        def caster():
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(3.0)
                while b"\r\n\r\n" not in received:
                    received.extend(connection.recv(4096))
                connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: gnss/data\r\n\r\n" + correction)
                deadline = time.time() + 2.0
                while time.time() < deadline and b"$GNGGA," not in received:
                    try:
                        received.extend(connection.recv(4096))
                    except socket.timeout:
                        break

        server_thread = threading.Thread(target=caster, daemon=True)
        server_thread.start()
        gga = LatestGga()
        gga.update("$GNGGA,120000.00,2230.0000,N,11330.0000,E,1,12,0.8,10.0,M,0.0,M,,*00")
        with tempfile.TemporaryDirectory() as directory:
            config = NtripConfig(
                host=host,
                port=port,
                mountpoint="AUTO",
                username="vehicle-user",
                password="vehicle-password",
                serial_device=slave_path,
                gga_send_interval_sec=0.1,
                status_file=str(pathlib.Path(directory) / "status.json"),
            )
            client = NtripRtcmClient(config, gga)
            client.start()
            readable, _, _ = select.select([master_fd], [], [], 5.0)
            self.assertTrue(readable, "RTCM was not written to the G70 tty")
            self.assertEqual(os.read(master_fd, len(correction)), correction)
            client.stop()
            client.join()

        server_thread.join(3.0)
        listener.close()
        os.close(master_fd)
        os.close(slave_fd)
        self.assertIn(b"GET /AUTO HTTP/1.0", received)
        self.assertIn(b"Authorization: Basic ", received)
        self.assertIn(b"$GNGGA,", received)


if __name__ == "__main__":
    unittest.main()
