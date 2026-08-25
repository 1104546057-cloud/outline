#!/usr/bin/env python3
"""Qianxun FindCM NTRIP client for the WHEELTEC G70 USB receiver.

The client receives RTCM3 corrections over the vehicle's existing network and
writes them to the already-open G70 USB tty without changing its termios state.
Credentials are read only from the process environment and are never logged.
"""

from __future__ import annotations

import base64
import errno
import json
import logging
import os
import select
import socket
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


log = logging.getLogger("ntrip_rtcm_client")


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value == "replace_me":
        raise ValueError("缺少必要环境变量: {}".format(name))
    return value


@dataclass(frozen=True)
class NtripConfig:
    host: str
    port: int
    mountpoint: str
    username: str
    password: str
    serial_device: str = "/dev/wheeltec_gnss"
    gga_topic: str = "/gps/nmea_sentence"
    gga_send_interval_sec: float = 5.0
    gga_stale_sec: float = 15.0
    connect_timeout_sec: float = 12.0
    status_file: str = "/tmp/devices_web_control_ntrip_status.json"

    @classmethod
    def from_env(cls) -> "NtripConfig":
        mode = os.environ.get("DWC_RTK_CORRECTION_MODE", "ntrip_client").strip()
        if mode != "ntrip_client":
            raise ValueError("DWC_RTK_CORRECTION_MODE 必须为 ntrip_client")
        host = _required_env("DWC_RTK_NTRIP_HOST")
        if any(char in host for char in "/\\\r\n\t "):
            raise ValueError("NTRIP 主机名格式无效")
        mountpoint = _required_env("DWC_RTK_NTRIP_MOUNTPOINT").strip("/")
        if not mountpoint or any(char in mountpoint for char in "\r\n\t "):
            raise ValueError("NTRIP 挂载点格式无效")
        port = int(_required_env("DWC_RTK_NTRIP_PORT"))
        if not 1 <= port <= 65535:
            raise ValueError("NTRIP 端口超出范围")
        serial_device = os.environ.get("DWC_RTK_SERIAL_DEVICE", "/dev/wheeltec_gnss").strip()
        if not serial_device.startswith("/dev/"):
            raise ValueError("G70 串口必须位于 /dev 下")
        return cls(
            host=host,
            port=port,
            mountpoint=mountpoint,
            username=_required_env("DWC_RTK_NTRIP_USERNAME"),
            password=_required_env("DWC_RTK_NTRIP_PASSWORD"),
            serial_device=serial_device,
            gga_topic=os.environ.get("DWC_RTK_NTRIP_GGA_TOPIC", "/gps/nmea_sentence").strip(),
            gga_send_interval_sec=float(os.environ.get("DWC_RTK_NTRIP_GGA_INTERVAL_SEC", "5")),
            gga_stale_sec=float(os.environ.get("DWC_RTK_NTRIP_GGA_STALE_SEC", "15")),
            connect_timeout_sec=float(os.environ.get("DWC_RTK_NTRIP_CONNECT_TIMEOUT_SEC", "12")),
            status_file=os.environ.get(
                "DWC_RTK_NTRIP_STATUS_FILE",
                "/tmp/devices_web_control_ntrip_status.json",
            ).strip(),
        )


def build_ntrip_request(config: NtripConfig) -> bytes:
    credentials = "{}:{}".format(config.username, config.password).encode("utf-8")
    authorization = base64.b64encode(credentials).decode("ascii")
    lines = [
        "GET /{} HTTP/1.0".format(config.mountpoint),
        "Host: {}:{}".format(config.host, config.port),
        "User-Agent: NTRIP DevicesWebControl/1.0",
        "Ntrip-Version: Ntrip/2.0",
        "Authorization: Basic {}".format(authorization),
        "Connection: close",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("ascii")


def parse_ntrip_response(buffer: bytes) -> tuple[bool, bytes, str]:
    """Parse an NTRIP response and return (accepted, payload, status_line)."""
    first_line_end = buffer.find(b"\r\n")
    if first_line_end < 0:
        return False, b"", "响应头不完整"
    status_line = buffer[:first_line_end].decode("ascii", "replace").strip()
    accepted = status_line == "ICY 200 OK" or (
        status_line.startswith("HTTP/") and " 200 " in "{} ".format(status_line)
    )
    if not accepted:
        return False, b"", status_line

    header_end = buffer.find(b"\r\n\r\n")
    if header_end >= 0:
        return True, buffer[header_end + 4 :], status_line
    if status_line == "ICY 200 OK":
        remainder = buffer[first_line_end + 2 :]
        rtcm_start = remainder.find(b"\xd3")
        if rtcm_start >= 0:
            return True, remainder[rtcm_start:], status_line
    return True, b"", status_line


def normalize_gga_sentence(sentence: str) -> Optional[bytes]:
    value = str(sentence or "").strip()
    if not (value.startswith("$GNGGA,") or value.startswith("$GPGGA,")):
        return None
    fields = value.split(",")
    if len(fields) < 7 or not fields[2] or not fields[4]:
        return None
    if any(char in value for char in "\r\n"):
        return None
    return (value + "\r\n").encode("ascii", "strict")


class LatestGga:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sentence: Optional[bytes] = None
        self._received_at = 0.0

    def update(self, sentence: str, received_at: Optional[float] = None) -> bool:
        normalized = normalize_gga_sentence(sentence)
        if normalized is None:
            return False
        with self._lock:
            self._sentence = normalized
            self._received_at = received_at if received_at is not None else time.time()
        return True

    def fresh(self, stale_sec: float, now: Optional[float] = None) -> Optional[bytes]:
        current = now if now is not None else time.time()
        with self._lock:
            if self._sentence is None or current - self._received_at > stale_sec:
                return None
            return self._sentence

    def age(self, now: Optional[float] = None) -> Optional[float]:
        current = now if now is not None else time.time()
        with self._lock:
            if not self._received_at:
                return None
            return max(0.0, current - self._received_at)


class StatusWriter:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def write(self, payload: dict) -> None:
        data = dict(payload)
        data["updatedAt"] = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".ntrip-status-",
            dir=str(self.path.parent),
            delete=False,
        )
        temp_path = Path(handle.name)
        try:
            with handle:
                json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(str(temp_path), 0o600)
            os.replace(str(temp_path), str(self.path))
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


