#!/usr/bin/env python3
"""
iot_client.py — 树莓派巡检机器人设备端上报客户端
========================================================
功能：
  1. 定期（默认 60 秒）上报遥测数据（电量、信号、GPS）到后端
  2. GPS 不可用时，按配置尝试网络定位 fallback
  3. 检测到巡检点时，调用打卡接口

用法：
  python3 iot_client.py --server https://<公网域名> --token <设备Token>

配置文件（可选，与脚本同目录的 iot_client.conf）：
  [client]
  server   = https://example.com
  token    = <从管理后台 /api/iot/tokens 获取的 Token>
  interval = 60
  point_id = 1
  route_id = 1
"""


import argparse
import configparser
import json
import logging
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import smbus
    SMBUS_AVAILABLE = True
except ImportError:
    SMBUS_AVAILABLE = False

# ── 日志 ──────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("iot_client")

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "iot_client.conf"
COMMON_GPS_SERIAL_DEVICES = ("/dev/serial0", "/dev/ttyAMA0", "/dev/serial1", "/dev/ttyS0", "/dev/ttyUSB0")


# ── 配置加载 ──────────────────────────────────────────────────────────────────
def load_config() -> Dict[str, Any]:
    """从命令行 + 配置文件合并参数，命令行优先。"""
    parser = argparse.ArgumentParser(description="树莓派 IoT 上报客户端")
    parser.add_argument("--server", default="", help="公网统一入口，如 https://example.com")
    parser.add_argument("--token", default="", help="设备 Token（从管理后台创建）")
    parser.add_argument("--interval", type=int, default=0, help="遥测上报间隔秒数，默认 60")
    parser.add_argument("--point-id", type=int, default=0, help="当前巡检点 ID（0 表示不绑定）")
    parser.add_argument("--route-id", type=int, default=0, help="当前巡检路线 ID（0 表示不绑定）")
    parser.add_argument("--checkin-only", action="store_true", help="仅执行一次打卡后退出")
    parser.add_argument("--gps-diagnose", action="store_true", help="执行一次 GPS 诊断并输出结果后退出")
    parser.add_argument("--gps-timeout", type=int, default=0, help="GPS 命令读取超时秒数，默认 5")
    parser.add_argument("--gps-serial-device", default="", help="GPS 串口设备，如 /dev/ttyAMA0")
    parser.add_argument("--gps-serial-baud", type=int, default=0, help="GPS 串口波特率，默认 9600")
    parser.add_argument("--gps-log-every", type=int, default=0, help="GPS 失败时每隔多少轮重复打印一次告警，默认 10")
    parser.add_argument("--network-locate-enabled", action="store_true", help="启用网络定位 fallback")
    parser.add_argument("--network-provider", default="", help="网络定位 provider，当前支持 google")
    parser.add_argument("--network-api-key", default="", help="网络定位 API Key")
    parser.add_argument("--network-api-url", default="", help="网络定位 API URL")
    parser.add_argument("--network-timeout", type=int, default=0, help="网络定位请求超时秒数，默认 10")
    parser.add_argument("--network-interface", default="", help="扫描 Wi-Fi 的网卡名，默认 wlan0")
    parser.add_argument("--network-consider-ip", type=int, default=-1, help="网络定位时是否允许按公网 IP 粗定位，1/0")
    parser.add_argument("--tls-no-verify", action="store_true", help="禁用 HTTPS 证书校验，仅用于受信任的内网调试")
    parser.add_argument("--config", default=str(CONFIG_FILE), help="配置文件路径")
    args = parser.parse_args()

    # 读取配置文件
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
    gps_timeout = args.gps_timeout or int(_get("gps_timeout", "5"))
    gps_serial_device = args.gps_serial_device or _get("gps_serial_device")
    gps_serial_baud = args.gps_serial_baud or int(_get("gps_serial_baud", "9600"))
    gps_log_every = args.gps_log_every or int(_get("gps_log_every", "10"))
    network_locate_enabled = args.network_locate_enabled or _get("network_locate_enabled", "0") in {"1", "true", "yes", "on"}
    network_provider = args.network_provider or _get("network_provider", "google")
    network_api_key = args.network_api_key or _get("network_api_key")
    network_api_url = args.network_api_url or _get("network_api_url", "https://www.googleapis.com/geolocation/v1/geolocate")
    network_timeout = args.network_timeout or int(_get("network_timeout", "10"))
    network_interface = args.network_interface or _get("network_interface", "wlan0")
    network_consider_ip_raw = args.network_consider_ip if args.network_consider_ip >= 0 else _get("network_consider_ip", "1")
    network_consider_ip = str(network_consider_ip_raw).strip().lower() in {"1", "true", "yes", "on"}
    tls_verify = False if args.tls_no_verify else _get("tls_verify", "1").strip().lower() in {"1", "true", "yes", "on"}

    if not server:
        log.error("未指定服务器地址，使用 --server 或在配置文件中设置 server=")
        sys.exit(1)
    if not token:
        log.error("未指定设备 Token，使用 --token 或在配置文件中设置 token=")
        sys.exit(1)

    return {
        "server":      server.rstrip("/"),
        "token":       token,
        "interval":    max(interval, 5),
        "point_id":    point_id or None,
        "route_id":    route_id or None,
        "gps_timeout": max(gps_timeout, 1),
        "gps_serial_device": gps_serial_device.strip(),
        "gps_serial_baud": max(gps_serial_baud, 1200),
        "gps_log_every": max(gps_log_every, 1),
        "network_locate_enabled": network_locate_enabled,
        "network_provider": network_provider.strip().lower() or "google",
        "network_api_key": network_api_key.strip(),
        "network_api_url": network_api_url.strip(),
        "network_timeout": max(network_timeout, 1),
        "network_interface": network_interface.strip() or "wlan0",
        "network_consider_ip": network_consider_ip,
        "tls_verify": tls_verify,
        "checkin_only": args.checkin_only,
        "gps_diagnose": args.gps_diagnose,
    }


