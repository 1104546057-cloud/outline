"""
摄像头视频流代理路由

提供 MJPEG 视频流代理、快照获取和视频录制接口。
"""

import time
import asyncio
import threading
from datetime import datetime
from pathlib import Path

import imageio_ffmpeg
from fastapi import APIRouter, HTTPException, Depends, Response
from sqlalchemy.orm import Session

from database import get_db
from models import User, Device
from auth import get_current_user
from config import (
    CAMERA_RECORD_FINALIZE_TIMEOUT_SECONDS,
    CAMERA_STREAM_PORT,
)

router = APIRouter(prefix="/api/devices", tags=["摄像头"])

# ===== 录制状态管理 =====
# 格式: { device_id: { "task": asyncio.Task, "stop_event": threading.Event, "start_time": datetime, "filename": str } }
_recording_sessions: dict[int, dict] = {}

# 录制视频保存目录（相对于 backend 目录的 ../data/camera_videos）
CAMERA_VIDEOS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "camera_videos"
CAMERA_RECORDING_TEMP_DIR = CAMERA_VIDEOS_DIR / ".recording"

# 快照保存目录（相对于 backend 目录的 ../data/camera_snapshots）
CAMERA_SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "camera_snapshots"


def _resolve_ffmpeg_binary() -> str | None:
    """通过 imageio-ffmpeg 获取其管理的 FFmpeg 可执行文件。"""
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except RuntimeError:
        return None


@router.get("/{device_id}/camera/stream")
async def proxy_camera_stream(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    代理转发设备的 MJPEG 摄像头视频流（需登录）

    设备端运行 mjpg_streamer，在 8080 端口提供 MJPEG 流。
    本接口通过后端代理转发，确保前端访问需要经过 JWT 鉴权。

    使用独立的 httpx.AsyncClient 实例避免与其他请求共享连接池，
    从而解决多路视频流并发时阻塞的问题。
    """
    import httpx
    from starlette.responses import StreamingResponse

    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    if not device.ip_address:
        raise HTTPException(status_code=422, detail="设备未配置 IP 地址")

    camera_url = f"http://{device.ip_address}:{CAMERA_STREAM_PORT}/?action=stream"

    async def stream_generator():
        """异步读取 MJPEG 流并逐块转发，每路流独立创建连接"""
        client = None
        try:
            # 每路视频流创建独立的 httpx 客户端，避免连接池竞争
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=None, write=5.0, pool=None),
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            )
            async with client.stream("GET", camera_url) as response:
                if response.status_code != 200:
                    print(f"[{datetime.now()}] 摄像头流代理: 设备 {device_id} 返回 HTTP {response.status_code}")
                    return
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    yield chunk
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            print(f"[{datetime.now()}] 摄像头流代理失败 (设备 {device_id}): {exc}")
            return
        except Exception as exc:
            print(f"[{datetime.now()}] 摄像头流代理异常 (设备 {device_id}): {exc}")
            return
        finally:
            if client:
                await client.aclose()

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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取设备摄像头的单帧快照（JPEG 图片）（需登录）

    通过后端代理从 mjpg_streamer 的 ?action=snapshot 接口获取。
    用于截图保存等功能。
    """
    import httpx

    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    if not device.ip_address:
        raise HTTPException(status_code=422, detail="设备未配置 IP 地址")

    snapshot_url = f"http://{device.ip_address}:{CAMERA_STREAM_PORT}/?action=snapshot"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            response = await client.get(snapshot_url)
            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"摄像头快照获取失败 (HTTP {response.status_code})"
                )

            # 将快照保存到本地文件
            CAMERA_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            snapshot_filename = f"{device.name}_{timestamp}.jpg"
            snapshot_filepath = CAMERA_SNAPSHOTS_DIR / snapshot_filename
            snapshot_filepath.write_bytes(response.content)
            print(f"[{datetime.now()}] 快照已保存: {snapshot_filepath}")

            return Response(
                content=response.content,
                media_type="image/jpeg",
                headers={
                    "Content-Disposition": f"attachment; filename=snapshot_{device_id}_{int(time.time())}.jpg",
                    "Cache-Control": "no-cache",
                },
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="无法连接到设备摄像头服务")
    except httpx.ReadTimeout:
        raise HTTPException(status_code=504, detail="摄像头响应超时")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"摄像头快照获取异常: {exc}")


