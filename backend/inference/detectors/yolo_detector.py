"""YOLOv8 目标检测器（ONNX Runtime 推理）。

设计要点（见 docs/plans/video-analysis-module-plan.md §3.2 / 风险 R1、R2）：
- 走纯 ONNX 链路（onnxruntime + opencv），不引入 ultralytics/PyTorch，体积可控；
- onnxruntime / 模型权重 / cv2 均惰性加载：缺失时优雅降级为"不可用"，
  让管线仍可启动（detect 返回空），避免远端部署缺模型时拖垮服务；
- 输出解码 + NMS 为纯 numpy，可脱离模型做单元测试。

配置见 inference.yaml 的 models.<name>（weights / classes / conf_threshold / iou_threshold）。
"""

from __future__ import annotations

from typing import Any

from inference.base import BaseDetector, Detection, Frame
from inference.config import inference_config
from inference.registry import detector_registry
from inference.utils.decode import decode_jpeg, is_ndarray
from inference.utils.nms import nms

# COCO 80 类（YOLOv8 默认）
COCO_NAMES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]


class YoloDetector(BaseDetector):
    """ONNX YOLOv8 检测器。"""

    def __init__(
        self,
        model_name: str = "yolo_v8n",
        weights: str | None = None,
        classes: list[str] | None = None,
        conf_threshold: float | None = None,
        iou_threshold: float | None = None,
        input_size: int = 640,
        num_classes: int = 80,
        **kwargs,  # noqa: ARG002
    ) -> None:
        model_cfg = inference_config.get_models().get(model_name, {}) or {}

        self.model_name = model_name
        self.weights = weights or model_cfg.get("weights")
        self.conf_threshold = float(conf_threshold if conf_threshold is not None else model_cfg.get("conf_threshold", 0.5))
        self.iou_threshold = float(iou_threshold if iou_threshold is not None else model_cfg.get("iou_threshold", 0.45))
        self.input_size = int(input_size)
        self.num_classes = int(num_classes)
        self.class_names = COCO_NAMES[: self.num_classes]

        self._classes = classes if classes is not None else model_cfg.get("classes")
        self._class_filter_ids = self._resolve_class_ids(self._classes)

        self._session: Any = None
        self._available = False

    # ===== 生命周期 =====

    def setup(self) -> None:
        """加载 ONNX 会话；缺少 onnxruntime / 权重时降级为不可用。"""
        if not self.weights:
            print(f"[inference] YOLO 检测器 '{self.model_name}' 未配置权重，跳过加载")
            return
        try:
            import onnxruntime as ort
        except Exception as exc:  # noqa: BLE001
            print(f"[inference] 未安装 onnxruntime，YOLO 检测器 '{self.model_name}' 不可用: {exc}")
            return
        try:
            self._session = ort.InferenceSession(self.weights, providers=["CPUExecutionProvider"])
            self._available = True
            print(f"[inference] YOLO 检测器 '{self.model_name}' 已加载: {self.weights}")
        except Exception as exc:  # noqa: BLE001
            print(f"[inference] YOLO 检测器 '{self.model_name}' 权重加载失败: {exc}")

    def teardown(self) -> None:
        self._session = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    # ===== 推理 =====

    def detect(self, frame: Frame) -> list[Detection]:
        if not self._available or self._session is None:
            return []
        if not is_ndarray(frame):
            frame = decode_jpeg(frame)
            if not is_ndarray(frame):
                return []
        try:
            blob = self._preprocess(frame)
            outputs = self._session.run(None, {self._input_name(): blob})[0]
            return self.postprocess(outputs, frame.shape)
        except Exception as exc:  # noqa: BLE001 - 单帧失败不拖垮管线
            print(f"[inference] YOLO 检测 '{self.model_name}' 失败: {exc}")
            return []

    # ===== 预处理 / 后处理 =====

    def _input_name(self) -> str:
        return self._session.get_inputs()[0].name

    def _preprocess(self, img: Any) -> Any:
        import cv2

        blob = cv2.dnn.blobFromImage(
            img,
            scalefactor=1.0 / 255.0,
            size=(self.input_size, self.input_size),
            swapRB=True,
            crop=False,
        )
        return blob

    def _decode_output(self, output: Any) -> tuple[Any, Any]:
        """把模型原始输出解码为 (N,4) xyxy 框 + (N,num_classes) 分数。"""
        import numpy as np

        out = np.asarray(output, dtype=np.float32)
        if out.ndim == 3:
            out = out[0]  # (C, N)
        if out.ndim != 2:
            raise ValueError(f"YOLO 输出形状异常: {output.shape if hasattr(output, 'shape') else '?'}")
        # ultralytics 导出通常为 (4+num_classes, N)，转置为 (N, 4+num_classes)
        if out.shape[0] == 4 + self.num_classes:
            out = out.T

        boxes = out[:, :4].copy()
        scores = out[:, 4 : 4 + self.num_classes].copy()

        cx = boxes[:, 0]
        cy = boxes[:, 1]
        w = boxes[:, 2]
        h = boxes[:, 3]
        xyxy = np.stack([cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0], axis=1)
        return xyxy, scores

    def postprocess(self, output: Any, frame_shape: tuple | None = None) -> list[Detection]:
        """把模型输出解码为 Detection 列表（阈值过滤 + NMS，纯 numpy）。"""
        import numpy as np

        xyxy, scores = self._decode_output(output)

        class_ids = self._class_filter_ids or range(self.num_classes)
        detections: list[Detection] = []
        for cls_id in class_ids:
            cls_scores = scores[:, cls_id]
            keep = cls_scores > self.conf_threshold
            if not np.any(keep):
                continue
            boxes = xyxy[keep]
            confs = cls_scores[keep]
            for i in nms(boxes, confs, self.iou_threshold):
                x1, y1, x2, y2 = (float(v) for v in boxes[i])
                detections.append(
                    Detection(
                        bbox=(x1, y1, x2, y2),
                        confidence=float(confs[i]),
                        class_name=self.class_names[cls_id],
                        class_id=int(cls_id),
                    )
                )
        return detections

    @staticmethod
    def _resolve_class_ids(classes: list[str] | None) -> list[int] | None:
        """把类别名列表映射为类别 id 列表；未知名称忽略。"""
        if not classes:
            return None
        ids = []
        for name in classes:
            if name in COCO_NAMES:
                ids.append(COCO_NAMES.index(name))
        return ids or None


# 注册常见模型名（同一实现，按 model_name 读取对应权重配置）
detector_registry.register_class("yolo_v8n", YoloDetector)
detector_registry.register_class("yolo_v8s", YoloDetector)