# ── 硬件信息读取（树莓派专用，其他平台降级返回 None）────────────────────────────
def _read_file(path: str) -> Optional[str]:
    try:
        return Path(path).read_text().strip()
    except Exception:
        return None


# ── INA219 UPS 电量读取 ───────────────────────────────────────────────────────
# 参考 INA219.py，通过 I2C 读取 UPS HAT 的电压/电流/功率并换算电量百分比。
# 硬件不存在或 smbus 未安装时会优雅降级。

_REG_CONFIG_INA219         = 0x00
_REG_SHUNTVOLTAGE_INA219   = 0x01
_REG_BUSVOLTAGE_INA219     = 0x02
_REG_POWER_INA219          = 0x03
_REG_CURRENT_INA219        = 0x04
_REG_CALIBRATION_INA219    = 0x05

# 全局 INA219 实例缓存，避免每次遥测都重新初始化
_ina219_instance: Optional[Any] = None
_ina219_init_failed: bool = False


def _ina219_read_reg(bus, addr: int, register: int) -> int:
    """从 INA219 寄存器读取 16 位值。"""
    data = bus.read_i2c_block_data(addr, register, 2)
    return (data[0] << 8) | data[1]


def _ina219_write_reg(bus, addr: int, register: int, value: int) -> None:
    """向 INA219 寄存器写入 16 位值。"""
    bus.write_i2c_block_data(addr, register, [(value >> 8) & 0xFF, value & 0xFF])


def _get_ina219():
    """
    获取 INA219 I2C 总线实例。
    首次调用时初始化并缓存，初始化失败后不再重试。
    返回 (bus, addr) 或 None。
    """
    global _ina219_instance, _ina219_init_failed

    if _ina219_init_failed:
        return None
    if _ina219_instance is not None:
        return _ina219_instance

    if not SMBUS_AVAILABLE:
        _ina219_init_failed = True
        log.debug("smbus 模块不可用，跳过 INA219 UPS 电量读取")
        return None

    # 尝试常见的 INA219 I2C 地址
    i2c_bus_num = 1
    candidate_addrs = [0x42, 0x40, 0x41, 0x43]

    try:
        bus = smbus.SMBus(i2c_bus_num)
    except Exception as exc:
        _ina219_init_failed = True
        log.debug(f"无法打开 I2C 总线 {i2c_bus_num}，跳过 INA219: {exc}")
        return None

    for addr in candidate_addrs:
        try:
            # 尝试读取配置寄存器来探测设备是否存在
            bus.read_i2c_block_data(addr, _REG_CONFIG_INA219, 2)

            # 设备存在，执行校准（32V/2A 配置，与 INA219.py 一致）
            cal_value = 4096
            config = (
                0x01 << 13 |  # BusVoltageRange: 32V
                0x03 << 11 |  # Gain: /8, 320mV
                0x0D << 7  |  # Bus ADC: 12bit, 32 samples
                0x0D << 3  |  # Shunt ADC: 12bit, 32 samples
                0x07          # Mode: shunt and bus continuous
            )
            _ina219_write_reg(bus, addr, _REG_CALIBRATION_INA219, cal_value)
            _ina219_write_reg(bus, addr, _REG_CONFIG_INA219, config)

            _ina219_instance = (bus, addr)
            log.info(f"INA219 UPS 初始化成功，I2C 地址: 0x{addr:02X}")
            return _ina219_instance
        except Exception:
            continue

    _ina219_init_failed = True
    log.debug("未检测到 INA219 设备，跳过 UPS 电量读取")
    return None


def read_ups_ina219() -> Optional[Dict[str, Any]]:
    """
    通过 INA219 读取 UPS HAT 电源信息。
    返回包含 voltage, current, power, percent 的字典，或在硬件不可用时返回 None。
    电量百分比换算：参考 INA219.py，假设锂电池放电范围 6V ~ 8.4V。
    """
    ina = _get_ina219()
    if ina is None:
        return None

    bus, addr = ina
    cal_value = 4096
    current_lsb = 0.1      # 100uA per bit
    power_lsb = 0.002      # 2mW per bit

    try:
        # 写入校准寄存器（每次读取前重写以确保一致性，与 INA219.py 行为一致）
        _ina219_write_reg(bus, addr, _REG_CALIBRATION_INA219, cal_value)

        # 读取总线电压（负载侧）
        _ina219_read_reg(bus, addr, _REG_BUSVOLTAGE_INA219)  # 第一次读取丢弃
        raw_bus = _ina219_read_reg(bus, addr, _REG_BUSVOLTAGE_INA219)
        bus_voltage = (raw_bus >> 3) * 0.004  # V

        # 读取电流
        raw_current = _ina219_read_reg(bus, addr, _REG_CURRENT_INA219)
        if raw_current > 32767:
            raw_current -= 65535
        current_mA = raw_current * current_lsb  # mA

        # 读取功率
        _ina219_write_reg(bus, addr, _REG_CALIBRATION_INA219, cal_value)
        raw_power = _ina219_read_reg(bus, addr, _REG_POWER_INA219)
        if raw_power > 32767:
            raw_power -= 65535
        power_W = raw_power * power_lsb  # W

        # 电量百分比：锂电池放电曲线近似线性映射（6V ~ 8.4V）
        percent = (bus_voltage - 6) / 2.4 * 100
        percent = max(0.0, min(100.0, percent))

        return {
            "voltage_V": round(bus_voltage, 3),
            "current_A": round(current_mA / 1000, 6),
            "power_W": round(power_W, 3),
            "percent": round(percent, 1),
        }
    except Exception as exc:
        log.warning(f"INA219 读取失败: {exc}")
        return None


