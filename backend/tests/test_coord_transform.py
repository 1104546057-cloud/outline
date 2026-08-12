"""
coord_transform 单元测试

测试覆盖：
  1. WGS84 ↔ ENU 双向转换的数学正确性（与已知参考点对比）
  2. ENU ↔ map 在 yaw_offset=0 与非零时的旋转正确性
  3. 复合转换 wgs84_to_map 的可逆性（与 map_to_wgs84 互逆）
  4. CoordTransformer 的转换日志记录完整性
  5. Calibration 的边界检查（经纬度越界）

运行方式：
  cd backend
  python -m pytest tests/test_coord_transform.py -v
  或直接：
  python tests/test_coord_transform.py

不依赖 SQLAlchemy 或项目其它模块，纯函数测试。
"""

from __future__ import annotations

import math
import os
import sys

# 让脚本可独立运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.coord_transform import (
    Calibration,
    CoordTransformer,
    TransformEndpoint,
    enu_to_map,
    enu_to_wgs84,
    map_to_enu,
    map_to_wgs84,
    wgs84_to_enu,
    wgs84_to_map,
)


# 校园参考点：北京中关村附近（纯测试用，非实际校园坐标）
CAMPUS_LAT = 39.9847
CAMPUS_LON = 116.3074

CAL = Calibration(
    version="test-campus-v1",
    origin_lat=CAMPUS_LAT,
    origin_lng=CAMPUS_LON,
    origin_alt=50.0,
    yaw_offset=0.0,
)

CAL_ROTATED = Calibration(
    version="test-campus-v2-rotated",
    origin_lat=CAMPUS_LAT,
    origin_lng=CAMPUS_LON,
    origin_alt=50.0,
    yaw_offset=math.radians(90.0),  # 顺时针 90°
)


def approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def test_wgs84_to_enu_origin():
    """原点的 ENU 应为 (0, 0, 0)（传入原点 alt 时 up=0）"""
    e, n, u = wgs84_to_enu(CAMPUS_LAT, CAMPUS_LON, CAL, alt=CAL.origin_alt)
    assert approx(e, 0.0, 1e-3), f"原点 east 不为零: {e}"
    assert approx(n, 0.0, 1e-3), f"原点 north 不为零: {n}"
    assert approx(u, 0.0, 1e-3), f"原点 up 不为零: {u}"
    # 默认 alt=0 时 up 应为 -origin_alt
    _, _, u_default = wgs84_to_enu(CAMPUS_LAT, CAMPUS_LON, CAL)
    assert approx(u_default, -CAL.origin_alt, 1e-6)
    print("[PASS] 原点 ENU = (0,0,0)")


def test_wgs84_to_enu_known_offset():
    """向北走 1 角秒 ≈ 31 米"""
    one_arcsec = 1.0 / 3600.0
    lat_north = CAMPUS_LAT + one_arcsec
    e, n, u = wgs84_to_enu(lat_north, CAMPUS_LON, CAL)
    assert 30.0 < n < 32.0, f"北向 1 角秒应为 ~31m，实际 {n}"
    assert approx(e, 0.0, 0.1), f"东向应近 0，实际 {e}"
    print(f"[PASS] 北向 1\" = {n:.2f} m")


def test_wgs84_to_enu_east_offset():
    """向东走 1 角秒 ≈ 24 米（在中纬度 40°）"""
    one_arcsec = 1.0 / 3600.0
    lon_east = CAMPUS_LON + one_arcsec
    e, n, u = wgs84_to_enu(CAMPUS_LAT, lon_east, CAL)
    assert 23.0 < e < 25.0, f"东向 1 角秒应为 ~24m，实际 {e}"
    assert approx(n, 0.0, 0.1), f"北向应近 0，实际 {n}"
    print(f"[PASS] 东向 1\" = {e:.2f} m")


def test_enu_to_wgs84_roundtrip():
    """ENU → WGS84 → ENU 应可逆"""
    e0, n0 = 100.0, 200.0
    lat, lon, alt = enu_to_wgs84(e0, n0, CAL, up=10.0)
    e1, n1, u1 = wgs84_to_enu(lat, lon, CAL, alt=alt)
    assert approx(e0, e1, 1e-6), f"east roundtrip 失败: {e0} → {e1}"
    assert approx(n0, n1, 1e-6), f"north roundtrip 失败: {n0} → {n1}"
    assert approx(10.0, u1, 1e-6), f"up roundtrip 失败"
    print(f"[PASS] ENU<->WGS84 roundtrip: ({e0},{n0}) -> ({lat},{lon}) -> ({e1:.4f},{n1:.4f})")