class NtripRtcmClient:
    def __init__(self, config: NtripConfig, latest_gga: LatestGga) -> None:
        self.config = config
        self.latest_gga = latest_gga
        self.status = StatusWriter(config.status_file)
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.bytes_received = 0
        self.last_correction_at = 0.0

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="ntrip-rtcm", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def join(self, timeout: float = 5.0) -> None:
        if self.thread is not None:
            self.thread.join(timeout)

    def _status(self, connected: bool, error: str = "") -> None:
        now = time.time()
        correction_age = now - self.last_correction_at if self.last_correction_at else None
        gga_age = self.latest_gga.age(now)
        self.status.write(
            {
                "connected": connected,
                "bytesReceived": self.bytes_received,
                "lastCorrectionAgeSec": correction_age,
                "ggaAgeSec": gga_age,
                "ggaFresh": gga_age is not None and gga_age <= self.config.gga_stale_sec,
                "lastError": error[:240],
                "serialDevice": self.config.serial_device,
                "mountpoint": self.config.mountpoint,
            }
        )

    @staticmethod
    def _write_all(fd: int, data: bytes) -> None:
        view = memoryview(data)
        while view:
            try:
                written = os.write(fd, view)
                view = view[written:]
            except BlockingIOError:
                select.select([], [fd], [], 1.0)

    @staticmethod
    def _read_handshake(sock: socket.socket) -> bytes:
        response = b""
        while len(response) < 16384:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
            accepted, payload, status_line = parse_ntrip_response(response)
            if not accepted and status_line != "响应头不完整":
                raise ConnectionError("NTRIP 连接被拒绝: {}".format(status_line))
            if accepted and (b"\r\n\r\n" in response or payload.startswith(b"\xd3")):
                return payload
            if accepted and response == b"ICY 200 OK\r\n":
                return b""
        accepted, payload, status_line = parse_ntrip_response(response)
        if not accepted:
            raise ConnectionError("NTRIP 握手失败: {}".format(status_line))
        return payload

    def _session(self) -> None:
        serial_fd = os.open(
            self.config.serial_device,
            os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK,
        )
        try:
            with socket.create_connection(
                (self.config.host, self.config.port),
                timeout=self.config.connect_timeout_sec,
            ) as sock:
                sock.settimeout(self.config.connect_timeout_sec)
                sock.sendall(build_ntrip_request(self.config))
                gga = self.latest_gga.fresh(self.config.gga_stale_sec)
                if gga is not None:
                    sock.sendall(gga)
                initial = self._read_handshake(sock)
                sock.setblocking(False)
                if initial:
                    self._write_all(serial_fd, initial)
                    self.bytes_received += len(initial)
                    self.last_correction_at = time.time()
                self._status(True)
                last_gga_sent = 0.0
                last_status = 0.0
                while not self.stop_event.is_set():
                    now = time.time()
                    if now - last_gga_sent >= self.config.gga_send_interval_sec:
                        gga = self.latest_gga.fresh(self.config.gga_stale_sec, now)
                        if gga is not None:
                            sock.sendall(gga)
                        last_gga_sent = now
                    readable, _, exceptional = select.select([sock], [], [sock], 1.0)
                    if exceptional:
                        raise ConnectionError("NTRIP 连接异常")
                    if readable:
                        try:
                            chunk = sock.recv(8192)
                        except BlockingIOError:
                            chunk = None
                        if chunk == b"":
                            raise ConnectionError("NTRIP 服务端已断开")
                        if chunk:
                            self._write_all(serial_fd, chunk)
                            self.bytes_received += len(chunk)
                            self.last_correction_at = time.time()
                    if now - last_status >= 2.0:
                        self._status(True)
                        last_status = now
        finally:
            os.close(serial_fd)

    def _run(self) -> None:
        delay = 1.0
        while not self.stop_event.is_set():
            try:
                self._session()
                delay = 1.0
            except Exception as exc:
                message = str(exc) or exc.__class__.__name__
                if isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.ENOENT):
                    message = "无法访问 G70 串口: {}".format(exc.strerror or exc.errno)
                log.warning("NTRIP/RTCM 会话中断: %s", message)
                self._status(False, message)
            if self.stop_event.wait(delay):
                break
            delay = min(30.0, delay * 2.0)
        self._status(False, "服务已停止")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    config = NtripConfig.from_env()
    import rospy
    from nmea_msgs.msg import Sentence

    latest_gga = LatestGga()
    client = NtripRtcmClient(config, latest_gga)
    rospy.init_node("dwc_ntrip_rtcm_client", anonymous=False)

    def on_sentence(message: Sentence) -> None:
        latest_gga.update(message.sentence)

    rospy.Subscriber(config.gga_topic, Sentence, on_sentence, queue_size=10)
    rospy.on_shutdown(client.stop)
    client.start()
    log.info(
        "NTRIP/RTCM 客户端已启动: caster=%s:%s mount=%s serial=%s gga_topic=%s",
        config.host,
        config.port,
        config.mountpoint,
        config.serial_device,
        config.gga_topic,
    )
    try:
        rospy.spin()
    finally:
        client.stop()
        client.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