def read_battery() -> Optional[int]:
    """
    读取电量百分比。
    优先从 sysfs 读取（标准 Linux 电池驱动），
    若不可用则尝试通过 INA219 I2C 读取 UPS HAT 电压并换算百分比。
    均不可用时返回 None。
    """
    # 方式 1：标准 sysfs
    raw = _read_file("/sys/class/power_supply/BAT0/capacity")
    if raw and raw.isdigit():
        return int(raw)

    # 方式 2：INA219 UPS HAT
    ups_data = read_ups_ina219()
    if ups_data is not None:
        return int(ups_data["percent"])

    return None


def _wifi_signal_percent(dbm: float) -> int:
    return int(max(0, min(100, 2 * (dbm + 100))))


def read_signal(interface: str = "wlan0") -> Optional[int]:
    """
    读取 Wi-Fi 信号强度（RSSI），转换为 0~100 百分比。
    优先使用 iw，兼容回退到 iwconfig。
    """
    interface = interface.strip() or "wlan0"
    attempts = (
        (["iw", "dev", interface, "link"], r"signal:\s*(-?\d+(?:\.\d+)?)\s*dBm"),
        (["iwconfig", interface], r"Signal\s+level[=:]\s*(-?\d+(?:\.\d+)?)\s*dBm"),
    )
    errors: List[str] = []
    for command, pattern in attempts:
        result = _run_command(command, 3)
        output = f"{result.get('stdout') or ''}\n{result.get('stderr') or ''}"
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return _wifi_signal_percent(float(match.group(1)))
        error = str(result.get("stderr") or "").strip()
        if error:
            errors.append(f"{command[0]}: {error}")
    log.warning(
        "Wi-Fi 信号读取失败 | 网卡=%s | %s",
        interface,
        " | ".join(errors) or "未找到 RSSI，请确认无线网卡已连接",
    )
    return None


# ── 系统信息采集（基于 psutil，适用于树莓派）─────────────────────────────────

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
        partitions = psutil.disk_partitions(all=False)
        for part in partitions:
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
        # 网卡状态
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
        # 系统负载（仅 Linux/Unix）
        if hasattr(os, "getloadavg"):
            load = os.getloadavg()
            data["load_avg"] = {
                "1min": round(load[0], 2),
                "5min": round(load[1], 2),
                "15min": round(load[2], 2),
            }
        # 主机名
        try:
            data["hostname"] = os.uname().nodename
        except AttributeError:
            import platform
            data["hostname"] = platform.node()
        return data if data else None
    except Exception:
        return None


