#!/usr/bin/env python3
"""
iot_client.py — ROS1 wheeltec 无人车设备端上报客户端（ROS-like 重构版）
========================================================
功能：
  1. 定期（默认 60 秒）上报遥测数据（电量、信号、GPS、机器人状态）到后端
  2. GPS 坐标通过订阅 ROS /fix (sensor_msgs/NavSatFix) 话题获取
     （需在车端启动 G70 RTK 驱动，见下方 "前置 launch" 说明）
  3. 电源状态通过 /PowerVoltage、/robot_charging_flag 等话题获取
  4. 底盘安全、自检、充电、里程计、IMU 等均通过 ROS 话题获取

前置 launch（车端需预先启动）：
  - 底盘驱动（提供 /PowerVoltage /odom /chassis_security 等）：
      roslaunch turn_on_wheeltec_robot turn_on_wheeltec_robot.launch
  - G70 RTK 差分定位驱动（提供 /fix）：
      roslaunch wheeltec_gps_driver wheeltec_dual_rtk_driver_nmea.launch

用法：
  python3 iot_client.py --server http://<服务器IP>:5273 --token <设备Token>

配置文件（可选，与脚本同目录的 iot_client.conf）：
  [client]
  server   = http://192.168.31.28:5273
  token    = <从设备管理页面获取的 Token>
  interval = 60
  point_id = 1
  route_id = 1
"""

import argparse
import configparser
import json
import logging
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import rospy
    from std_msgs.msg import (
        Bool as RosBool,
        Float32 as RosFloat32,
        Int8 as RosInt8,
        UInt8 as RosUInt8,
        UInt32 as RosUInt32,
    )
    from sensor_msgs.msg import NavSatFix, NavSatStatus, Imu
    from nav_msgs.msg import Odometry
    ROSPY_AVAILABLE = True
except ImportError:
    ROSPY_AVAILABLE = False

# ── 日志 ──────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("iot_client")

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "iot_client.conf"

# 6S 锂电池电压范围（用于换算电量百分比）
_BATTERY_VOLTAGE_MIN = 18.0   # 3.0V/cell × 6，放电截止
_BATTERY_VOLTAGE_MAX = 25.2   # 4.2V/cell × 6，满电
HTTP_TIMEOUT_SEC = 5
FAILED_REPORT_RETRY_SEC = 5


def configure_local_ros_network() -> None:
    """Advertise a reachable local address for this single-host vehicle ROS graph."""
    master_uri = os.environ.get("ROS_MASTER_URI", "http://localhost:11311")
    ros_ip = os.environ.get("DWC_ROS_IP", "127.0.0.1").strip() or "127.0.0.1"
    os.environ.pop("ROS_HOSTNAME", None)
    os.environ["ROS_IP"] = ros_ip
    log.info(
        "ROS 网络环境 master=%s ROS_IP=%s ROS_HOSTNAME=%s",
        master_uri,
        os.environ.get("ROS_IP", ""),
        os.environ.get("ROS_HOSTNAME", ""),
    )

# ── ROS 话题缓存（线程安全）──────────────────────────────────────────────────
_ros_lock = Lock()
_ros_initialized: bool = False

# 电源（/PowerVoltage  /robot_charging_flag  /robot_charging_current）
_ros_voltage: Optional[float] = None
_ros_charging: Optional[bool] = None
_ros_charging_current: Optional[float] = None

# GPS（/fix，sensor_msgs/NavSatFix，由 wheeltec_dual_rtk_driver_nmea.launch 发布）
_ros_gps_lat: Optional[float] = None
_ros_gps_lng: Optional[float] = None
_ros_gps_status: Optional[int] = None   # NavSatStatus: -1=NO_FIX, 0=FIX, 1=SBAS, 2=GBAS(RTK)

# 底盘安全锁定（/chassis_security, std_msgs/Int8，1=正常解除，0=锁定）
_ros_chassis_security: Optional[int] = 1

# 自检状态（/robot_selfcheck, std_msgs/UInt32，bitmask）
_ros_selfcheck: Optional[int] = 0

# 红旗/急停（/robot_red_flag, std_msgs/UInt8）
_ros_red_flag: Optional[int] = 0

