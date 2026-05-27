"""
数据库模型定义

定义系统中的所有数据库表结构（ORM 模型）。
"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Table, Text, Numeric, JSON
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    """用户表模型"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="用户ID")
    username = Column(String(50), unique=True, nullable=False, index=True, comment="用户名")
    password_hash = Column(String(255), nullable=False, comment="密码哈希值")
    nickname = Column(String(100), nullable=True, comment="用户昵称")
    is_active = Column(Boolean, default=True, nullable=False, comment="是否启用")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', nickname='{self.nickname}')>"


class Device(Base):
    """设备表模型"""
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="设备ID")
    name = Column(String(100), nullable=False, comment="设备名称")
    type = Column(String(50), nullable=False, comment="设备类型(无人车/无人机/无人船)")
    ip_address = Column(String(50), nullable=False, unique=True, comment="IP地址")
    port = Column(Integer, default=9000, nullable=False, comment="控制服务端口号")
    status = Column(String(20), default="offline", comment="在线状态(online/offline)")
    battery = Column(Integer, nullable=True, comment="电量%")
    health = Column(Integer, default=100, comment="健康度%")
    signal = Column(Integer, nullable=True, comment="信号强度%")
    speed = Column(String(20), default="0 m/s", comment="当前速度")
    lat = Column(String(50), nullable=True, comment="纬度")
    lng = Column(String(50), nullable=True, comment="经度")
    last_seen = Column(DateTime, nullable=True, comment="最后遥测上报时间")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    # 关联遥测数据
    telemetry_records = relationship("DeviceTelemetry", back_populates="device", cascade="all, delete-orphan")
    # 关联设备 Token
    tokens = relationship("DeviceToken", back_populates="device", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Device(id={self.id}, name='{self.name}', ip='{self.ip_address}:{self.port}')>"


class DeviceTelemetry(Base):
    """设备遥测记录表"""
    __tablename__ = "device_telemetry"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="遥测记录ID")
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True, comment="设备ID")
    battery = Column(Integer, nullable=True, comment="电量%")
    signal = Column(Integer, nullable=True, comment="信号强度%")
    status = Column(String(32), nullable=True, comment="设备状态")
    lat = Column(Numeric(10, 7), nullable=True, comment="纬度")
    lng = Column(Numeric(10, 7), nullable=True, comment="经度")
    source_ip = Column(String(64), nullable=True, comment="上报来源IP")
    extra_json = Column(JSON, nullable=True, comment="扩展数据(CPU温度/GPS状态等)")
    reported_at = Column(DateTime, nullable=False, comment="上报时间")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")

    device = relationship("Device", back_populates="telemetry_records")

    def __repr__(self):
        return f"<DeviceTelemetry(id={self.id}, device_id={self.device_id}, reported_at={self.reported_at})>"


class DeviceToken(Base):
    """设备认证 Token 表"""
    __tablename__ = "device_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="Token ID")
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True, comment="设备ID")
    token = Column(String(128), unique=True, nullable=False, comment="设备Token")
    note = Column(String(256), nullable=True, comment="备注")
    is_active = Column(Boolean, default=True, nullable=False, comment="是否有效")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")

    device = relationship("Device", back_populates="tokens")

    def __repr__(self):
        return f"<DeviceToken(id={self.id}, device_id={self.device_id})>"


# 集群与设备的多对多关联表
cluster_device_association = Table(
    "cluster_device",
    Base.metadata,
    Column("cluster_id", Integer, ForeignKey("clusters.id", ondelete="CASCADE"), primary_key=True),
    Column("device_id", Integer, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
)


class Cluster(Base):
    """集群表模型"""
    __tablename__ = "clusters"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="集群ID")
    name = Column(String(100), nullable=False, unique=True, comment="集群名称")
    description = Column(String(255), nullable=True, comment="集群描述")
    created_at = Column(DateTime, default=datetime.now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False, comment="更新时间")

    # 关联设备列表，自动加载
    devices = relationship("Device", secondary=cluster_device_association, backref="clusters", lazy="joined")

    def __repr__(self):
        return f"<Cluster(id={self.id}, name='{self.name}')>"