def read_pi_hardware() -> Optional[Dict[str, Any]]:
    """尝试使用 pinout 命令读取树莓派硬件详情（型号、SoC、RAM等）以及引脚图"""
    try:
        out = subprocess.check_output(
            ["pinout"], universal_newlines=True, stderr=subprocess.DEVNULL, timeout=5
        )
        hw_list = []
        diagram_lines = []
        is_diagram = False
        
        for line in out.splitlines():
            stripped = line.strip()
            if not is_diagram:
                # 空行或者以 ,--- 开头表示属性读取结束，图形开始
                if not stripped or stripped.startswith(",---"):
                    is_diagram = True
                    if stripped:
                        diagram_lines.append(line)
                    continue
                    
                if ":" in stripped:
                    parts = stripped.split(":", 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip()
                        hw_list.append({"label": key, "value": val})
            else:
                # 收集图形行，但忽略末尾的帮助文档链接
                if "For further information" in line or "pinout.xyz" in line:
                    continue
                diagram_lines.append(line)
                
        # 移除末尾多余的空行
        while diagram_lines and not diagram_lines[-1].strip():
            diagram_lines.pop()
            
        diagram = "\n".join(diagram_lines) if diagram_lines else None
        
        if hw_list or diagram:
            return {"info": hw_list if hw_list else None, "diagram": diagram}
        return None
    except Exception:
        # 降级：如果 pinout 失败，仅读取 model 文件
        try:
            model = _read_file("/sys/firmware/devicetree/base/model")
            if model:
                return {"info": [{"label": "Description", "value": model.strip('\x00')}], "diagram": None}
        except Exception:
            pass
        return None


def read_gpu_info() -> Optional[Dict[str, Any]]:
    """读取 Jetson GPU 使用率、频率和温度；非 Jetson 或未安装 jtop 时返回 None。"""
    gpu_data: Dict[str, Any] = {}
    jetson = None
    try:
        from jtop import jtop

        jetson = jtop()
        jetson.start()

        gpu_status = jetson.gpu
        if hasattr(gpu_status, "items"):
            for _, info in gpu_status.items():
                if not isinstance(info, dict):
                    continue
                status = info.get("status")
                if isinstance(status, dict) and "load" in status:
                    gpu_data["load_percent"] = round(float(status["load"]), 1)
                elif "val" in info:
                    gpu_data["load_percent"] = round(float(info["val"]), 1)
                elif "load" in info:
                    gpu_data["load_percent"] = round(float(info["load"]), 1)

                freq_info = info.get("freq")
                if isinstance(freq_info, dict):
                    current_freq = freq_info.get("cur")
                    max_freq = freq_info.get("max")
                    if current_freq is not None:
                        current_freq = float(current_freq)
                        gpu_data["freq_current_mhz"] = round(
                            current_freq / 1000.0 if current_freq > 10000 else current_freq,
                            1,
                        )
                    if max_freq is not None:
                        max_freq = float(max_freq)
                        gpu_data["freq_max_mhz"] = round(
                            max_freq / 1000.0 if max_freq > 10000 else max_freq,
                            1,
                        )
        elif isinstance(gpu_status, (int, float)):
            gpu_data["load_percent"] = round(float(gpu_status), 1)
        elif isinstance(gpu_status, (tuple, list)) and gpu_status:
            gpu_data["load_percent"] = round(float(gpu_status[0]), 1)

        temperatures = jetson.temperature
        if hasattr(temperatures, "items"):
            for name, value in temperatures.items():
                if "gpu" not in name.lower():
                    continue
                if isinstance(value, dict) and "temp" in value:
                    gpu_data["temp_c"] = round(float(value["temp"]), 1)
                else:
                    gpu_data["temp_c"] = round(float(value), 1)
                break
    except ImportError:
        pass
    except Exception as exc:
        log.debug(f"jtop GPU 采集出错: {exc}")
    finally:
        if jetson is not None:
            try:
                jetson.close()
            except Exception as exc:
                log.debug(f"jtop 连接关闭出错: {exc}")
    return gpu_data if gpu_data else None


def read_usb_devices() -> Optional[List[str]]:
    """读取 USB 外设列表，过滤掉基础 Hub"""
    try:
        out = subprocess.check_output(
            ["lsusb"], universal_newlines=True, stderr=subprocess.DEVNULL, timeout=3
        )
        devices = []
        for line in out.splitlines():
            # 过滤掉系统自带的 root hub 和常见内置 hub
            if "Linux Foundation" in line or "root hub" in line:
                continue
            # 提取名称，例如从: "Bus 001 Device 004: ID 32e6:9005 icSpring icspring camera" 中提取
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


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def normalize_mac_address(value: str) -> str:
    return value.strip().lower().replace("-", ":")


def is_universally_administered_mac(mac: str) -> bool:
    try:
        first_octet = int(normalize_mac_address(mac).split(":", 1)[0], 16)
    except Exception:
        return False
    return (first_octet & 0x02) == 0


def parse_iwlist_scan_output(output: str) -> List[Dict[str, Any]]:
    wifi_points: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}

    def flush() -> None:
        if not current:
            return
        mac = normalize_mac_address(str(current.get("macAddress") or ""))
        if not mac or not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
            current.clear()
            return
        if not is_universally_administered_mac(mac):
            current.clear()
            return
        point: Dict[str, Any] = {"macAddress": mac}
        if current.get("signalStrength") is not None:
            point["signalStrength"] = int(current["signalStrength"])
        if current.get("channel") is not None:
            point["channel"] = int(current["channel"])
        wifi_points.append(point)
        current.clear()

    for raw_line in output.splitlines():
        line = raw_line.strip()
        address_match = re.search(r"Address:\s*([0-9A-Fa-f:-]{17})", line)
        if address_match:
            flush()
            current["macAddress"] = address_match.group(1)
            continue
        signal_match = re.search(r"Signal level=([-]?\d+)\s*dBm", line)
        if signal_match:
            current["signalStrength"] = int(signal_match.group(1))
            continue
        channel_match = re.search(r"Channel:(\d+)", line)
        if channel_match:
            current["channel"] = int(channel_match.group(1))
            continue
        frequency_match = re.search(r"Frequency:([0-9.]+)\s*GHz", line)
        if frequency_match and current.get("channel") is None:
            freq_ghz = float(frequency_match.group(1))
            if 2.4 <= freq_ghz <= 2.5:
                current["channel"] = max(1, round((freq_ghz - 2.412) / 0.005) + 1)

    flush()
    return wifi_points


def scan_wifi_access_points(interface: str, timeout: int) -> Dict[str, Any]:
    result = _run_command(["iwlist", interface, "scan"], timeout)
    if not result["ok"] and result["stderr"] == "command not found":
        return {"status": "iwlist_missing", "message": "未安装 iwlist，无法扫描周边 Wi-Fi", "wifiAccessPoints": []}

    output = str(result["stdout"] or "")
    wifi_points = parse_iwlist_scan_output(output)
    if wifi_points:
        return {
            "status": "ok",
            "message": f"扫描到 {len(wifi_points)} 个可上报的 Wi-Fi 热点",
            "wifiAccessPoints": wifi_points,
        }
    if result["stderr"]:
        return {
            "status": "scan_error",
            "message": str(result["stderr"]).strip(),
            "wifiAccessPoints": [],
        }
    return {
        "status": "scan_empty",
        "message": f"网卡 {interface} 未扫描到可用于定位的 Wi-Fi 热点",
        "wifiAccessPoints": [],
    }