# 回充状态（/robot_recharge_flag, std_msgs/Int8）
_ros_recharge_flag: Optional[int] = 0

# 里程计速度（/odom, nav_msgs/Odometry）
_ros_odom_vx: Optional[float] = None     # 前进线速度 m/s
_ros_odom_vyaw: Optional[float] = None   # 偏航角速度 rad/s

# IMU 加速度（/imu, sensor_msgs/Imu）
_ros_imu_ax: Optional[float] = None
_ros_imu_ay: Optional[float] = None
_ros_imu_az: Optional[float] = None


# ── ROS 回调函数 ──────────────────────────────────────────────────────────────

def _on_power_voltage(msg) -> None:
    """回调：/PowerVoltage 电压更新。"""
    global _ros_voltage
    with _ros_lock:
        _ros_voltage = msg.data


def _on_charging_flag(msg) -> None:
    """回调：/robot_charging_flag 充电状态更新。"""
    global _ros_charging
    with _ros_lock:
        _ros_charging = msg.data


def _on_charging_current(msg) -> None:
    """回调：/robot_charging_current 充电电流更新。"""
    global _ros_charging_current
    with _ros_lock:
        _ros_charging_current = msg.data


def _on_gps_fix(msg) -> None:
    """回调：/fix GPS 定位数据更新（G70 RTK 驱动发布）。"""
    global _ros_gps_lat, _ros_gps_lng, _ros_gps_status
    with _ros_lock:
        _ros_gps_status = msg.status.status
        # STATUS_NO_FIX=-1, STATUS_FIX=0, STATUS_SBAS_FIX=1, STATUS_GBAS_FIX=2(RTK)
        if msg.status.status >= NavSatStatus.STATUS_FIX:
            _ros_gps_lat = msg.latitude
            _ros_gps_lng = msg.longitude
        else:
            _ros_gps_lat = None
            _ros_gps_lng = None


def _on_chassis_security(msg) -> None:
    """回调：/chassis_security 底盘安全状态更新。"""
    global _ros_chassis_security
    with _ros_lock:
        _ros_chassis_security = msg.data


def _on_selfcheck(msg) -> None:
    """回调：/robot_selfcheck 机器人自检状态更新。"""
    global _ros_selfcheck
    with _ros_lock:
        _ros_selfcheck = msg.data


def _on_red_flag(msg) -> None:
    """回调：/robot_red_flag 急停/红旗状态更新。"""
    global _ros_red_flag
    with _ros_lock:
        _ros_red_flag = msg.data


def _on_recharge_flag(msg) -> None:
    """回调：/robot_recharge_flag 回充状态更新。"""
    global _ros_recharge_flag
    with _ros_lock:
        _ros_recharge_flag = msg.data


def _on_odom(msg) -> None:
    """回调：/odom 里程计速度更新。"""
    global _ros_odom_vx, _ros_odom_vyaw
    with _ros_lock:
        _ros_odom_vx = msg.twist.twist.linear.x
        _ros_odom_vyaw = msg.twist.twist.angular.z


def _on_imu(msg) -> None:
    """回调：/imu IMU 线加速度更新。"""
    global _ros_imu_ax, _ros_imu_ay, _ros_imu_az
    with _ros_lock:
        _ros_imu_ax = msg.linear_acceleration.x
        _ros_imu_ay = msg.linear_acceleration.y
        _ros_imu_az = msg.linear_acceleration.z


# ── ROS 初始化 ────────────────────────────────────────────────────────────────

