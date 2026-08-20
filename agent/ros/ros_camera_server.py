#!/usr/bin/env python3
"""Expose Gemini camera frames and a rendered ROS lidar view as HTTP streams."""

import argparse
import json
import math
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
import rospy
from cv_bridge import CvBridge
from sensor_msgs.msg import CompressedImage, Image, PointCloud2, PointField


BOUNDARY = b"boundarydonotcross"
DEPTH_COLORMAP = getattr(cv2, "COLORMAP_TURBO", cv2.COLORMAP_JET)
LIDAR_COLORMAP = getattr(cv2, "COLORMAP_TURBO", cv2.COLORMAP_JET)
POINT_FIELD_DTYPES = {
    PointField.INT8: "i1",
    PointField.UINT8: "u1",
    PointField.INT16: "i2",
    PointField.UINT16: "u2",
    PointField.INT32: "i4",
    PointField.UINT32: "u4",
    PointField.FLOAT32: "f4",
    PointField.FLOAT64: "f8",
}


class FrameStore:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._frames: Dict[str, Optional[bytes]] = {
            "color": None,
            "depth": None,
            "lidar": None,
        }
        self._updated_at: Dict[str, Optional[float]] = {
            "color": None,
            "depth": None,
            "lidar": None,
        }
        self._clients = {"color": 0, "depth": 0, "lidar": 0}
        self._versions = {"color": 0, "depth": 0, "lidar": 0}

    def update(self, kind: str, jpeg: bytes) -> None:
        with self._condition:
            self._frames[kind] = jpeg
            self._updated_at[kind] = time.time()
            self._versions[kind] += 1
            self._condition.notify_all()

    def get(self, kind: str) -> Optional[bytes]:
        with self._condition:
            return self._frames.get(kind)

    def add_client(self, kind: str) -> None:
        with self._condition:
            if kind != "color" and self._clients[kind] == 0:
                self._frames[kind] = None
                self._updated_at[kind] = None
            self._clients[kind] += 1

    def remove_client(self, kind: str) -> None:
        with self._condition:
            self._clients[kind] = max(0, self._clients[kind] - 1)

    def has_clients(self, kind: str) -> bool:
        with self._condition:
            return self._clients.get(kind, 0) > 0

    def wait_for(self, kind: str, timeout: float) -> Optional[bytes]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._frames.get(kind) is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return self._frames[kind]

    def wait_for_update(self, kind: str, version: int, timeout: float) -> Tuple[Optional[bytes], int]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._versions[kind] == version:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None, version
                self._condition.wait(remaining)
            return self._frames[kind], self._versions[kind]

    def status(self) -> Dict[str, object]:
        now = time.time()
        with self._condition:
            return {
                kind: {
                    "ready": frame is not None,
                    "age": None if self._updated_at[kind] is None else round(now - self._updated_at[kind], 2),
                    "clients": self._clients[kind],
                }
                for kind, frame in self._frames.items()
            }