def build_gps_report(
    status: str,
    source: str,
    *,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    message: str = "",
    sample: Optional[List[str]] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "status": status,
        "source": source,
        "lat": lat,
        "lng": lng,
        "message": message.strip(),
    }
    if sample:
        report["sample"] = sample[:5]
    if details:
        report.update(details)
    return report


def _run_command(command: List[str], timeout: int) -> Dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "code": result.returncode,
        }
    except FileNotFoundError:
        return {"ok": False, "stdout": "", "stderr": "command not found", "code": None}
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return {"ok": False, "stdout": stdout, "stderr": stderr or "timeout", "code": None}
    except Exception as exc:
        return {"ok": False, "stdout": "", "stderr": str(exc), "code": None}


def parse_nmea_coordinate(raw: str, hemisphere: str) -> Optional[float]:
    raw = raw.strip()
    hemisphere = hemisphere.strip().upper()
    if not raw or not hemisphere:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    degree_width = 2 if hemisphere in {"N", "S"} else 3
    raw_digits = raw.split(".", 1)[0]
    if len(raw_digits) <= degree_width:
        return None
    degrees = int(raw[:degree_width])
    minutes = value - (degrees * 100)
    decimal = degrees + minutes / 60.0
    if hemisphere in {"S", "W"}:
        decimal *= -1
    return round(decimal, 7)


def parse_nmea_sentence(line: str) -> Tuple[Optional[float], Optional[float]]:
    parts = line.strip().split(",")
    if len(parts) < 7:
        return None, None

    sentence_type = parts[0].upper()
    if sentence_type.endswith("GGA"):
        if len(parts) < 6 or parts[6] in {"", "0"}:
            return None, None
        lat = parse_nmea_coordinate(parts[2], parts[3])
        lng = parse_nmea_coordinate(parts[4], parts[5])
        return lat, lng

    if sentence_type.endswith("RMC"):
        if len(parts) < 7 or parts[2].upper() != "A":
            return None, None
        lat = parse_nmea_coordinate(parts[3], parts[4])
        lng = parse_nmea_coordinate(parts[5], parts[6])
        return lat, lng

    return None, None


def probe_gps_via_gpspipe(timeout: int) -> Dict[str, Any]:
    result = _run_command(["gpspipe", "-w", "-n", "10"], timeout)
    if not result["ok"] and result["stderr"] == "command not found":
        return build_gps_report("gpspipe_missing", "gpspipe-json", message="未安装 gpspipe/gpsd-clients")

    output = str(result["stdout"] or "")
    classes: List[str] = []
    tpv_seen = False
    for line in output.splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        obj_class = str(obj.get("class") or "").strip()
        if obj_class:
            classes.append(obj_class)
        if obj_class == "TPV":
            tpv_seen = True
            lat = obj.get("lat")
            lng = obj.get("lon")
            if lat is not None and lng is not None:
                return build_gps_report("fix", "gpspipe-json", lat=float(lat), lng=float(lng), message="通过 gpspipe TPV 获取到坐标")

    unique_classes = ", ".join(dict.fromkeys(classes)) if classes else "无输出"
    if tpv_seen:
        return build_gps_report("no_fix", "gpspipe-json", message=f"gpspipe 已返回 TPV，但当前没有有效经纬度；类: {unique_classes}")
    if output.strip():
        return build_gps_report("no_data", "gpspipe-json", message=f"gpspipe 仅返回 {unique_classes}", sample=output.splitlines())
    if result["stderr"]:
        return build_gps_report("gpspipe_error", "gpspipe-json", message=str(result["stderr"]).strip())
    return build_gps_report("no_data", "gpspipe-json", message="gpspipe 没有返回任何内容")


def probe_gps_via_raw_nmea(timeout: int) -> Dict[str, Any]:
    result = _run_command(["gpspipe", "-r", "-n", "20"], timeout)
    if not result["ok"] and result["stderr"] == "command not found":
        return build_gps_report("gpspipe_missing", "gpspipe-raw", message="未安装 gpspipe/gpsd-clients")

    output = str(result["stdout"] or "")
    nmea_lines = [line.strip() for line in output.splitlines() if line.strip().startswith("$")]
    for line in nmea_lines:
        lat, lng = parse_nmea_sentence(line)
        if lat is not None and lng is not None:
            return build_gps_report("fix", "gpspipe-raw", lat=lat, lng=lng, message="通过 gpspipe 原始 NMEA 获取到坐标")

    if nmea_lines:
        return build_gps_report("nmea_no_fix", "gpspipe-raw", message=f"已读到 {len(nmea_lines)} 条 NMEA，但当前没有有效定位", sample=nmea_lines)
    if result["stderr"]:
        return build_gps_report("gpspipe_error", "gpspipe-raw", message=str(result["stderr"]).strip())
    return build_gps_report("no_data", "gpspipe-raw", message="gpspipe 原始模式没有读到 NMEA 数据")


