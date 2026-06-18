"""
摄像头视频流代理路由

提供 MJPEG 视频流代理、快照获取和视频录制接口。
"""

import time
import asyncio
import queue
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import imageio_ffmpeg
from fastapi import APIRouter, HTTPException, Depends, Response
from sqlalchemy.orm import Session

from database import get_db
from models import User, Device
from auth import get_current_user
from agent_gateway import MediaFrame, agent_gateway
from config import CAMERA_RECORD_FINALIZE_TIMEOUT_SECONDS

router = APIRouter(prefix="/api/devices", tags=["摄像头"])

# ===== 录制状态管理 =====
# 格式: { device_id: { "task": asyncio.Task, "control": _RecordingControl, "start_time": datetime, "filename": str } }
_recording_sessions: dict[int, dict] = {}

# 录制视频保存目录（相对于 backend 目录的 ../data/camera_videos）
CAMERA_VIDEOS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "camera_videos"
CAMERA_RECORDING_TEMP_DIR = CAMERA_VIDEOS_DIR / ".recording"

# 快照保存目录（相对于 backend 目录的 ../data/camera_snapshots）
CAMERA_SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "camera_snapshots"


@dataclass
class _RecordingControl:
    """在线程之间传递精确的停止时间。"""

    stopped_at: float | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)

    def stop(self) -> None:
        self.stopped_at = time.monotonic()
        self.stop_event.set()


def _resolve_ffmpeg_binary() -> str | None:
    """通过 imageio-ffmpeg 获取其管理的 FFmpeg 可执行文件。"""
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except RuntimeError:
        return None


