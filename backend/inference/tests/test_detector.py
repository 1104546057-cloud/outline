"""目标检测器单元测试（M2）。

覆盖：
1. 纯 Python NMS 正确性（重叠抑制、分离保留、空输入）
2. YoloDetector 配置解析（类别过滤、阈值）
3. YoloDetector 输出解码 + 后处理（合成 ONNX 输出 → Detection）
4. 缺权重 / 缺 onnxruntime 时优雅降级（不抛错、返回空）

运行::

    cd backend
    python -m pytest inference/tests/ -v
"""

from __future__ import annotations

import numpy as np
import pytest

from inference.detectors.yolo_detector import COCO_NAMES, YoloDetector
from inference.utils.nms import iou, nms


# ============================================================
# NMS
# ============================================================

class TestNms:
    def test_suppress_overlapping(self):
        boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11]], dtype=float)
        scores = np.array([0.9, 0.5])
        assert nms(boxes, scores, iou_threshold=0.5) == [0]

    def test_keep_disjoint(self):
        boxes = np.array([[0, 0, 10, 10], [20, 20, 30, 30]], dtype=float)
        scores = np.array([0.5, 0.9])
        assert sorted(nms(boxes, scores, iou_threshold=0.5)) == [0, 1]

    def test_empty_input(self):
        assert nms(np.zeros((0, 4)), np.zeros((0,)), 0.5) == []

    def test_iou(self):
        got = iou([0, 0, 10, 10], [5, 5, 15, 15])
        assert abs(got - 25.0 / 175.0) < 1e-6


# ============================================================
# YoloDetector 配置解析
# ============================================================

class TestYoloDetectorConfig:
    def test_class_filter_resolution(self):
        assert YoloDetector._resolve_class_ids(["person", "car", "nonsense"]) == [0, 2]
        assert YoloDetector._resolve_class_ids(None) is None
        assert YoloDetector._resolve_class_ids([]) is None

    def test_explicit_params_override(self):
        det = YoloDetector(model_name="yolo_v8n", conf_threshold=0.7, iou_threshold=0.3, classes=["person"])
        assert det.conf_threshold == 0.7
        assert det.iou_threshold == 0.3
        assert det._class_filter_ids == [0]

    def test_coco_names_length(self):
        assert len(COCO_NAMES) == 80
        assert COCO_NAMES[0] == "person"


# ============================================================
# 输出解码 + 后处理
# ============================================================

def _synthetic_output():
    """构造一个 (84, 2) 的 YOLO 输出：一个人 + 一辆车。"""
    out = np.zeros((84, 2), dtype=np.float32)
    # 第 0 列：person（class 0），框 (75,75,125,125)，分数 0.9
    out[0, 0], out[1, 0], out[2, 0], out[3, 0] = 100, 100, 50, 50
    out[4, 0] = 0.9
    # 第 1 列：car（class 2），框 (200,200,300,300)，分数 0.8
    out[0, 1], out[1, 1], out[2, 1], out[3, 1] = 250, 250, 100, 100
    out[4 + 2, 1] = 0.8
    return out


class TestYoloPostprocess:
    def test_decode_output_orientation(self):
        det = YoloDetector(model_name="test", conf_threshold=0.5)
        xyxy, scores = det._decode_output(_synthetic_output())
        assert xyxy.shape == (2, 4)
        assert scores.shape == (2, 80)

    def test_postprocess_person(self):
        det = YoloDetector(model_name="test", conf_threshold=0.5, classes=["person"])
        dets = det.postprocess(_synthetic_output())
        assert len(dets) == 1
        assert dets[0].class_name == "person"
        assert dets[0].class_id == 0
        assert abs(dets[0].bbox[0] - 75) < 1e-3
        assert abs(dets[0].bbox[2] - 125) < 1e-3
        assert abs(dets[0].confidence - 0.9) < 1e-3

    def test_postprocess_all_classes(self):
        det = YoloDetector(model_name="test", conf_threshold=0.5)
        dets = det.postprocess(_synthetic_output())
        names = {d.class_name for d in dets}
        assert names == {"person", "car"}

    def test_conf_threshold_filters(self):
        det = YoloDetector(model_name="test", conf_threshold=0.85)
        dets = det.postprocess(_synthetic_output())
        assert len(dets) == 1  # 只有 0.9 的 person 通过


# ============================================================
# 优雅降级
# ============================================================

class TestYoloDegradation:
    def test_no_weights_unavailable(self):
        det = YoloDetector(model_name="yolo_v8n", weights=None)
        det.setup()
        assert det.available is False
        assert det.detect(b"not-a-jpeg") == []

    def test_detect_returns_empty_when_unavailable(self):
        det = YoloDetector(model_name="yolo_v8n", weights="models/nonexistent.onnx")
        # 未 setup() 时 session 为空，detect 直接返回空
        assert det.detect(np.zeros((64, 64, 3), dtype=np.uint8)) == []