def _serial_lines(device: str, baud: int, timeout: int) -> List[str]:
    try:
        import termios
    except ImportError as exc:
        raise RuntimeError("当前系统不支持 termios，无法直接诊断串口") from exc

    if not Path(device).exists():
        raise FileNotFoundError(device)

    speed_attr = getattr(termios, f"B{baud}", None)
    if speed_attr is None:
        raise RuntimeError(f"当前系统 termios 不支持波特率 {baud}")

    fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    original = termios.tcgetattr(fd)
    updated = termios.tcgetattr(fd)
    try:
        updated[0] = 0
        updated[1] = 0
        updated[2] = termios.CLOCAL | termios.CREAD | termios.CS8
        updated[3] = 0
        updated[4] = speed_attr
        updated[5] = speed_attr
        updated[6][termios.VMIN] = 0
        updated[6][termios.VTIME] = 1
        termios.tcflush(fd, termios.TCIFLUSH)
        termios.tcsetattr(fd, termios.TCSANOW, updated)

        deadline = time.monotonic() + timeout
        buffer = b""
        lines: List[str] = []
        while time.monotonic() < deadline and len(lines) < 40:
            try:
                chunk = os.read(fd, 1024)
            except BlockingIOError:
                chunk = b""
            if chunk:
                buffer += chunk
                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    text = raw_line.decode("ascii", errors="ignore").strip()
                    if text:
                        lines.append(text)
            else:
                time.sleep(0.1)
        if buffer.strip():
            lines.append(buffer.decode("ascii", errors="ignore").strip())
        return lines
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSANOW, original)
        finally:
            os.close(fd)


def probe_gps_via_serial(device: str, baud: int, timeout: int) -> Dict[str, Any]:
    try:
        lines = _serial_lines(device, baud, timeout)
    except FileNotFoundError:
        return build_gps_report("device_missing", f"serial:{device}", message=f"串口设备不存在: {device}")
    except Exception as exc:
        return build_gps_report("serial_error", f"serial:{device}", message=str(exc))

    nmea_lines = [line for line in lines if line.startswith("$")]
    for line in nmea_lines:
        lat, lng = parse_nmea_sentence(line)
        if lat is not None and lng is not None:
            return build_gps_report("fix", f"serial:{device}", lat=lat, lng=lng, message=f"直接从串口 {device} 读取到 NMEA 定位")

    if nmea_lines:
        return build_gps_report("nmea_no_fix", f"serial:{device}", message=f"串口 {device} 有 NMEA 输出，但没有有效定位", sample=nmea_lines)
    if lines:
        return build_gps_report("serial_noise", f"serial:{device}", message=f"串口 {device} 有输出，但不是标准 NMEA", sample=lines)
    return build_gps_report("serial_silent", f"serial:{device}", message=f"串口 {device} 没有任何输出")


def serial_probe_supported() -> bool:
    try:
        import termios  # noqa: F401
    except ImportError:
        return False
    return True


def get_gps_report(
    *,
    timeout: int = 5,
    serial_device: str = "/dev/ttyUSB0",
    serial_baud: int = 38400,
    include_serial_fallback: bool = False,
    auto_probe_serial: bool = False,
) -> Dict[str, Any]:
    attempts: List[Dict[str, str]] = []

    report = probe_gps_via_gpspipe(timeout)
    attempts.append({"source": report["source"], "status": report["status"], "message": report["message"]})
    if report["lat"] is not None and report["lng"] is not None:
        report["attempts"] = attempts
        return report

    raw_report = probe_gps_via_raw_nmea(timeout)
    attempts.append({"source": raw_report["source"], "status": raw_report["status"], "message": raw_report["message"]})
    if raw_report["lat"] is not None and raw_report["lng"] is not None:
        raw_report["attempts"] = attempts
        return raw_report

    selected = raw_report if raw_report["status"] not in {"gpspipe_missing", "no_data"} else report

    if include_serial_fallback:
        candidates = [serial_device] if serial_device else list(COMMON_GPS_SERIAL_DEVICES if auto_probe_serial else [])
        if candidates and not serial_probe_supported():
            if serial_device:
                serial_report = build_gps_report(
                    "serial_unsupported",
                    f"serial:{serial_device}",
                    message="当前系统不支持 termios，无法直接诊断串口",
                )
                attempts.append({"source": serial_report["source"], "status": serial_report["status"], "message": serial_report["message"]})
                selected = serial_report
        else:
            for candidate in candidates:
                serial_report = probe_gps_via_serial(candidate, serial_baud, max(1, min(timeout, 3)))
                attempts.append({"source": serial_report["source"], "status": serial_report["status"], "message": serial_report["message"]})
                if serial_report["lat"] is not None and serial_report["lng"] is not None:
                    serial_report["attempts"] = attempts
                    return serial_report
                if serial_report["status"] not in {"device_missing"}:
                    selected = serial_report

    selected["attempts"] = attempts
    return selected


def read_gps(
    *,
    timeout: int = 5,
    serial_device: str = "",
    serial_baud: int = 9600,
    include_serial_fallback: bool = False,
) -> Tuple[Optional[float], Optional[float]]:
    report = get_gps_report(
        timeout=timeout,
        serial_device=serial_device,
        serial_baud=serial_baud,
        include_serial_fallback=include_serial_fallback,
        auto_probe_serial=False,
    )
    return report["lat"], report["lng"]