def test_enu_to_map_identity():
    """yaw_offset=0 时 ENU 与 map 重合"""
    x, y = enu_to_map(100.0, 200.0, CAL)
    assert approx(x, 100.0) and approx(y, 200.0)
    print("[PASS] yaw_offset=0 时 map = ENU")


def test_enu_to_map_90deg_rotation():
    """yaw_offset=90° 时 (E, N) → (-N, E)"""
    x, y = enu_to_map(100.0, 200.0, CAL_ROTATED)
    assert approx(x, -200.0, 1e-9), f"x 应为 -200，实际 {x}"
    assert approx(y, 100.0, 1e-9), f"y 应为 100，实际 {y}"
    print(f"[PASS] yaw_offset=90° 旋转: (100, 200) -> ({x}, {y})")


def test_map_to_enu_inverse_rotation():
    """map → ENU 应为 enu_to_map 的逆"""
    e, n = map_to_enu(-200.0, 100.0, CAL_ROTATED)
    assert approx(e, 100.0, 1e-9)
    assert approx(n, 200.0, 1e-9)
    print(f"[PASS] map->ENU 逆旋转: (-200, 100) -> ({e}, {n})")


def test_wgs84_to_map_roundtrip():
    """WGS84 → map → WGS84 应可逆"""
    lat0, lon0 = CAMPUS_LAT + 0.001, CAMPUS_LON + 0.001
    x, y = wgs84_to_map(lat0, lon0, CAL_ROTATED)
    lat1, lon1 = map_to_wgs84(x, y, CAL_ROTATED)
    assert approx(lat0, lat1, 1e-9), f"lat roundtrip: {lat0} → {lat1}"
    assert approx(lon0, lon1, 1e-9), f"lon roundtrip: {lon0} → {lon1}"
    print("[PASS] WGS84->map->WGS84 roundtrip under 90° rotation")


def test_calibration_validation():
    """Calibration 经纬度越界应抛 ValueError"""
    try:
        Calibration(version="bad", origin_lat=200.0, origin_lng=0.0)
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "origin_lat" in str(e)
        print(f"[PASS] Calibration 边界检查: {e}")


def test_coord_transformer_logging():
    """CoordTransformer 应累积转换记录"""
    tx = CoordTransformer(CAL)
    _, r1 = tx.wgs84_to_enu(CAMPUS_LAT + 0.001, CAMPUS_LON)
    _, r2 = tx.wgs84_to_map(CAMPUS_LAT + 0.002, CAMPUS_LON)

    records = tx.export_records()
    assert len(records) == 2, f"应有 2 条记录，实际 {len(records)}"
    assert records[0]["source_type"] == "wgs84"
    assert records[0]["target_type"] == "enu"
    assert records[0]["calibration_version"] == "test-campus-v1"
    assert records[1]["target_type"] == "map"
    assert "lat" in records[0]["source_values"]
    assert "east" in records[0]["target_values"]
    assert records[0]["endpoint"] == "backend"
    print(f"[PASS] CoordTransformer 日志: {len(records)} 条，含版本与坐标类型")


def test_coord_transformer_endpoint():
    """endpoint=agent 时记录中应反映"""
    tx = CoordTransformer(CAL, endpoint=TransformEndpoint.AGENT)
    _, _ = tx.enu_to_wgs84(10.0, 20.0)
    rec = tx.export_records()[0]
    assert rec["endpoint"] == "agent"
    print("[PASS] endpoint=agent 正确记录")


def run_all():
    """一次性运行全部测试"""
    tests = [
        test_wgs84_to_enu_origin,
        test_wgs84_to_enu_known_offset,
        test_wgs84_to_enu_east_offset,
        test_enu_to_wgs84_roundtrip,
        test_enu_to_map_identity,
        test_enu_to_map_90deg_rotation,
        test_map_to_enu_inverse_rotation,
        test_wgs84_to_map_roundtrip,
        test_calibration_validation,
        test_coord_transformer_logging,
        test_coord_transformer_endpoint,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n=== {passed} passed, {failed} failed ===")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