# ===== 视频录制接口 =====

@router.post("/{device_id}/camera/record/start")
async def start_recording(
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    开始录制摄像头视频（需登录）

    后端持续从设备摄像头获取 MJPEG 流，解析出 JPEG 帧并写入 MP4 文件。
    录制在后台异步进行，直到调用停止录制接口。
    """
    # 检查是否已在录制
    if device_id in _recording_sessions:
        raise HTTPException(status_code=409, detail="该设备正在录制中")

    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    if not device.ip_address:
        raise HTTPException(status_code=422, detail="设备未配置 IP 地址")

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

    # 创建停止事件
    stop_event = threading.Event()

    # 启动录制后台任务
    task = asyncio.create_task(
        asyncio.to_thread(
            _recording_worker,
            device_id,
            device.ip_address,
            device.name,
            recording_filepath,
            filepath,
            stop_event,
        )
    )

    _recording_sessions[device_id] = {
        "task": task,
        "stop_event": stop_event,
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
    session["stop_event"].set()

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
    ip_address: str,
    device_name: str,
    recording_filepath: Path,
    final_filepath: Path,
    stop_event: threading.Event,
):
    """
    录制后台工作函数（通过 asyncio.to_thread 在线程中执行）

    连接设备的 MJPEG 流，逐帧提取 JPEG 数据并通过 FFmpeg 管道写入 H.264 MP4。
    当 stop_event 被设置时停止录制。
    """
    camera_url = f"http://{ip_address}:{CAMERA_STREAM_PORT}/?action=stream"
    reader = None
    writer = None
    frame_count = 0
    fps = 15  # 目标帧率
    error_message = None

    try:
        reader = imageio_ffmpeg.read_frames(
            camera_url,
            pix_fmt="rgb24",
            input_params=["-f", "mjpeg"],
            output_params=["-vf", f"fps={fps}"],
        )
        metadata = next(reader)
        frame_size = metadata.get("size")
        if not frame_size or len(frame_size) != 2:
            raise RuntimeError("无法获取摄像头画面尺寸")

        writer = imageio_ffmpeg.write_frames(
            recording_filepath,
            tuple(frame_size),
            pix_fmt_in="rgb24",
            pix_fmt_out="yuv420p",
            fps=fps,
            quality=6,
            codec="libx264",
            macro_block_size=2,
            ffmpeg_log_level="error",
            ffmpeg_timeout=CAMERA_RECORD_FINALIZE_TIMEOUT_SECONDS,
            output_params=["-preset", "veryfast", "-movflags", "+faststart"],
        )
        writer.send(None)

        for frame in reader:
            if stop_event.is_set():
                break
            writer.send(frame)
            frame_count += 1
            if frame_count == 1:
                print(
                    f"[{datetime.now()}] 录制中: 设备 {device_name}, "
                    f"分辨率 {frame_size[0]}×{frame_size[1]}, H.264 编码已启动"
                )
    except Exception as exc:
        error_message = f"录制异常: {exc}"
        print(f"[{datetime.now()}] 录制异常 (设备 {device_id}): {exc}")
    finally:
        try:
            if reader:
                reader.close()
        except Exception as exc:
            error_message = error_message or f"关闭视频读取器失败: {exc}"
        try:
            if writer:
                writer.close()
        except Exception as exc:
            error_message = error_message or f"完成视频文件失败: {exc}"

    saved = False
    if frame_count > 0 and not error_message and recording_filepath.is_file():
        recording_filepath.replace(final_filepath)
        saved = True
    else:
        recording_filepath.unlink(missing_ok=True)
        if not error_message:
            error_message = "未录制到有效视频帧"

    # 确保从录制列表中清除（防止异常退出时残留）
    _recording_sessions.pop(device_id, None)
    print(f"[{datetime.now()}] 录制完成: 设备 {device_id}, 共 {frame_count} 帧, 文件: {final_filepath}")
    return {
        "saved": saved,
        "error": error_message,
        "frame_count": frame_count,
        "duration": round(frame_count / fps, 1),
    }