def geolocate_with_google(
    api_url: str,
    api_key: str,
    wifi_access_points: List[Dict[str, Any]],
    timeout: int,
    consider_ip: bool,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"considerIp": consider_ip}
    if wifi_access_points:
        body["wifiAccessPoints"] = wifi_access_points
    query = urllib.parse.urlencode({"key": api_key})
    request = urllib.request.Request(
        f"{api_url}?{query}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        return build_gps_report(
            "provider_error",
            "network:google",
            message=f"Google Geolocation API 返回 HTTP {exc.code}: {response_text.strip()}",
            details={"wifiCount": len(wifi_access_points), "considerIp": consider_ip},
        )
    except Exception as exc:
        return build_gps_report(
            "provider_error",
            "network:google",
            message=str(exc),
            details={"wifiCount": len(wifi_access_points), "considerIp": consider_ip},
        )

    location = payload.get("location") or {}
    lat = location.get("lat")
    lng = location.get("lng")
    accuracy = payload.get("accuracy")
    if lat is None or lng is None:
        return build_gps_report(
            "provider_empty",
            "network:google",
            message="Google Geolocation API 未返回坐标",
            details={"wifiCount": len(wifi_access_points), "considerIp": consider_ip},
        )
    return build_gps_report(
        "fix",
        "network:google",
        lat=float(lat),
        lng=float(lng),
        message="网络定位成功",
        details={
            "provider": "google",
            "accuracyMeters": float(accuracy) if accuracy is not None else None,
            "wifiCount": len(wifi_access_points),
            "considerIp": consider_ip,
        },
    )


