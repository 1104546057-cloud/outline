"""
智慧校园巡逻管理系统 - 后端服务

基于 FastAPI 框架构建的 RESTful API 后端服务。
提供用户认证、用户管理、设备管理、无人车 WebSocket 控制和 IoT 遥测接口。
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from routers import agent_ws, login, users, devices, robot_control, telemetry, clusters, camera, patrol, patrol_results, navigation, captcha, remote_access, security_alerts, analytics, analytics_admin, outdoor_patrol, inference, alerts_ws

# 创建 FastAPI 应用实例
app = FastAPI(
    title="智慧校园巡逻管理系统",
    description="基于 FastAPI 的智慧校园巡逻管理系统后端 API",
    version="0.3.0",
)

# 配置 CORS 跨域中间件，允许前端开发服务器访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5273",
        "http://127.0.0.1:5273",
        "http://192.168.31.28:5273",
    ],
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有 HTTP 方法
    allow_headers=["*"],  # 允许所有请求头
)


@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "message": "服务运行正常"}


# ===== 注册子路由 =====

app.include_router(login.router)
app.include_router(users.router)
app.include_router(devices.router)
app.include_router(robot_control.router)
app.include_router(telemetry.router)
app.include_router(clusters.router)
app.include_router(camera.router)
app.include_router(patrol.router)
app.include_router(patrol_results.router)
app.include_router(navigation.router)
app.include_router(captcha.router)
app.include_router(agent_ws.router)
app.include_router(remote_access.router)
app.include_router(security_alerts.router)
app.include_router(analytics.router)
app.include_router(analytics_admin.router)
app.include_router(outdoor_patrol.router)
app.include_router(inference.router)
app.include_router(alerts_ws.router)


# ===== 研判模块后台调度（启动时挂载，关闭时清理） =====

def _start_analytics_scheduler():
    """启动 APScheduler：每日凌晨日聚合 + 每 5 分钟近实时规则评估。

    若 APScheduler 未安装则静默跳过，不影响主服务启动；
    调度也可通过 /api/analytics/admin/run-daily 与 run-rules 手动触发。
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
        from analytics.scheduler import run_daily, run_near_realtime
        from config import ANALYTICS_DAILY_RUN_HOUR, ANALYTICS_NEAR_REALTIME_INTERVAL

        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            run_daily,
            CronTrigger(hour=ANALYTICS_DAILY_RUN_HOUR, minute=0),
            id="analytics_daily",
            replace_existing=True,
        )
        scheduler.add_job(
            run_near_realtime,
            IntervalTrigger(seconds=ANALYTICS_NEAR_REALTIME_INTERVAL),
            id="analytics_near_realtime",
            replace_existing=True,
        )
        scheduler.start()
        print(f"[analytics] 调度器已启动：日聚合 {ANALYTICS_DAILY_RUN_HOUR:02d}:00，近实时间隔 {ANALYTICS_NEAR_REALTIME_INTERVAL}s")
        return scheduler
    except ImportError:
        print("[analytics] APScheduler 未安装，跳过自动调度（可通过 admin 接口手动触发）")
        return None
    except Exception as e:
        print(f"[analytics] 调度器启动失败: {e}")
        return None


@app.on_event("startup")
async def _on_startup():
    app.state.analytics_scheduler = _start_analytics_scheduler()


@app.on_event("shutdown")
async def _on_shutdown():
    scheduler = getattr(app.state, "analytics_scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)
        print("[analytics] 调度器已关闭")
    # 停止所有运行中的推理管线，释放帧订阅
    from inference.manager import inference_manager
    await inference_manager.stop_all()
    print("[inference] 推理管线已全部停止")


# ===== 前端静态文件 =====

FRONTEND_DIST_DIR = (Path(__file__).resolve().parent.parent / "frontend" / "dist").resolve()


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    """提供前端构建文件，并为 React BrowserRouter 回退到 index.html。"""
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    requested_file = (FRONTEND_DIST_DIR / full_path).resolve()
    if requested_file.is_relative_to(FRONTEND_DIST_DIR) and requested_file.is_file():
        return FileResponse(requested_file)

    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)

    raise HTTPException(status_code=404, detail="前端尚未构建，请先生成 frontend/dist")