def init_ros_subscribers() -> bool:
    """初始化 ROS 节点，订阅所有遥测相关话题。成功返回 True。"""
    global _ros_initialized
    if _ros_initialized:
        return True
    if not ROSPY_AVAILABLE:
        log.debug("rospy 不可用，跳过 ROS 话题订阅")
        return False
    try:
        rospy.init_node("iot_client", anonymous=True, disable_signals=True)

        # 电源
        rospy.Subscriber("/PowerVoltage", RosFloat32, _on_power_voltage, queue_size=1)
        rospy.Subscriber("/robot_charging_flag", RosBool, _on_charging_flag, queue_size=1)
        rospy.Subscriber("/robot_charging_current", RosFloat32, _on_charging_current, queue_size=1)

        # GPS（需启动 wheeltec_dual_rtk_driver_nmea.launch）
        rospy.Subscriber("/fix", NavSatFix, _on_gps_fix, queue_size=1)

        # 底盘状态（由 turn_on_wheeltec_robot.launch 提供）
        rospy.Subscriber("/chassis_security", RosInt8, _on_chassis_security, queue_size=1)
        rospy.Subscriber("/robot_selfcheck", RosUInt32, _on_selfcheck, queue_size=1)
        rospy.Subscriber("/robot_red_flag", RosUInt8, _on_red_flag, queue_size=1)
        rospy.Subscriber("/robot_recharge_flag", RosInt8, _on_recharge_flag, queue_size=1)

        # 运动状态（由 turn_on_wheeltec_robot.launch 提供）
        rospy.Subscriber("/odom", Odometry, _on_odom, queue_size=1)
        rospy.Subscriber("/imu", Imu, _on_imu, queue_size=1)

        _ros_initialized = True
        log.info(
            "ROS 话题订阅已初始化 | 电源: /PowerVoltage /robot_charging_* "
            "| GPS: /fix | 底盘: /chassis_security /robot_selfcheck /robot_red_flag /robot_recharge_flag "
            "| 运动: /odom /imu"
        )
        return True
    except Exception as exc:
        log.warning(f"ROS 初始化失败: {exc}")
        return False


# ── 数据读取 ──────────────────────────────────────────────────────────────────

def read_ros_power() -> Optional[Dict[str, Any]]:
    """从 ROS 话题缓存读取电源信息（电压、电量、充电状态）。"""
    with _ros_lock:
        voltage = _ros_voltage
        charging = _ros_charging
        charging_current = _ros_charging_current

    if voltage is None:
        return None

    percent = (voltage - _BATTERY_VOLTAGE_MIN) / (_BATTERY_VOLTAGE_MAX - _BATTERY_VOLTAGE_MIN) * 100
    percent = max(0.0, min(100.0, percent))

    result: Dict[str, Any] = {
        "voltage_V": round(voltage, 3),
        "percent": round(percent, 1),
    }
    if charging is not None:
        result["charging"] = charging
    if charging_current is not None:
        result["charging_current_A"] = round(charging_current, 3)
    return result


def read_battery() -> Optional[int]:
    """
    读取电量百分比。
    优先从 ROS /PowerVoltage 话题读取，降级到 sysfs。
    """
    power_data = read_ros_power()
    if power_data is not None:
        return int(power_data["percent"])
    raw = _read_file("/sys/class/power_supply/BAT0/capacity")
    if raw and raw.isdigit():
        return int(raw)
    return None


def read_gps() -> Tuple[Optional[float], Optional[float]]:
    """从 /fix 话题缓存读取 GPS 坐标；G70 RTK 无定位时返回 (None, None)。"""
    with _ros_lock:
        return _ros_gps_lat, _ros_gps_lng


def read_gps_status() -> Optional[int]:
    """读取最近一次 /fix 消息的 NavSatStatus.status 值（-1/0/1/2）。"""
    with _ros_lock:
        return _ros_gps_status


def read_robot_status() -> Optional[Dict[str, Any]]:
    """读取底盘安全、自检、急停、回充状态。"""
    with _ros_lock:
        chassis = _ros_chassis_security
        selfcheck = _ros_selfcheck
        red_flag = _ros_red_flag
        recharge_flag = _ros_recharge_flag

    if all(v is None for v in (chassis, selfcheck, red_flag, recharge_flag)):
        return None

    data: Dict[str, Any] = {}
    if chassis is not None:
        data["chassis_security"] = int(chassis)
    if selfcheck is not None:
        data["selfcheck"] = int(selfcheck)
    if red_flag is not None:
        data["red_flag"] = int(red_flag)
    if recharge_flag is not None:
        data["recharge_flag"] = int(recharge_flag)
    return data