@router.get("/{device_id}/camera/stream")
async def proxy_camera_stream(
    device_id: int,
    view: Literal["color", "depth", "lidar"] = "color",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    代理转发设备 ROS 相机服务的 MJPEG 视频流（需登录）

    view=color 为 Gemini 彩色画面，view=depth 为伪彩深度图，
    view=lidar 为车端渲染后的 C16 16 线点云俯视图。
    本接口通过后端代理转发，确保前端访问需要经过 JWT 鉴权。

    车端只在存在订阅者时上传，并且每个浏览器消费者只保留最新帧。
    """
    from starlette.responses import StreamingResponse

    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    frame_queue = await agent_gateway.subscribe_frames(device_id, view)

    async def stream_generator():
        """将车端上传的 JPEG 帧封装为浏览器可直接显示的 MJPEG。"""
        try:
            while True:
                try:
                    frame: MediaFrame = await asyncio.wait_for(frame_queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    if not agent_gateway.is_media_connected(device_id):
                        return
                    continue
                yield (
                    b"--boundarydonotcross\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(frame.data)}\r\n\r\n".encode("ascii")
                    + frame.data
                    + b"\r\n"
                )
        finally:
            await agent_gateway.unsubscribe_frames(device_id, view, frame_queue)

    return StreamingResponse(
        stream_generator(),
        media_type="multipart/x-mixed-replace; boundary=boundarydonotcross",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Content-Type-Options": "nosniff",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{device_id}/camera/snapshot")
async def proxy_camera_snapshot(
    device_id: int,
    view: Literal["color", "depth", "lidar"] = "color",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取设备摄像头的单帧快照（JPEG 图片）（需登录）

    从车端 Agent 媒体通道获取指定视图的最新快照。
    用于截图保存等功能。
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    frame_queue = await agent_gateway.subscribe_frames(device_id, view)
    try:
        frame: MediaFrame = await asyncio.wait_for(frame_queue.get(), timeout=10)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="摄像头快照等待超时") from exc
    finally:
        await agent_gateway.unsubscribe_frames(device_id, view, frame_queue)

    CAMERA_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_filename = f"{device.name}_{timestamp}.jpg"
    snapshot_filepath = CAMERA_SNAPSHOTS_DIR / snapshot_filename
    snapshot_filepath.write_bytes(frame.data)
    print(f"[{datetime.now()}] 快照已保存: {snapshot_filepath}")
    return Response(
        content=frame.data,
        media_type="image/jpeg",
        headers={
            "Content-Disposition": f"attachment; filename=snapshot_{device_id}_{int(time.time())}.jpg",
            "Cache-Control": "no-cache",
        },
    )


# ===== 视频录制接口 =====

@router.get("/camera/recordings")
async def recording_statuses(
    current_user: User = Depends(get_current_user),
):
    """一次返回当前所有录制会话，供前端恢复录制状态。"""
    now = datetime.now()
    recordings = [
        {
            "recording": True,
            "device_id": device_id,
            "filename": session["filename"],
            "duration": round((now - session["start_time"]).total_seconds(), 1),
        }
        for device_id, session in list(_recording_sessions.items())
    ]
    return {"recordings": recordings}


@router.post("/{device_id}/camera/record/start")
async def start_recording(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    开始录制摄像头视频（需登录）

    后端持续消费车端 Agent 上传的 JPEG 帧并写入 MP4 文件。
    录制在后台异步进行，直到调用停止录制接口。
    """
    # 检查是否已在录制
    if device_id in _recording_sessions:
        raise HTTPException(status_code=409, detail="该设备正在录制中")

    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    ffmpeg_binary = _resolve_ffmpeg_binary()
    if not ffmpeg_binary:
        raise HTTPException(status_code=503, detail="未找到 FFmpeg，无法生成浏览器兼容的视频文件")

    # 确保保存目录存在
    CAMERA_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    CAMERA_RECORDING_TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # 生成文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{device.name}_{timestamp}.mp4"
    filepath = CAMERA_VIDEOS_DIR / filename
    recording_filepath = CAMERA_RECORDING_TEMP_DIR / filename

    # 停止时间单独记录，避免等待下一帧时把视频尾部无意拉长。
    control = _RecordingControl()

    frame_queue = await agent_gateway.subscribe_thread_frames(device_id, "color")

    async def run_recording_worker():
        try:
            return await asyncio.to_thread(
                _recording_worker,
                device_id,
                device.name,
                recording_filepath,
                filepath,
                control,
                frame_queue,
            )
        finally:
            await agent_gateway.unsubscribe_thread_frames(device_id, "color", frame_queue)

    # 启动录制后台任务
    task = asyncio.create_task(
        run_recording_worker()
    )

    _recording_sessions[device_id] = {
        "task": task,
        "control": control,
        "start_time": datetime.now(),
        "filename": filename,
    }

    print(f"[{datetime.now()}] 开始录制: 设备 {device.name} ({device_id}), 文件: {filename}")
    return {
        "message": "录制已开始",
        "device_id": device_id,
        "filename": filename,
    }


@router.post("/{device_id}/camera/record/stop")
async def stop_recording(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    停止录制摄像头视频（需登录）

    停止后台录制任务，完成 MP4 文件写入。
    """
    session = _recording_sessions.get(device_id)
    if not session:
        raise HTTPException(status_code=404, detail="该设备未在录制")

    # 发送停止信号
    session["control"].stop()

    # 等待录制结束并完成 H.264 转码。
    try:
        result = await asyncio.wait_for(
            session["task"],
            timeout=CAMERA_RECORD_FINALIZE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        session["task"].cancel()
        _recording_sessions.pop(device_id, None)
        raise HTTPException(status_code=504, detail="视频结束处理超时，请检查 FFmpeg 状态")

    if not result.get("saved"):
        raise HTTPException(status_code=500, detail=result.get("error") or "视频保存失败")

    # 计算录制时长
    duration = result.get("duration", 0)
    filename = session["filename"]

    # 清除录制状态
    _recording_sessions.pop(device_id, None)

    print(f"[{datetime.now()}] 录制结束: 设备 {device_id}, 时长: {duration:.1f}秒, 文件: {filename}")
    return {
        "message": "录制已停止",
        "device_id": device_id,
        "filename": filename,
        "duration": round(duration, 1),
    }


@router.get("/{device_id}/camera/record/status")
async def recording_status(
    device_id: int,
    current_user: User = Depends(get_current_user),
):
    """
    查询设备的录制状态（需登录）
    """
    session = _recording_sessions.get(device_id)
    if not session:
        return {"recording": False, "device_id": device_id}

    duration = (datetime.now() - session["start_time"]).total_seconds()
    return {
        "recording": True,
        "device_id": device_id,
        "filename": session["filename"],
        "duration": round(duration, 1),
    }


def _recording_worker(
    device_id: int,
    device_name: str,
    recording_filepath: Path,
    final_filepath: Path,
    control: _RecordingControl,
    frame_queue: queue.Queue,
):
    """
    录制后台工作函数（通过 asyncio.to_thread 在线程中执行）

    消费 Agent 媒体帧并通过 FFmpeg 管道写入 H.264 MP4。
    根据帧的实际到达时间重采样为固定帧率，收到停止信号后结束录制。
    """
    process = None
    frame_count = 0
    fps = 15  # 目标帧率
    error_message = None
    capture_started_at = None
    last_frame = None
    recording_started_logged = False

    try:
        ffmpeg_binary = _resolve_ffmpeg_binary()
        if not ffmpeg_binary:
            raise RuntimeError("未找到 FFmpeg")

        process = subprocess.Popen(
            [
                ffmpeg_binary,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "mjpeg",
                "-framerate",
                str(fps),
                "-i",
                "pipe:0",
                "-an",
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(recording_filepath),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        def write_until(frame: bytes, end_at: float) -> None:
            nonlocal frame_count
            if capture_started_at is None or process.stdin is None:
                return
            elapsed = max(0.0, end_at - capture_started_at)
            target_frame_count = max(1, int(elapsed * fps + 0.5))
            while frame_count < target_frame_count:
                process.stdin.write(frame)
                frame_count += 1

        while not control.stop_event.is_set():
            try:
                media_frame: MediaFrame = frame_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            frame = media_frame.data
            now = time.monotonic()
            if capture_started_at is None:
                capture_started_at = now
                last_frame = frame
            else:
                last_frame = frame
            write_until(last_frame, now)

            if not recording_started_logged and frame_count > 0:
                print(f"[{datetime.now()}] 录制中: 设备 {device_name}, H.264 编码已启动")
                recording_started_logged = True
    except Exception as exc:
        error_message = f"录制异常: {exc}"
        print(f"[{datetime.now()}] 录制异常 (设备 {device_id}): {exc}")
    finally:
        try:
            if (
                process
                and process.stdin
                and last_frame is not None
                and capture_started_at is not None
                and control.stopped_at is not None
            ):
                write_until(last_frame, control.stopped_at)
        except Exception as exc:
            error_message = error_message or f"补齐视频结束帧失败: {exc}"
        try:
            if process and process.stdin:
                process.stdin.close()
        except Exception as exc:
            error_message = error_message or f"关闭视频编码输入失败: {exc}"
        if process:
            try:
                return_code = process.wait(timeout=CAMERA_RECORD_FINALIZE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                error_message = error_message or "完成视频文件超时"
            else:
                stderr = process.stderr.read().decode("utf-8", errors="replace").strip() if process.stderr else ""
                if return_code != 0:
                    error_message = error_message or f"FFmpeg 编码失败: {stderr or f'退出码 {return_code}'}"

    saved = False
    if frame_count > 0 and not error_message and recording_filepath.is_file():
        recording_filepath.replace(final_filepath)
        saved = True
    else:
        recording_filepath.unlink(missing_ok=True)
        if not error_message:
            error_message = "未录制到有效视频帧"

    # 后台异常结束时同步清除录制状态。
    _recording_sessions.pop(device_id, None)
    print(f"[{datetime.now()}] 录制完成: 设备 {device_id}, 共 {frame_count} 帧, 文件: {final_filepath}")
    return {
        "saved": saved,
        "error": error_message,
        "frame_count": frame_count,
        "duration": round(frame_count / fps, 1),
    }