class DepthRenderer:
    def __init__(
        self,
        store: FrameStore,
        jpeg_quality: int,
        max_fps: float,
        depth_near_m: float,
        depth_far_m: float,
    ) -> None:
        self.store = store
        self.bridge = CvBridge()
        self.jpeg_quality = jpeg_quality
        self.frame_interval = 1.0 / max_fps
        self.depth_near_m = depth_near_m
        self.depth_far_m = depth_far_m
        self._render_lock = threading.Lock()
        self._last_render = 0.0

    def _should_render(self) -> bool:
        now = time.monotonic()
        with self._render_lock:
            if now - self._last_render < self.frame_interval:
                return False
            self._last_render = now
            return True

    def _encode(self, image: np.ndarray) -> Optional[bytes]:
        ok, buffer = cv2.imencode(
            ".jpg",
            image,
            [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
        )
        return buffer.tobytes() if ok else None

    def on_depth(self, msg: Image) -> None:
        if not self.store.has_clients("depth") or not self._should_render():
            return
        try:
            raw = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
            depth = np.asarray(raw, dtype=np.float32)
            if msg.encoding == "16UC1":
                depth *= 0.001

            valid = np.isfinite(depth) & (depth > 0.01)
            safe_depth = np.where(valid, depth, self.depth_far_m)
            clipped = np.clip(safe_depth, self.depth_near_m, self.depth_far_m)
            scaled = (
                (clipped - self.depth_near_m)
                / (self.depth_far_m - self.depth_near_m)
                * 255.0
            ).astype(np.uint8)
            colored = cv2.applyColorMap(255 - scaled, DEPTH_COLORMAP)
            colored[~valid] = 0

            jpeg = self._encode(colored)
            if jpeg:
                self.store.update("depth", jpeg)
        except Exception as exc:
            rospy.logerr_throttle(10, "Depth image conversion failed: %s", exc)


class LidarRenderer:
    def __init__(
        self,
        store: FrameStore,
        jpeg_quality: int,
        max_fps: float,
        width: int,
        height: int,
        range_m: float,
        min_height_m: float,
        max_height_m: float,
    ) -> None:
        self.store = store
        self.jpeg_quality = jpeg_quality
        self.frame_interval = 1.0 / max_fps
        self.width = width
        self.height = height
        self.range_m = range_m
        self.min_height_m = min_height_m
        self.max_height_m = max_height_m
        self._render_lock = threading.Lock()
        self._last_render = 0.0
        color_values = np.linspace(12, 244, 16, dtype=np.uint8).reshape(-1, 1)
        self._ring_colors = cv2.applyColorMap(color_values, LIDAR_COLORMAP)[:, 0, :]

    def _should_render(self) -> bool:
        now = time.monotonic()
        with self._render_lock:
            if now - self._last_render < self.frame_interval:
                return False
            self._last_render = now
            return True

    @staticmethod
    def _as_array(msg: PointCloud2) -> np.ndarray:
        byte_order = ">" if msg.is_bigendian else "<"
        names = []
        formats = []
        offsets = []
        for field in msg.fields:
            dtype_code = POINT_FIELD_DTYPES.get(field.datatype)
            if dtype_code is None:
                continue
            field_dtype = np.dtype(byte_order + dtype_code)
            if field.count > 1:
                field_dtype = np.dtype((field_dtype, field.count))
            names.append(field.name)
            formats.append(field_dtype)
            offsets.append(field.offset)

        dtype = np.dtype({
            "names": names,
            "formats": formats,
            "offsets": offsets,
            "itemsize": msg.point_step,
        })
        expected_row_step = msg.width * msg.point_step
        if msg.height <= 1 or msg.row_step == expected_row_step:
            return np.frombuffer(msg.data, dtype=dtype, count=msg.width * msg.height)

        rows = []
        data = memoryview(msg.data)
        for row_index in range(msg.height):
            start = row_index * msg.row_step
            rows.append(np.frombuffer(data[start:start + expected_row_step], dtype=dtype, count=msg.width))
        return np.concatenate(rows)

    def _draw_grid(self, image: np.ndarray, center_x: int, center_y: int, scale: float, effective_range: float = None) -> None:
        if effective_range is None:
            effective_range = self.range_m
        image[:] = (10, 15, 22)
        grid_color = (46, 55, 64)
        axis_color = (72, 91, 104)
        # Choose a nice grid step based on the effective range
        if effective_range >= 20.0:
            step_m = 5.0
        elif effective_range >= 10.0:
            step_m = 3.0
        elif effective_range >= 5.0:
            step_m = 2.0
        else:
            step_m = 1.0
        distance = step_m
        while distance <= effective_range + 0.001:
            radius = int(round(distance * scale))
            cv2.circle(image, (center_x, center_y), radius, grid_color, 1, cv2.LINE_AA)
            cv2.putText(
                image,
                f"{distance:g}m",
                (center_x + 4, center_y - radius + 12),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.32,
                axis_color,
                1,
                cv2.LINE_AA,
            )
            distance += step_m
        cv2.line(image, (center_x, 30), (center_x, self.height - 24), grid_color, 1, cv2.LINE_AA)
        cv2.line(image, (24, center_y), (self.width - 24, center_y), grid_color, 1, cv2.LINE_AA)

    def _draw_robot(self, image: np.ndarray, center_x: int, center_y: int) -> None:
        body = np.array([
            [center_x, center_y - 12],
            [center_x - 8, center_y + 10],
            [center_x + 8, center_y + 10],
        ], dtype=np.int32)
        cv2.fillConvexPoly(image, body, (23, 67, 76), cv2.LINE_AA)
        cv2.polylines(image, [body], True, (88, 225, 233), 1, cv2.LINE_AA)
        cv2.line(image, (center_x, center_y - 12), (center_x, center_y - 22), (88, 225, 233), 1, cv2.LINE_AA)

    def _draw_overlay(self, image: np.ndarray, point_count: int, effective_range: float = None) -> None:
        if effective_range is None:
            effective_range = self.range_m
        cv2.putText(image, "C16 16-LAYER POINT CLOUD", (14, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (105, 223, 238), 1, cv2.LINE_AA)
        cv2.putText(
            image,
            f"TOP VIEW  RANGE {effective_range:g}m  POINTS {point_count}",
            (14, self.height - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.34,
            (104, 133, 145),
            1,
            cv2.LINE_AA,
        )
        legend_x = self.width - 45
        legend_y = 38
        cv2.putText(image, "RING", (legend_x - 2, legend_y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (115, 144, 157), 1, cv2.LINE_AA)
        for ring, color in enumerate(self._ring_colors):
            top = legend_y + ring * 8
            cv2.rectangle(image, (legend_x, top), (legend_x + 12, top + 6), tuple(int(value) for value in color), -1)
            cv2.putText(image, f"{ring:02d}", (legend_x + 16, top + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.24, (113, 139, 151), 1, cv2.LINE_AA)

    @staticmethod
    def _snap_range(value: float) -> float:
        """Round *value* up to a 'nice' number for grid labels (e.g. 2, 3, 5, 8, 10, 15, 20 …)."""
        nice_steps = [1, 2, 3, 5, 8, 10, 15, 20, 30, 50, 80, 100]
        for step in nice_steps:
            if step >= value:
                return float(step)
        return float(math.ceil(value))

    def on_point_cloud(self, msg: PointCloud2) -> None:
        if not self.store.has_clients("lidar") or not self._should_render():
            return
        try:
            points = self._as_array(msg)
            if not {"x", "y", "z"}.issubset(points.dtype.names or ()):
                raise ValueError("point cloud must contain x, y and z fields")

            x = points["x"].astype(np.float32, copy=False)
            y = points["y"].astype(np.float32, copy=False)
            z = points["z"].astype(np.float32, copy=False)
            horizontal_range = np.hypot(x, y)
            valid = (
                np.isfinite(x)
                & np.isfinite(y)
                & np.isfinite(z)
                & (horizontal_range >= 0.2)
                & (horizontal_range <= self.range_m)
                & (z >= self.min_height_m)
                & (z <= self.max_height_m)
            )
            x = x[valid]
            y = y[valid]
            z = z[valid]

            # --- adaptive range: fit display to actual data extent ---
            min_range = 3.0  # never zoom in closer than 3 m
            if len(x) > 0:
                hr = np.hypot(x, y)
                data_max = float(np.percentile(hr, 95))  # 95th percentile
                effective_range = self._snap_range(max(min_range, data_max * 1.25))
                effective_range = min(effective_range, self.range_m)
            else:
                effective_range = self.range_m

            margin_x = 58
            margin_y = 34
            center_x = self.width // 2
            center_y = self.height // 2
            scale = min(
                (self.width - margin_x * 2) / (2.0 * effective_range),
                (self.height - margin_y * 2) / (2.0 * effective_range),
            )
            pixel_x = np.rint(center_x - y * scale).astype(np.int32)
            pixel_y = np.rint(center_y - x * scale).astype(np.int32)

            if "ring" in (points.dtype.names or ()):
                rings = points["ring"][valid].astype(np.int32, copy=False) % 16
                colors = self._ring_colors[rings]
            else:
                height_ratio = np.clip(
                    (z - self.min_height_m) / (self.max_height_m - self.min_height_m),
                    0.0,
                    1.0,
                )
                height_values = np.rint(height_ratio * 255.0).astype(np.uint8).reshape(-1, 1)
                colors = cv2.applyColorMap(height_values, LIDAR_COLORMAP)[:, 0, :]

            canvas = np.empty((self.height, self.width, 3), dtype=np.uint8)
            # pass effective_range so grid rings match the adaptive zoom
            self._draw_grid(canvas, center_x, center_y, scale, effective_range)
            point_layer = np.zeros_like(canvas)
            for offset_x, offset_y in ((0, 0), (1, 0), (0, 1), (1, 1)):
                draw_x = pixel_x + offset_x
                draw_y = pixel_y + offset_y
                inside = (
                    (draw_x >= 0)
                    & (draw_x < self.width)
                    & (draw_y >= 0)
                    & (draw_y < self.height)
                )
                point_layer[draw_y[inside], draw_x[inside]] = colors[inside]

            glow = cv2.GaussianBlur(point_layer, (0, 0), 1.2)
            canvas = cv2.addWeighted(canvas, 1.0, glow, 0.45, 0.0)
            point_mask = np.any(point_layer != 0, axis=2)
            canvas[point_mask] = point_layer[point_mask]
            self._draw_robot(canvas, center_x, center_y)
            self._draw_overlay(canvas, len(x), effective_range)

            ok, buffer = cv2.imencode(
                ".jpg",
                canvas,
                [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
            )
            if ok:
                self.store.update("lidar", buffer.tobytes())
        except Exception as exc:
            rospy.logerr_throttle(10, "Lidar point cloud rendering failed: %s", exc)


class NativeMjpegCapture:
    def __init__(
        self,
        store: FrameStore,
        publisher: rospy.Publisher,
        device: str,
        width: int,
        height: int,
        fps: int,
        frame_id: str,
    ) -> None:
        self.store = store
        self.publisher = publisher
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.frame_id = frame_id
        self.stop_event = threading.Event()
        self.process: Optional[subprocess.Popen] = None
        self.capture_thread: Optional[threading.Thread] = None
        self.stderr_thread: Optional[threading.Thread] = None
        self.watchdog_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        gst_launch = shutil.which("gst-launch-1.0")
        if gst_launch is None:
            raise RuntimeError("gst-launch-1.0 is not installed")

        command = [
            gst_launch,
            "-q",
            "v4l2src",
            f"device={self.device}",
            "io-mode=mmap",
            "!",
            f"image/jpeg,width={self.width},height={self.height},framerate={self.fps}/1",
            "!",
            "fdsink",
            "fd=1",
            "sync=false",
        ]
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.capture_thread = threading.Thread(target=self._capture_loop, name="native-mjpeg", daemon=True)
        self.stderr_thread = threading.Thread(target=self._stderr_loop, name="native-mjpeg-log", daemon=True)
        self.watchdog_thread = threading.Thread(target=self._watchdog_loop, name="native-mjpeg-watchdog", daemon=True)
        self.capture_thread.start()
        self.stderr_thread.start()
        self.watchdog_thread.start()

    def stop(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        current_thread = threading.current_thread()
        if self.capture_thread is not None and self.capture_thread is not current_thread:
            self.capture_thread.join(timeout=2.0)
        if self.stderr_thread is not None and self.stderr_thread is not current_thread:
            self.stderr_thread.join(timeout=2.0)
        if self.watchdog_thread is not None and self.watchdog_thread is not current_thread:
            self.watchdog_thread.join(timeout=2.0)

    def _capture_loop(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return

        buffer = bytearray()
        while not self.stop_event.is_set():
            chunk = process.stdout.read(65536)
            if not chunk:
                break
            buffer.extend(chunk)

            while True:
                start = buffer.find(b"\xff\xd8")
                if start < 0:
                    if len(buffer) > 2 * 1024 * 1024:
                        del buffer[:-2]
                    break
                end = buffer.find(b"\xff\xd9", start + 2)
                if end < 0:
                    if start > 0:
                        del buffer[:start]
                    break

                jpeg = bytes(buffer[start:end + 2])
                del buffer[:end + 2]
                self.store.update("color", jpeg)
                if self.publisher.get_num_connections() > 0:
                    message = CompressedImage()
                    message.header.stamp = rospy.Time.now()
                    message.header.frame_id = self.frame_id
                    message.format = "jpeg"
                    message.data = jpeg
                    self.publisher.publish(message)

        if not self.stop_event.is_set():
            return_code = process.poll()
            rospy.logerr("Native MJPEG capture stopped unexpectedly (code=%s)", return_code)
            rospy.signal_shutdown("native MJPEG capture stopped")

    def _stderr_loop(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        for raw_line in iter(process.stderr.readline, b""):
            if self.stop_event.is_set():
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                rospy.logwarn("GStreamer camera: %s", line)

    def _watchdog_loop(self) -> None:
        version = 0
        while not self.stop_event.is_set():
            _, next_version = self.store.wait_for_update("color", version, timeout=10.0)
            if self.stop_event.is_set():
                return
            if next_version != version:
                version = next_version
                continue

            process = self.process
            if process is None or process.poll() is not None:
                return
            rospy.logerr("Native MJPEG capture produced no frames for 10 seconds; restarting media service")
            process.terminate()
            rospy.signal_shutdown("native MJPEG capture stalled")
            return


class CameraHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, store: FrameStore, stream_fps: float) -> None:
        super().__init__(address, handler)
        self.store = store
        self.stream_interval = 1.0 / stream_fps
        self.stop_event = threading.Event()


class CameraRequestHandler(BaseHTTPRequestHandler):
    server_version = "DevicesWebControlROSSensors/1.1"

    def log_message(self, format_string: str, *args) -> None:
        rospy.logdebug(format_string, *args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/health":
            body = json.dumps(self.server.store.status()).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8")
            return

        kind = self._resolve_kind(parsed.path, query)
        if kind is None:
            self.send_error(404, "unknown sensor view")
            return

        action = query.get("action", [""])[-1].lower()
        if parsed.path.startswith("/stream/") or action == "stream":
            self._serve_stream(kind)
            return
        if parsed.path.startswith("/snapshot/") or action == "snapshot":
            self._serve_snapshot(kind)
            return

        self.send_error(404, "unknown camera action")

    @staticmethod
    def _resolve_kind(path: str, query: Dict[str, list]) -> Optional[str]:
        if path in ("/stream/rgb", "/stream/color", "/snapshot/rgb", "/snapshot/color"):
            return "color"
        if path in ("/stream/depth", "/snapshot/depth"):
            return "depth"
        if path in ("/stream/lidar", "/snapshot/lidar"):
            return "lidar"
        if path != "/":
            return None

        view = query.get("view", ["color"])[-1].lower()
        if view in ("color", "rgb", "camera", "main"):
            return "color"
        if view == "depth":
            return "depth"
        if view in ("lidar", "radar", "pointcloud"):
            return "lidar"
        return None

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _wait_for_frame(self, kind: str) -> Optional[bytes]:
        frame = self.server.store.get(kind)
        if frame is not None:
            return frame
        return self.server.store.wait_for(kind, timeout=10.0)

    def _serve_snapshot(self, kind: str) -> None:
        self.server.store.add_client(kind)
        try:
            frame = self._wait_for_frame(kind)
            if frame is None:
                self.send_error(503, "sensor source has no frames")
                return
            self._send_bytes(frame, "image/jpeg")
        finally:
            self.server.store.remove_client(kind)

    def _serve_stream(self, kind: str) -> None:
        self.server.store.add_client(kind)
        try:
            if self._wait_for_frame(kind) is None:
                self.send_error(503, "sensor source has no frames")
                return

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "multipart/x-mixed-replace; boundary=boundarydonotcross",
            )
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            version = -1
            while not self.server.stop_event.is_set() and not rospy.is_shutdown():
                frame, version = self.server.store.wait_for_update(kind, version, timeout=1.0)
                if frame is None:
                    continue
                self.wfile.write(b"--" + BOUNDARY + b"\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                self.server.stop_event.wait(self.server.stream_interval)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        finally:
            self.server.store.remove_client(kind)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gemini camera and C16 lidar HTTP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--camera-device", default="/dev/Astra_Gemini")
    parser.add_argument("--camera-width", type=int, default=640)
    parser.add_argument("--camera-height", type=int, default=480)
    parser.add_argument("--camera-fps", type=int, default=30)
    parser.add_argument("--camera-frame-id", default="camera_color_optical_frame")
    parser.add_argument("--rgb-compressed-topic", default="/camera/rgb/image_raw/compressed")
    parser.add_argument("--depth-topic", default="/camera/depth/image_raw")
    parser.add_argument("--jpeg-quality", type=int, default=82)
    parser.add_argument("--depth-max-fps", type=float, default=30.0)
    parser.add_argument("--stream-fps", type=float, default=30.0)
    parser.add_argument("--depth-near-m", type=float, default=0.3)
    parser.add_argument("--depth-far-m", type=float, default=4.0)
    parser.add_argument("--lidar-topic", default="/point_cloud_raw")
    parser.add_argument("--lidar-max-fps", type=float, default=10.0)
    parser.add_argument("--lidar-width", type=int, default=640)
    parser.add_argument("--lidar-height", type=int, default=480)
    parser.add_argument("--lidar-range-m", type=float, default=20.0)
    parser.add_argument("--lidar-min-height-m", type=float, default=-2.5)
    parser.add_argument("--lidar-max-height-m", type=float, default=3.0)
    return parser.parse_args(rospy.myargv(argv=sys.argv)[1:])


def validate_args(args: argparse.Namespace) -> None:
    if not 1 <= args.jpeg_quality <= 100:
        raise ValueError("jpeg-quality must be between 1 and 100")
    if args.camera_width <= 0 or args.camera_height <= 0 or args.camera_fps <= 0:
        raise ValueError("camera dimensions and fps must be greater than zero")
    if not math.isfinite(args.depth_max_fps) or args.depth_max_fps <= 0:
        raise ValueError("depth-max-fps must be greater than zero")
    if not math.isfinite(args.stream_fps) or args.stream_fps <= 0:
        raise ValueError("stream-fps must be greater than zero")
    if args.depth_near_m <= 0 or args.depth_far_m <= args.depth_near_m:
        raise ValueError("depth range must satisfy 0 < near < far")
    if not math.isfinite(args.lidar_max_fps) or args.lidar_max_fps <= 0:
        raise ValueError("lidar-max-fps must be greater than zero")
    if args.lidar_width <= 0 or args.lidar_height <= 0:
        raise ValueError("lidar dimensions must be greater than zero")
    if not math.isfinite(args.lidar_range_m) or args.lidar_range_m <= 0:
        raise ValueError("lidar-range-m must be greater than zero")
    if args.lidar_max_height_m <= args.lidar_min_height_m:
        raise ValueError("lidar height range must satisfy min < max")


def main() -> None:
    args = parse_args()
    validate_args(args)
    rospy.init_node("devices_webcontrol_camera_server", anonymous=False)

    store = FrameStore()
    depth_renderer = DepthRenderer(
        store=store,
        jpeg_quality=args.jpeg_quality,
        max_fps=args.depth_max_fps,
        depth_near_m=args.depth_near_m,
        depth_far_m=args.depth_far_m,
    )
    lidar_renderer = LidarRenderer(
        store=store,
        jpeg_quality=args.jpeg_quality,
        max_fps=args.lidar_max_fps,
        width=args.lidar_width,
        height=args.lidar_height,
        range_m=args.lidar_range_m,
        min_height_m=args.lidar_min_height_m,
        max_height_m=args.lidar_max_height_m,
    )
    rospy.Subscriber(args.depth_topic, Image, depth_renderer.on_depth, queue_size=1, buff_size=2**24)
    rospy.Subscriber(
        args.lidar_topic,
        PointCloud2,
        lidar_renderer.on_point_cloud,
        queue_size=1,
        buff_size=8 * 1024 * 1024,
    )
    compressed_publisher = rospy.Publisher(
        args.rgb_compressed_topic,
        CompressedImage,
        queue_size=1,
    )
    capture = NativeMjpegCapture(
        store=store,
        publisher=compressed_publisher,
        device=args.camera_device,
        width=args.camera_width,
        height=args.camera_height,
        fps=args.camera_fps,
        frame_id=args.camera_frame_id,
    )

    server = CameraHTTPServer(
        (args.host, args.port),
        CameraRequestHandler,
        store=store,
        stream_fps=args.stream_fps,
    )
    server_thread = threading.Thread(target=server.serve_forever, name="camera-http", daemon=True)
    server_thread.start()

    def shutdown() -> None:
        server.stop_event.set()
        server.shutdown()
        capture.stop()

    rospy.on_shutdown(shutdown)
    try:
        capture.start()
    except Exception:
        capture.stop()
        server.stop_event.set()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2.0)
        raise
    rospy.loginfo(
        "Sensor server listening on http://%s:%s (device=%s compressed=%s depth=%s lidar=%s)",
        args.host,
        args.port,
        args.camera_device,
        args.rgb_compressed_topic,
        args.depth_topic,
        args.lidar_topic,
    )
    try:
        rospy.spin()
    finally:
        shutdown()
        server.server_close()
        server_thread.join(timeout=2.0)


if __name__ == "__main__":
    main()