def read_motion_status() -> Optional[Dict[str, Any]]:
    """读取里程计速度和 IMU 线加速度。"""
    with _ros_lock:
        vx = _ros_odom_vx
        vyaw = _ros_odom_vyaw
        ax, ay, az = _ros_imu_ax, _ros_imu_ay, _ros_imu_az

    data: Dict[str, Any] = {}
    if vx is not None:
        data["linear_x_mps"] = round(vx, 4)
    if vyaw is not None:
        data["angular_z_radps"] = round(vyaw, 4)
    if ax is not None:
        data["accel"] = {
            "x": round(ax, 4),
            "y": round(ay, 4),
            "z": round(az, 4),
        }
    return data if data else None


def read_signal() -> Optional[int]:
    """
    读取 Wi-Fi 信号强度（RSSI），转换为 0~100 百分比。
    仅在 Linux 下有效。
    """
    try:
        out = subprocess.check_output(
            ["iwconfig", "wlan0"], stderr=subprocess.DEVNULL, text=True, timeout=3
        )
        for part in out.split():
            if part.startswith("level="):
                dbm = int(part.split("=")[1])
                pct = max(0, min(100, 2 * (dbm + 100)))
                return pct
    except Exception:
        pass
    return None


# ── 系统信息采集（基于 psutil）────────────────────────────────────────────────

def _read_file(path: str) -> Optional[str]:
    try:
        return Path(path).read_text().strip()
    except Exception:
        return None


def read_cpu_info() -> Optional[Dict[str, Any]]:
    """读取 CPU 使用率、核心数、频率等信息。"""
    if not PSUTIL_AVAILABLE:
        return None
    try:
        per_core = psutil.cpu_percent(interval=0.5, percpu=True)
        total = psutil.cpu_percent(interval=0)
        core_count = psutil.cpu_count(logical=True)
        freq = psutil.cpu_freq()
        data: Dict[str, Any] = {
            "total": total,
            "per_core": per_core,
            "core_count": core_count,
        }
        if freq:
            data["freq_current_mhz"] = round(freq.current, 1)
            if freq.max:
                data["freq_max_mhz"] = round(freq.max, 1)
        return data
    except Exception:
        return None


def read_memory_info() -> Optional[Dict[str, Any]]:
    """读取物理内存和 Swap 使用情况。"""
    if not PSUTIL_AVAILABLE:
        return None
    try:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return {
            "physical": {
                "total_gb": round(mem.total / (1024 ** 3), 2),
                "used_gb": round(mem.used / (1024 ** 3), 2),
                "available_gb": round(mem.available / (1024 ** 3), 2),
                "percent": mem.percent,
            },
            "swap": {
                "total_gb": round(swap.total / (1024 ** 3), 2),
                "used_gb": round(swap.used / (1024 ** 3), 2),
                "percent": swap.percent,
            },
        }
    except Exception:
        return None


def read_disk_info() -> Optional[List[Dict[str, Any]]]:
    """读取磁盘分区使用情况。"""
    if not PSUTIL_AVAILABLE:
        return None
    try:
        disk_data: List[Dict[str, Any]] = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disk_data.append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total_gb": round(usage.total / (1024 ** 3), 2),
                    "used_gb": round(usage.used / (1024 ** 3), 2),
                    "free_gb": round(usage.free / (1024 ** 3), 2),
                    "percent": usage.percent,
                })
            except (PermissionError, OSError):
                continue
        return disk_data if disk_data else None
    except Exception:
        return None


def read_network_info() -> Optional[Dict[str, Any]]:
    """读取网络 IO 流量统计。"""
    if not PSUTIL_AVAILABLE:
        return None
    try:
        counters = psutil.net_io_counters(pernic=True)
        network_data: Dict[str, Any] = {}
        for nic_name, stats in counters.items():
            if nic_name == "lo":
                continue
            network_data[nic_name] = {
                "bytes_sent": stats.bytes_sent,
                "bytes_recv": stats.bytes_recv,
                "packets_sent": stats.packets_sent,
                "packets_recv": stats.packets_recv,
                "errin": stats.errin,
                "errout": stats.errout,
            }
        if_stats = psutil.net_if_stats()
        for nic_name in network_data:
            if nic_name in if_stats:
                network_data[nic_name]["is_up"] = if_stats[nic_name].isup
                if if_stats[nic_name].speed:
                    network_data[nic_name]["speed_mbps"] = if_stats[nic_name].speed
        return network_data if network_data else None
    except Exception:
        return None


