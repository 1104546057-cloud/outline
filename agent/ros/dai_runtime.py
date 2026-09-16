"""ZeroTier dai YOLO runtime helpers. Keep this file rospy-free for unit tests."""

from __future__ import annotations

import threading


def parse_systemctl_show(output):
    values = {}
    for line in (output or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip()
    try:
        main_pid = int(values.get("MainPID") or 0)
    except ValueError:
        main_pid = 0
    return {
        "main_pid": max(0, main_pid),
        "active_state": values.get("ActiveState") or "unknown",
        "sub_state": values.get("SubState") or "unknown",
        "unit_file_state": values.get("UnitFileState") or "unknown",
    }


def gpu_ready_from_payload(service, detector):
    """Ready only when systemd is up and /status reports TensorRT GPU.

    dai puts backend/target under detection, not the top-level object.
    """
    service = service or {}
    detector = detector or {}
    detection = detector.get("detection") if isinstance(detector.get("detection"), dict) else {}
    backend = str(detector.get("backend") or detection.get("backend") or "").lower()
    target = str(detector.get("target") or detection.get("target") or "").lower()
    active = bool(service.get("active") or service.get("active_state") == "active")
    try:
        pid = int(service.get("main_pid") or service.get("MainPID") or 0)
    except (TypeError, ValueError):
        pid = 0
    return bool(
        active
        and pid > 0
        and bool(detector.get("online", True))
        and backend == "tensorrt"
        and target == "gpu"
    )


def gpu_released_from_payload(service):
    service = service or {}
    try:
        pid = int(service.get("main_pid") or service.get("MainPID") or 0)
    except (TypeError, ValueError):
        pid = 0
    active = bool(service.get("active") or service.get("active_state") == "active")
    return bool(not active and pid == 0)


class DaiServiceGuard:
    """Serialize start/stop so repeated UI clicks cannot spawn extra processes."""

    def __init__(self):
        self.lock = threading.Lock()
        self.pid = 0
        self.active = False
        self.start_count = 0
        self.stop_count = 0
        self.fail_next_start = False

    def start(self):
        with self.lock:
            if self.fail_next_start:
                self.fail_next_start = False
                raise RuntimeError("dai start failed")
            self.start_count += 1
            if not self.active:
                self.pid = self.pid + 1 if self.pid else 1000
                self.active = True
            return {"pid": self.pid, "state": "active", "gpu_released": False, "video_preserved": True}

    def stop(self):
        with self.lock:
            self.stop_count += 1
            self.active = False
            self.pid = 0
            return {"pid": 0, "state": "inactive", "gpu_released": True, "video_preserved": True}

    def snapshot(self):
        return {
            "pid": self.pid,
            "state": "active" if self.active else "inactive",
            "gpu_released": gpu_released_from_payload(
                {"active": self.active, "main_pid": self.pid, "active_state": "active" if self.active else "inactive"}
            ),
        }


def apply_inference_transition(enabled, service, enable_sender, disable_sender):
    """Start dai first, then sender. Start failure rolls back to stopped."""
    if enabled:
        try:
            runtime = service.start()
        except Exception:
            try:
                disable_sender()
            except Exception:
                pass
            try:
                service.stop()
            except Exception:
                pass
            raise
        try:
            sender = enable_sender()
        except Exception:
            try:
                disable_sender()
            except Exception:
                pass
            service.stop()
            raise
        runtime["sender"] = sender
        runtime["enabled"] = True
        runtime["video_preserved"] = True
        return runtime

    sender = {}
    sender_error = ""
    try:
        sender = disable_sender()
    except Exception as exc:
        sender_error = str(exc)
    runtime = service.stop()
    runtime["sender"] = sender
    runtime["enabled"] = False
    runtime["video_preserved"] = True
    if sender_error:
        runtime["sender_error"] = sender_error
    return runtime