def get_network_location_report(cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not parse_bool(cfg.get("network_locate_enabled"), False):
        return build_gps_report("disabled", "network", message="未启用网络定位 fallback")

    provider = str(cfg.get("network_provider") or "google").strip().lower()
    if provider != "google":
        return build_gps_report("unsupported_provider", f"network:{provider or 'unknown'}", message="当前仅支持 google provider")

    api_key = str(cfg.get("network_api_key") or "").strip()
    if not api_key:
        return build_gps_report("missing_api_key", "network:google", message="未配置 Google Geolocation API Key")

    scan_report = scan_wifi_access_points(str(cfg.get("network_interface") or "wlan0"), int(cfg.get("network_timeout", 10)))
    wifi_access_points = list(scan_report.get("wifiAccessPoints") or [])
    consider_ip = parse_bool(cfg.get("network_consider_ip"), True)
    if not wifi_access_points and not consider_ip:
        return build_gps_report(
            "no_wifi_data",
            "network:google",
            message=scan_report.get("message", "没有可用 Wi-Fi 数据，且已禁用 IP 粗定位"),
        )

    report = geolocate_with_google(
        api_url=str(cfg.get("network_api_url") or "https://www.googleapis.com/geolocation/v1/geolocate"),
        api_key=api_key,
        wifi_access_points=wifi_access_points,
        timeout=int(cfg.get("network_timeout", 10)),
        consider_ip=consider_ip,
    )
    report["wifiScanStatus"] = scan_report.get("status")
    if scan_report.get("message") and report.get("status") != "fix":
        report["message"] = f"{report.get('message', '').strip()} | {scan_report['message']}".strip(" |")
    return report


def collect_telemetry(cfg: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """收集本机遥测数据，构造上报 payload。"""
    cfg = cfg or {}
    gps_report = get_gps_report(
        timeout=int(cfg.get("gps_timeout", 5)),
        serial_device=str(cfg.get("gps_serial_device", "")),
        serial_baud=int(cfg.get("gps_serial_baud", 9600)),
        include_serial_fallback=bool(cfg.get("gps_serial_device")),
        auto_probe_serial=False,
    )
    network_report: Optional[Dict[str, Any]] = None
    location_report = gps_report
    payload: Dict[str, Any] = {
        "status":     "online",
        "reportedAt": datetime.now().isoformat(timespec="seconds"),
    }
    battery = read_battery()
    signal = read_signal(str(cfg.get("network_interface") or "wlan0"))
    if battery is not None:
        payload["battery"] = battery
    if signal is not None:
        payload["signal"] = signal
    if gps_report["lat"] is not None:
        payload["lat"] = gps_report["lat"]
        payload["lng"] = gps_report["lng"]
    elif parse_bool(cfg.get("network_locate_enabled"), False):
        network_report = get_network_location_report(cfg)
        if network_report.get("lat") is not None and network_report.get("lng") is not None:
            payload["lat"] = network_report["lat"]
            payload["lng"] = network_report["lng"]
            location_report = network_report
        else:
            location_report = network_report

    # 扩展字段：CPU 温度（树莓派专有）
    temp_raw = _read_file("/sys/class/thermal/thermal_zone0/temp")
    extra: Dict[str, Any] = {}
    if temp_raw and temp_raw.isdigit():
        extra["cpu_temp_c"] = round(int(temp_raw) / 1000, 1)

    extra["gps"] = {
        "status": gps_report["status"],
        "source": gps_report["source"],
        "message": gps_report["message"],
    }
    if network_report is not None:
        extra["networkLocation"] = {
            "status": network_report["status"],
            "source": network_report["source"],
            "message": network_report["message"],
            "accuracyMeters": network_report.get("accuracyMeters"),
            "wifiCount": network_report.get("wifiCount"),
            "wifiScanStatus": network_report.get("wifiScanStatus"),
        }
    extra["locationSource"] = location_report["source"] if location_report.get("lat") is not None else "none"

    # ── 新增：系统状态信息采集（基于 psutil）──
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

    hw_data = read_pi_hardware()
    if hw_data is not None:
        if hw_data.get("info"):
            extra["hardware"] = hw_data["info"]
        if hw_data.get("diagram"):
            extra["hw_diagram"] = hw_data["diagram"]

    # Jetson GPU（可选依赖 jtop；非 Jetson 平台自动跳过）
    gpu_info = read_gpu_info()
    if gpu_info is not None:
        extra["gpu"] = gpu_info

    usb_devs = read_usb_devices()
    if usb_devs is not None:
        extra["usb_devices"] = usb_devs

    # UPS 电源详情（INA219）
    ups_info = read_ups_ina219()
    if ups_info is not None:
        extra["ups"] = ups_info

    if extra:
        payload["extra"] = extra

    return payload, location_report


def format_gps_report(report: Dict[str, Any]) -> str:
    parts = [f"状态={report['status']}", f"来源={report['source']}"]
    if report.get("lat") is not None and report.get("lng") is not None:
        parts.append(f"坐标={report['lat']:.7f},{report['lng']:.7f}")
    if report.get("accuracyMeters") is not None:
        parts.append(f"精度≈{int(round(float(report['accuracyMeters'])))}m")
    if report.get("message"):
        parts.append(f"说明={report['message']}")
    return " | ".join(parts)


def log_gps_report(report: Dict[str, Any], state: Dict[str, Any], repeat_every: int) -> None:
    signature = f"{report['status']}|{report['source']}|{report.get('message', '')}"
    if report.get("lat") is not None and report.get("lng") is not None:
        if state.get("last_signature") != signature:
            label = "GPS 定位成功" if str(report.get("source", "")).startswith("gps") or "serial:" in str(report.get("source", "")) else "定位成功"
            log.info(f"{label} | {format_gps_report(report)}")
        state["last_signature"] = signature
        state["fail_count"] = 0
        return

    fail_count = int(state.get("fail_count", 0)) + 1
    state["fail_count"] = fail_count
    should_log = state.get("last_signature") != signature or fail_count == 1 or fail_count % repeat_every == 0
    if should_log:
        label = "定位失败"
        log.warning(f"{label} | {format_gps_report(report)}")
    state["last_signature"] = signature


def run_gps_diagnose(cfg: Dict[str, Any]) -> int:
    report = get_gps_report(
        timeout=int(cfg["gps_timeout"]),
        serial_device=str(cfg["gps_serial_device"]),
        serial_baud=int(cfg["gps_serial_baud"]),
        include_serial_fallback=True,
        auto_probe_serial=True,
    )
    payload = {
        "ok": report.get("lat") is not None and report.get("lng") is not None,
        "report": report,
        "config": {
            "gps_timeout": cfg["gps_timeout"],
            "gps_serial_device": cfg["gps_serial_device"],
            "gps_serial_baud": cfg["gps_serial_baud"],
        },
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 2


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
    request_kwargs: Dict[str, Any] = {"timeout": 10}
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
    server   = cfg["server"]
    token    = cfg["token"]
    interval = cfg["interval"]
    point_id = cfg["point_id"]
    route_id = cfg["route_id"]
    gps_state: Dict[str, Any] = {"last_signature": "", "fail_count": 0}

    log.info(
        f"IoT 客户端启动 | 服务器: {server} | 上报间隔: {interval}s | GPS 超时: {cfg['gps_timeout']}s"
        f" | GPS 串口: {cfg['gps_serial_device'] or '未配置'} | 串口波特率: {cfg['gps_serial_baud']}"
        f" | 网络定位: {'启用' if cfg['network_locate_enabled'] else '关闭'}"
        f" | TLS 校验: {'启用' if cfg['tls_verify'] else '关闭'}"
    )
    if server.lower().startswith("https://") and not cfg["tls_verify"]:
        log.warning("HTTPS 证书校验已禁用，仅适用于受信任的内网调试环境")

    if cfg["gps_diagnose"]:
        sys.exit(run_gps_diagnose(cfg))

    # 仅打卡模式
    if cfg["checkin_only"]:
        lat, lng = read_gps(
            timeout=int(cfg["gps_timeout"]),
            serial_device=str(cfg["gps_serial_device"]),
            serial_baud=int(cfg["gps_serial_baud"]),
            include_serial_fallback=bool(cfg["gps_serial_device"]),
        )
        ok = send_checkin(server, token, point_id=point_id, route_id=route_id, lat=lat, lng=lng, tls_verify=bool(cfg["tls_verify"]))
        sys.exit(0 if ok else 1)

    # 启动时先发一次打卡（如需要）
    if point_id or route_id:
        lat, lng = read_gps(
            timeout=int(cfg["gps_timeout"]),
            serial_device=str(cfg["gps_serial_device"]),
            serial_baud=int(cfg["gps_serial_baud"]),
            include_serial_fallback=bool(cfg["gps_serial_device"]),
        )
        send_checkin(
            server,
            token,
            point_id=point_id,
            route_id=route_id,
            lat=lat,
            lng=lng,
            note="设备启动打卡",
            tls_verify=bool(cfg["tls_verify"]),
        )

    # 持续遥测循环
    while True:
        telemetry, gps_report = collect_telemetry(cfg)
        log_gps_report(gps_report, gps_state, int(cfg["gps_log_every"]))
        send_telemetry(server, token, telemetry, tls_verify=bool(cfg["tls_verify"]))
        log.info(f"下次上报: {interval}s 后")
        time.sleep(interval)


if __name__ == "__main__":
    main()