def read_system_info() -> Optional[Dict[str, Any]]:
    """读取系统基础信息：启动时间、运行时长、负载、主机名。"""
    try:
        data: Dict[str, Any] = {}
        if PSUTIL_AVAILABLE:
            boot_ts = psutil.boot_time()
            uptime_sec = time.time() - boot_ts
            hours = int(uptime_sec // 3600)
            minutes = int((uptime_sec % 3600) // 60)
            data["boot_time"] = datetime.fromtimestamp(boot_ts).isoformat(timespec="seconds")
            data["uptime"] = f"{hours}h {minutes}m"
            data["uptime_seconds"] = int(uptime_sec)
        if hasattr(os, "getloadavg"):
            load = os.getloadavg()
            data["load_avg"] = {
                "1min": round(load[0], 2),
                "5min": round(load[1], 2),
                "15min": round(load[2], 2),
            }
        try:
            data["hostname"] = os.uname().nodename
        except AttributeError:
            import platform
            data["hostname"] = platform.node()
        return data if data else None
    except Exception:
        return None


def read_hardware_info() -> Optional[Dict[str, Any]]:
    """读取 Jetson 硬件详情。"""
    hw_list: List[Dict[str, str]] = []

    model = _read_file("/sys/firmware/devicetree/base/model")
    if model:
        hw_list.append({"label": "Description", "value": model.strip('\x00')})

    tegra = _read_file("/etc/nv_tegra_release")
    if tegra:
        hw_list.append({"label": "Tegra Release", "value": tegra.split("\n")[0].strip("# ").strip()})

    try:
        out = subprocess.check_output(
            ["python3", "-c",
             "from jtop import jtop; j=jtop(); j.start(); "
             "b=j.board; "
             "print('SoC:', b.get('hardware',{}).get('Module','N/A')); "
             "print('L4T:', b.get('hardware',{}).get('L4T','N/A')); "
             "print('Jetpack:', b.get('hardware',{}).get('Jetpack','N/A')); "
             "print('CUDA:', b.get('libraries',{}).get('CUDA','N/A')); "
             "j.close()"],
            text=True, stderr=subprocess.DEVNULL, timeout=10,
        )
        for line in out.strip().splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                val = val.strip()
                if val and val != "N/A":
                    hw_list.append({"label": key.strip(), "value": val})
    except Exception:
        pass

    if hw_list:
        return {"info": hw_list, "diagram": None}
    return None


def read_gpu_info() -> Optional[Dict[str, Any]]:
    """读取 Jetson GPU 使用率、频率和温度（依赖 jtop）。"""
    gpu_data: Dict[str, Any] = {}
    jetson = None
    try:
        from jtop import jtop
        jetson = jtop()
        jetson.start()

        gpu_status = jetson.gpu
        if hasattr(gpu_status, "items"):
            for key, info in gpu_status.items():
                if not isinstance(info, dict):
                    continue
                if "status" in info and isinstance(info["status"], dict) and "load" in info["status"]:
                    gpu_data["load_percent"] = round(float(info["status"]["load"]), 1)
                elif "val" in info:
                    gpu_data["load_percent"] = round(float(info["val"]), 1)
                elif "load" in info:
                    gpu_data["load_percent"] = round(float(info["load"]), 1)
                if "freq" in info and isinstance(info["freq"], dict):
                    freq_info = info["freq"]
                    cur = freq_info.get("cur")
                    max_f = freq_info.get("max")
                    if cur is not None:
                        gpu_data["freq_current_mhz"] = round(float(cur) / 1000.0 if float(cur) > 10000 else float(cur), 1)
                    if max_f is not None:
                        gpu_data["freq_max_mhz"] = round(float(max_f) / 1000.0 if float(max_f) > 10000 else float(max_f), 1)
        elif isinstance(gpu_status, (int, float)):
            gpu_data["load_percent"] = round(float(gpu_status), 1)
        elif isinstance(gpu_status, (tuple, list)):
            if len(gpu_status) > 0:
                gpu_data["load_percent"] = round(float(gpu_status[0]), 1)

        temps = jetson.temperature
        if hasattr(temps, "items"):
            for key, val in temps.items():
                if "gpu" in key.lower():
                    if isinstance(val, dict) and "temp" in val:
                        gpu_data["temp_c"] = round(float(val["temp"]), 1)
                    else:
                        gpu_data["temp_c"] = round(float(val), 1)
                    break
    except ImportError:
        pass
    except Exception as e:
        log.debug(f"jtop GPU 采集出错: {e}")
    finally:
        if jetson is not None:
            try:
                jetson.close()
            except Exception as e:
                log.debug(f"jtop 连接关闭出错: {e}")
    return gpu_data if gpu_data else None


def read_usb_devices() -> Optional[List[str]]:
    """读取 USB 外设列表，过滤掉基础 Hub。"""
    try:
        out = subprocess.check_output(["lsusb"], text=True, stderr=subprocess.DEVNULL, timeout=3)
        devices = []
        for line in out.splitlines():
            if "Linux Foundation" in line or "root hub" in line:
                continue
            try:
                if "ID " in line:
                    name = line.split("ID ")[1].split(" ", 1)[1].strip()
                else:
                    name = line.split(":", 2)[2].strip()
                if name:
                    devices.append(name)
            except IndexError:
                pass
        return devices if devices else None
    except Exception:
        return None


# ── 遥测数据采集 ──────────────────────────────────────────────────────────────

def collect_telemetry(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """收集所有遥测数据，构造上报 payload。"""
    cfg = cfg or {}

    payload: Dict[str, Any] = {
        "status":     "online",
        "reportedAt": datetime.now().isoformat(timespec="seconds"),
    }

    # 电量 & 信号
    battery = read_battery()
    signal = read_signal()
    if battery is not None:
        payload["battery"] = battery
    if signal is not None:
        payload["signal"] = signal

    # GPS（通过 /fix 话题，G70 RTK）
    lat, lng = read_gps()
    gps_status_code = read_gps_status()
    if lat is not None and lng is not None:
        payload["lat"] = lat
        payload["lng"] = lng

    extra: Dict[str, Any] = {}

    # GPS 元信息
    if lat is not None:
        gps_source_label = {2: "RTK_Fix", 1: "SBAS_Fix", 0: "GPS_Fix"}.get(gps_status_code or 0, "Fix")
        extra["gps"] = {
            "status": "fix", 
            "source": "ros:/fix", 
            "fix_type": gps_source_label, 
            "status_code": gps_status_code,
            "message": "通过 ROS /fix 话题获取到有效定位"
        }
        extra["locationSource"] = "ros:/fix"
    else:
        status_label = "no_fix" if gps_status_code is not None else "driver_not_started"
        extra["gps"] = {
            "status": status_label, 
            "source": "ros:/fix", 
            "status_code": gps_status_code,
            "message": "ROS /fix 话题尚未发布有效定位，或 RTK 驱动未启动"
        }
        extra["locationSource"] = "none"

    # CPU 温度（sysfs）
    temp_raw = _read_file("/sys/class/thermal/thermal_zone0/temp")
    if temp_raw and temp_raw.isdigit():
        extra["cpu_temp_c"] = round(int(temp_raw) / 1000, 1)

    # 系统资源（psutil）
    cpu_info = read_cpu_info()
    if cpu_info is not None:
        extra["cpu"] = cpu_info

    memory_info = read_memory_info()
    if memory_info is not None:
        extra["memory"] = memory_info

    disk_info = read_disk_info()
    if disk_info is not None:
        extra["disk"] = disk_info

    network_info = read_network_info()
    if network_info is not None:
        extra["network"] = network_info

    system_info = read_system_info()
    if system_info is not None:
        extra["system"] = system_info

    # 硬件信息（Jetson）
    hw_data = read_hardware_info()
    if hw_data and hw_data.get("info"):
        extra["hardware"] = hw_data["info"]

    # GPU（jtop，Jetson Only）
    gpu_info = read_gpu_info()
    if gpu_info is not None:
        extra["gpu"] = gpu_info

    # USB 外设
    usb_devs = read_usb_devices()
    if usb_devs is not None:
        extra["usb_devices"] = usb_devs

    # ROS 电源详情（/PowerVoltage 等）
    power_info = read_ros_power()
    if power_info is not None:
        extra["power"] = power_info

    # 机器人底盘状态（/chassis_security /robot_selfcheck 等）
    robot_status = read_robot_status()
    if robot_status is not None:
        extra["robot_status"] = robot_status

    # 运动状态（/odom /imu）
    motion_status = read_motion_status()
    if motion_status is not None:
        extra["motion"] = motion_status

    if extra:
        payload["extra"] = extra

    return payload


# ── 配置加载 ──────────────────────────────────────────────────────────────────

def load_config() -> Dict[str, Any]:
    """从命令行 + 配置文件合并参数，命令行优先。"""
    parser = argparse.ArgumentParser(description="ROS1 wheeltec 无人车 IoT 上报客户端")
    parser.add_argument("--server",    default="",  help="公网统一入口，如 http://192.168.31.28:5273")
    parser.add_argument("--token",     default="",  help="设备 Token（从管理后台创建）")
    parser.add_argument("--interval",  type=int, default=0, help="遥测上报间隔秒数，默认 60")
    parser.add_argument("--point-id",  type=int, default=0, help="当前巡检点 ID（0 表示不绑定）")
    parser.add_argument("--route-id",  type=int, default=0, help="当前巡检路线 ID（0 表示不绑定）")
    parser.add_argument("--checkin-only", action="store_true", help="仅执行一次打卡后退出")
    parser.add_argument("--tls-no-verify", action="store_true", help="禁用 HTTPS 证书校验，仅用于受信任的内网调试")
    parser.add_argument("--config",    default=str(CONFIG_FILE), help="配置文件路径")
    args = parser.parse_args()

    cfg = configparser.ConfigParser()
    config_path = Path(args.config)
    if config_path.exists():
        cfg.read(config_path, encoding="utf-8")
        log.info(f"加载配置文件: {config_path}")

    def _get(key: str, default: str = "") -> str:
        return cfg.get("client", key, fallback=default).strip()

    server   = args.server   or _get("server")
    token    = args.token    or _get("token")
    interval = args.interval or int(_get("interval", "60"))
    point_id = args.point_id or int(_get("point_id", "0"))
    route_id = args.route_id or int(_get("route_id", "0"))
    tls_verify = (
        False if args.tls_no_verify
        else _get("tls_verify", "1").lower() in {"1", "true", "yes", "on"}
    )

    if not server:
        log.error("未指定服务器地址，使用 --server 或在配置文件中设置 server=")
        sys.exit(1)
    if not token:
        log.error("未指定设备 Token，使用 --token 或在配置文件中设置 token=")
        sys.exit(1)

    return {
        "server":       server.rstrip("/"),
        "token":        token,
        "interval":     max(interval, 5),
        "point_id":     point_id or None,
        "route_id":     route_id or None,
        "tls_verify":   tls_verify,
        "checkin_only": args.checkin_only,
    }


# ── HTTP 请求封装 ──────────────────────────────────────────────────────────────

def _post(server: str, token: str, path: str, body: Dict[str, Any], tls_verify: bool = True) -> Dict[str, Any]:
    url = f"{server}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type":   "application/json",
            "X-Device-Token": token,
        },
        method="POST",
    )
    request_kwargs: Dict[str, Any] = {"timeout": HTTP_TIMEOUT_SEC}
    if url.lower().startswith("https://") and not tls_verify:
        request_kwargs["context"] = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, **request_kwargs) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body_text}") from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


