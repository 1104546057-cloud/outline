"""
摄像头视频流代理路由

提供 MJPEG 视频流代理和快照获取接口。
"""

import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Response
from sqlalchemy.orm import Session

from database import get_db
from models import User, Device
from auth import get_current_user
from config import CAMERA_STREAM_PORT

router = APIRouter(prefix="/api/devices", tags=["摄像头"])


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
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=10.0)) as client:
            response = await client.get(snapshot_url)
            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"摄像头快照获取失败 (HTTP {response.status_code})"
                )
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
