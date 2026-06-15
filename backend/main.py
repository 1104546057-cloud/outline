"""
智慧校园巡逻管理系统 - 后端服务

基于 FastAPI 框架构建的 RESTful API 后端服务。
提供用户认证、用户管理、设备管理、真实无人车 TCP 控制和 IoT 遥测接口。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import login, users, devices, robot_control, telemetry, clusters, camera, patrol, captcha

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
        "http://localhost:5173",  # Vite 默认开发服务器地址
        "http://127.0.0.1:5173",
        "http://192.168.31.28:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有 HTTP 方法
    allow_headers=["*"],  # 允许所有请求头
)


# ===== 根路由 =====

@app.get("/")
async def root():
    """根路径接口，返回欢迎信息"""
    return {"message": "欢迎使用智慧校园巡逻管理系统 API"}


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
app.include_router(captcha.router)