def send_telemetry(server: str, token: str, payload: Dict[str, Any], tls_verify: bool = True) -> bool:
    """上报遥测数据，返回是否成功。"""
    try:
        result = _post(server, token, "/api/iot/telemetry", payload, tls_verify=tls_verify)
        log.info(f"遥测上报成功: {payload}")
        return result.get("ok", False)
    except RuntimeError as exc:
        log.error(f"遥测上报失败: {exc}")
        return False



def send_checkin(
    server: str,
    token: str,
    point_id: Optional[int] = None,
    route_id: Optional[int] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    note: str = "",
    tls_verify: bool = True,
) -> bool:
    """上报巡检打卡，返回是否成功。"""
    payload: Dict[str, Any] = {"checkedAt": datetime.now().isoformat(timespec="seconds")}
    if point_id:
        payload["pointId"] = point_id
    if route_id:
        payload["routeId"] = route_id
    if lat is not None:
        payload["lat"] = lat
        payload["lng"] = lng
    if note:
        payload["note"] = note
    try:
        result = _post(server, token, "/api/iot/checkin", payload, tls_verify=tls_verify)
        log.info(f"打卡上报成功: point_id={point_id}, route_id={route_id}")
        return result.get("ok", False)
    except RuntimeError as exc:
        log.error(f"打卡上报失败: {exc}")
        return False


# ── 主循环 ────────────────────────────────────────────────────────────────────

def main() -> None:
    cfg = load_config()

    # 初始化 ROS 节点和所有话题订阅
    configure_local_ros_network()
    ros_ok = init_ros_subscribers()
    if ros_ok:
        # 等待第一次电压数据到达（最多 3 秒）
        _wait_start = time.time()
        while _ros_voltage is None and (time.time() - _wait_start) < 3.0:
            time.sleep(0.1)
        if _ros_voltage is not None:
            log.info(f"ROS 电源数据已就绪，当前电压: {_ros_voltage:.2f}V")
        else:
            log.warning("ROS 电源数据未就绪（turn_on_wheeltec_robot.launch 可能未启动）")
            try:
                topic_types = dict(rospy.get_published_topics())
                log.warning("ROS 图中 /PowerVoltage 类型: %s", topic_types.get("/PowerVoltage", "未发现"))
            except Exception as exc:
                log.warning("读取 ROS 话题图失败: %s", exc)
    else:
        log.warning("ROS 未初始化，电量读取将降级为 sysfs，其余 ROS 数据不可用")

    server   = cfg["server"]
    token    = cfg["token"]
    interval = cfg["interval"]
    point_id = cfg["point_id"]
    route_id = cfg["route_id"]

    log.info(
        f"IoT 客户端启动 | 服务器: {server} | 上报间隔: {interval}s"
        f" | TLS 校验: {'启用' if cfg['tls_verify'] else '关闭'}"
    )
    if server.lower().startswith("https://") and not cfg["tls_verify"]:
        log.warning("HTTPS 证书校验已禁用，仅适用于受信任的内网调试环境")

    # 仅打卡模式
    if cfg["checkin_only"]:
        lat, lng = read_gps()
        ok = send_checkin(
            server, token,
            point_id=point_id, route_id=route_id,
            lat=lat, lng=lng,
            tls_verify=bool(cfg["tls_verify"]),
        )
        sys.exit(0 if ok else 1)

    # 启动时先发一次打卡（如需要）
    if point_id or route_id:
        lat, lng = read_gps()
        send_checkin(
            server, token,
            point_id=point_id, route_id=route_id,
            lat=lat, lng=lng,
            note="设备启动打卡",
            tls_verify=bool(cfg["tls_verify"]),
        )

    # 持续遥测循环
    while True:
        telemetry = collect_telemetry(cfg)

        # GPS 状态日志
        gps_status_code = read_gps_status()
        with _ros_lock:
            lat = _ros_gps_lat
            lng = _ros_gps_lng
        if lat is not None:
            fix_type = {2: "RTK_Fix", 1: "SBAS_Fix", 0: "GPS_Fix"}.get(gps_status_code or 0, "Fix")
            log.info(f"GPS 定位成功 [{fix_type}] | 坐标={lat:.7f},{lng:.7f}")
        elif gps_status_code is not None:
            log.warning(f"GPS 无定位 | NavSatStatus={gps_status_code}（/fix 话题已收到，但当前无有效定位）")
        else:
            log.debug("GPS /fix 话题暂无数据（wheeltec_dual_rtk_driver_nmea.launch 可能未启动）")

        sent = send_telemetry(server, token, telemetry, tls_verify=bool(cfg["tls_verify"]))
        next_delay = interval if sent else min(interval, FAILED_REPORT_RETRY_SEC)
        log.info(f"下次上报: {next_delay}s 后")
        time.sleep(next_delay)


if __name__ == "__main__":
    main()
