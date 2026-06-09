#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# depthnet_trt.py - 纯 TensorRT + OpenCV 深度估计（不依赖 jetson-inference）
#
# 这个脚本仅使用 JetPack 自带的 TensorRT 和 OpenCV，
# 完全不需要安装 jetson-inference 库。
#
# 适用于 jetson-inference 的 pip wheel 不可用的情况。
#
# 用法:
#   python3 depthnet_trt.py --model models/MonoDepth-FCN-Mobilenet/monodepth_fcn_mobilenet.onnx --input /dev/video0
#   python3 depthnet_trt.py --model models/MonoDepth-FCN-Mobilenet/monodepth_fcn_mobilenet.onnx --input image.jpg --output depth.jpg
#
# 依赖（JetPack 自带）:
#   - TensorRT (tensorrt Python 包)
#   - PyCUDA (pycuda)
#   - OpenCV (cv2)
#   - NumPy
#

import os
import sys
import time
import argparse
import threading
import numpy as np

try:
    import cv2
except ImportError:
    print("[ERROR] 未找到 OpenCV，请安装: sudo apt-get install python3-opencv")
    sys.exit(1)

try:
    import tensorrt as trt
except ImportError:
    print("[ERROR] 未找到 TensorRT Python 包。")
    print("  请确认你在 Jetson Nano 上运行，且已安装 JetPack。")
    print("  尝试: sudo apt-get install python3-libnvinfer python3-libnvinfer-dev")
    sys.exit(1)

try:
    import pycuda.driver as cuda
    import pycuda.autoinit
except ImportError:
    print("[ERROR] 未找到 PyCUDA，请安装: pip3 install pycuda")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════
#  TensorRT 引擎管理
# ══════════════════════════════════════════════════════════════

TRT_LOGGER = trt.Logger(trt.Logger.WARNING)


def build_engine_from_onnx(onnx_path, engine_path=None, fp16=True):
    """
    从 ONNX 模型构建 TensorRT 引擎。
    首次构建会耗时几分钟，构建完成后会缓存引擎文件。
    
    Args:
        onnx_path: ONNX 模型路径
        engine_path: 引擎缓存路径（默认与 ONNX 同目录）
        fp16: 是否启用 FP16 精度（推荐）
    
    Returns:
        TensorRT ICudaEngine 对象
    """
    if engine_path is None:
        engine_path = onnx_path.replace('.onnx', '.engine')
    
    # 如果引擎文件已存在，直接加载
    if os.path.exists(engine_path):
        print(f"[INFO] 加载缓存的 TensorRT 引擎: {engine_path}")
        runtime = trt.Runtime(TRT_LOGGER)
        with open(engine_path, 'rb') as f:
            engine = runtime.deserialize_cuda_engine(f.read())
        return engine
    
    print(f"[INFO] 从 ONNX 构建 TensorRT 引擎（首次运行需要几分钟）...")
    print(f"[INFO] ONNX 模型: {onnx_path}")
    
    builder = trt.Builder(TRT_LOGGER)
    network_flags = 1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
    network = builder.create_network(network_flags)
    parser = trt.OnnxParser(network, TRT_LOGGER)
    
    # 解析 ONNX 模型
    with open(onnx_path, 'rb') as f:
        if not parser.parse(f.read()):
            for error in range(parser.num_errors):
                print(f"[ERROR] ONNX 解析错误: {parser.get_error(error)}")
            sys.exit(1)
    
    # 配置构建器
    config = builder.create_builder_config()
    config.max_workspace_size = 1 << 28  # 256MB（Jetson Nano 内存有限）
    
    if fp16 and builder.platform_has_fast_fp16:
        config.set_flag(trt.BuilderFlag.FP16)
        print("[INFO] 启用 FP16 精度")
    
    # 构建引擎
    print("[INFO] 正在构建引擎，请耐心等待...")
    engine = builder.build_engine(network, config)
    
    if engine is None:
        print("[ERROR] 引擎构建失败！")
        sys.exit(1)
    
    # 缓存引擎文件
    with open(engine_path, 'wb') as f:
        f.write(engine.serialize())
    print(f"[INFO] 引擎已缓存到: {engine_path}")
    
    return engine


class DepthEstimator:
    """基于 TensorRT 的深度估计器"""
    
    def __init__(self, engine):
        self.engine = engine
        self.context = engine.create_execution_context()
        
        # 获取输入/输出绑定信息
        self.input_idx = engine.get_binding_index("input_0")
        self.output_idx = engine.get_binding_index("output_0")
        
        self.input_shape = engine.get_binding_shape(self.input_idx)
        self.output_shape = engine.get_binding_shape(self.output_idx)
        
        # 输入尺寸: [batch, channels, height, width]
        self.input_h = self.input_shape[2]
        self.input_w = self.input_shape[3]
        
        # 输出尺寸: [batch, 1, height, width]
        self.output_h = self.output_shape[2]
        self.output_w = self.output_shape[3]
        
        print(f"[INFO] 模型输入尺寸:  {self.input_w}x{self.input_h}")
        print(f"[INFO] 深度图输出尺寸: {self.output_w}x{self.output_h}")
        
        # 分配 CUDA 内存
        self.input_size = trt.volume(self.input_shape) * np.dtype(np.float32).itemsize
        self.output_size = trt.volume(self.output_shape) * np.dtype(np.float32).itemsize
        
        self.d_input = cuda.mem_alloc(self.input_size)
        self.d_output = cuda.mem_alloc(self.output_size)
        
        self.h_output = np.empty(trt.volume(self.output_shape), dtype=np.float32)
        
        self.stream = cuda.Stream()
        
        # 性能统计
        self.frame_times = []
    
    def preprocess(self, img):
        """
        预处理输入图像:
        1. 缩放到模型输入尺寸
        2. BGR → RGB
        3. 归一化到 [0, 1]
        4. 转换为 NCHW 格式
        """
        img_resized = cv2.resize(img, (self.input_w, self.input_h))
        img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        img_float = img_rgb.astype(np.float32) / 255.0
        
        # HWC → CHW → NCHW
        img_chw = np.transpose(img_float, (2, 0, 1))
        img_nchw = np.expand_dims(img_chw, axis=0)
        
        return np.ascontiguousarray(img_nchw)
    
    def infer(self, img):
        """
        执行深度推理。
        
        Args:
            img: OpenCV BGR 图像 (numpy array)
        
        Returns:
            depth_map: 深度图 (numpy array, float32, HxW)
        """
        t_start = time.time()
        
        # 预处理
        input_data = self.preprocess(img)
        
        # 拷贝输入到 GPU
        cuda.memcpy_htod_async(self.d_input, input_data, self.stream)
        
        # 执行推理
        self.context.execute_async_v2(
            bindings=[int(self.d_input), int(self.d_output)],
            stream_handle=self.stream.handle
        )
        
        # 拷贝输出回 CPU
        cuda.memcpy_dtoh_async(self.h_output, self.d_output, self.stream)
        self.stream.synchronize()
        
        # 重塑输出
        depth_map = self.h_output.reshape(self.output_h, self.output_w)
        
        t_end = time.time()
        self.frame_times.append(t_end - t_start)
        
        return depth_map
    
    def get_fps(self):
        """获取平均 FPS"""
        if len(self.frame_times) == 0:
            return 0.0
        avg_time = sum(self.frame_times[-30:]) / min(len(self.frame_times), 30)
        return 1.0 / avg_time if avg_time > 0 else 0.0
    
    def __del__(self):
        """释放 CUDA 资源"""
        try:
            self.d_input.free()
            self.d_output.free()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════
#  线程化视频捕获（解决 HTTP 流帧率不匹配问题）
# ══════════════════════════════════════════════════════════════

class ThreadedVideoCapture:
    """
    使用独立线程持续抓取视频帧，始终保留最新一帧。
    
    解决的问题：
      当推理速度（如 48 FPS）远超视频源帧率（如 15 FPS）时，
      OpenCV 的内部缓冲区会堆积旧帧，导致 cap.read() 读取到的
      是过时的帧，造成画面延迟和跳帧。
      
    原理：
      独立的抓帧线程以最快速度读取帧，每次都覆盖上一帧，
      主线程通过 read() 方法始终获取最新帧。
    """
    
    def __init__(self, cap):
        """
        Args:
            cap: 已打开的 cv2.VideoCapture 对象
        """
        self.cap = cap
        self.lock = threading.Lock()
        self.frame = None
        self.ret = False
        self.running = True
        
        # 先读一帧确保可用
        self.ret, self.frame = self.cap.read()
        
        # 启动抓帧守护线程
        self.thread = threading.Thread(target=self._grab_loop, daemon=True)
        self.thread.start()
    
    def _grab_loop(self):
        """持续抓取最新帧的后台线程"""
        while self.running:
            ret, frame = self.cap.read()
            with self.lock:
                self.ret = ret
                self.frame = frame
            if not ret:
                break
    
    def read(self):
        """获取最新帧（非阻塞，返回当前缓存的最新帧）"""
        with self.lock:
            return self.ret, self.frame.copy() if self.frame is not None else None
    
    def isOpened(self):
        return self.cap.isOpened()
    
    def get(self, prop):
        return self.cap.get(prop)
    
    def set(self, prop, value):
        return self.cap.set(prop, value)
    
    def release(self):
        self.running = False
        if self.thread.is_alive():
            self.thread.join(timeout=2.0)
        self.cap.release()


# ══════════════════════════════════════════════════════════════
#  可视化
# ══════════════════════════════════════════════════════════════

# OpenCV 颜色映射表
COLORMAP_TABLE = {
    "viridis": cv2.COLORMAP_VIRIDIS,
    "viridis-inverted": cv2.COLORMAP_VIRIDIS,
    "inferno": cv2.COLORMAP_INFERNO,
    "inferno-inverted": cv2.COLORMAP_INFERNO,
    "magma": cv2.COLORMAP_MAGMA,
    "magma-inverted": cv2.COLORMAP_MAGMA,
    "plasma": cv2.COLORMAP_PLASMA,
    "plasma-inverted": cv2.COLORMAP_PLASMA,
    "turbo": cv2.COLORMAP_TURBO if hasattr(cv2, 'COLORMAP_TURBO') else cv2.COLORMAP_JET,
    "turbo-inverted": cv2.COLORMAP_TURBO if hasattr(cv2, 'COLORMAP_TURBO') else cv2.COLORMAP_JET,
    "parula": cv2.COLORMAP_PARULA if hasattr(cv2, 'COLORMAP_PARULA') else cv2.COLORMAP_VIRIDIS,
    "parula-inverted": cv2.COLORMAP_PARULA if hasattr(cv2, 'COLORMAP_PARULA') else cv2.COLORMAP_VIRIDIS,
}


def visualize_depth(depth_map, colormap_name="viridis-inverted", target_size=None):
    """
    将原始深度图转换为可视化彩色图像。
    使用直方图均衡化增强对比度。
    
    Args:
        depth_map: 原始深度图 (float32)
        colormap_name: 颜色映射方案名称
        target_size: 目标尺寸 (width, height)，None 表示不缩放
    
    Returns:
        colored_depth: 彩色深度图 (uint8, BGR)
    """
    # 归一化到 [0, 255]
    depth_min = np.min(depth_map)
    depth_max = np.max(depth_map)
    
    if depth_max - depth_min > 0:
        depth_normalized = (depth_map - depth_min) / (depth_max - depth_min)
    else:
        depth_normalized = np.zeros_like(depth_map)
    
    # 如果是 inverted 模式，翻转深度值
    if "inverted" in colormap_name:
        depth_normalized = 1.0 - depth_normalized
    
    depth_uint8 = (depth_normalized * 255).astype(np.uint8)
    
    # 直方图均衡化（增强对比度）
    depth_uint8 = cv2.equalizeHist(depth_uint8)
    
    # 应用颜色映射
    cv_colormap = COLORMAP_TABLE.get(colormap_name, cv2.COLORMAP_VIRIDIS)
    colored_depth = cv2.applyColorMap(depth_uint8, cv_colormap)
    
    # 缩放到目标尺寸
    if target_size is not None:
        colored_depth = cv2.resize(colored_depth, target_size)
    
    return colored_depth


# ══════════════════════════════════════════════════════════════
#  主程序
# ══════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="纯 TensorRT 单目深度估计（不依赖 jetson-inference）",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument("--model", type=str, required=True,
                        help="ONNX 模型文件路径")
    
    parser.add_argument("--input", type=str, default="/dev/video0",
                        help="输入源:\n"
                             "  /dev/video0 - USB 摄像头\n"
                             "  0           - 默认摄像头\n"
                             "  image.jpg   - 图片文件\n"
                             "  video.mp4   - 视频文件\n"
                             "  http://...  - HTTP/MJPEG 视频流")
    
    parser.add_argument("--output", type=str, default="display",
                        help="输出目标:\n"
                             "  display     - 屏幕显示\n"
                             "  output.jpg  - 保存图片\n"
                             "  output.mp4  - 保存视频")
    
    parser.add_argument("--colormap", type=str, default="viridis-inverted",
                        choices=list(COLORMAP_TABLE.keys()),
                        help="颜色映射方案（默认 viridis-inverted）")
    
    parser.add_argument("--depth-size", type=float, default=1.0,
                        help="深度图缩放比例（默认 1.0）")
    
    parser.add_argument("--no-fp16", action="store_true",
                        help="禁用 FP16 精度（使用 FP32）")
    
    parser.add_argument("--visualize", type=str, default="input,depth",
                        help="可视化模式: input, depth, input,depth")
    
    parser.add_argument("--fps", type=float, default=0,
                        help="目标帧率限制（默认 0 = 不限制）\n"
                             "  对 HTTP 视频流建议设为源帧率（如 15）\n"
                             "  设为 0 则以推理速度全速运行")
    
    return parser.parse_args()


def is_image_file(path):
    """判断是否为图片文件"""
    ext = os.path.splitext(path)[1].lower()
    return ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp']


def is_video_file(path):
    """判断是否为视频文件"""
    ext = os.path.splitext(path)[1].lower()
    return ext in ['.mp4', '.avi', '.mkv', '.mov', '.flv', '.wmv']


def main():
    args = parse_args()
    
    print("=" * 60)
    print("  FastDepth (TensorRT) - 单目深度估计")
    print("=" * 60)
    print(f"  模型: {args.model}")
    print(f"  输入: {args.input}")
    print(f"  输出: {args.output}")
    print("=" * 60)
    
    # ── 构建/加载 TensorRT 引擎 ──
    engine = build_engine_from_onnx(args.model, fp16=not args.no_fp16)
    estimator = DepthEstimator(engine)
    
    show_input = "input" in args.visualize
    show_depth = "depth" in args.visualize
    
    # ── 判断输入类型 ──
    input_path = args.input
    
    if is_image_file(input_path):
        # === 图片模式 ===
        print(f"\n[INFO] 处理图片: {input_path}")
        
        img = cv2.imread(input_path)
        if img is None:
            print(f"[ERROR] 无法读取图片: {input_path}")
            sys.exit(1)
        
        depth_map = estimator.infer(img)
        
        h, w = img.shape[:2]
        depth_size = (int(w * args.depth_size), int(h * args.depth_size))
        colored_depth = visualize_depth(depth_map, args.colormap, target_size=depth_size)
        
        # 合成输出
        if show_input and show_depth:
            # 确保高度一致
            if colored_depth.shape[0] != img.shape[0]:
                colored_depth = cv2.resize(colored_depth, (colored_depth.shape[1], img.shape[0]))
            result = np.hstack([img, colored_depth])
        elif show_depth:
            result = colored_depth
        else:
            result = img
        
        # 输出
        if args.output == "display":
            cv2.imshow("FastDepth", result)
            print("[INFO] 按任意键退出...")
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        else:
            cv2.imwrite(args.output, result)
            print(f"[INFO] 结果已保存到: {args.output}")
        
        # 打印深度统计
        print(f"\n[INFO] 深度统计:")
        print(f"  最小值: {np.min(depth_map):.4f}")
        print(f"  最大值: {np.max(depth_map):.4f}")
        print(f"  均值:   {np.mean(depth_map):.4f}")
        
    else:
        # === 视频/摄像头/HTTP流模式 ===
        
        # 确定视频源
        is_http_stream = False
        if input_path.isdigit():
            cap = cv2.VideoCapture(int(input_path))
        elif input_path.startswith('/dev/video'):
            device_id = int(input_path.replace('/dev/video', ''))
            cap = cv2.VideoCapture(device_id)
        elif input_path.startswith('csi://'):
            # CSI 摄像头 - GStreamer pipeline
            camera_id = int(input_path.replace('csi://', ''))
            gst_pipeline = (
                f"nvarguscamerasrc sensor-id={camera_id} ! "
                f"video/x-raw(memory:NVMM), width=640, height=480, "
                f"format=NV12, framerate=30/1 ! "
                f"nvvidconv ! video/x-raw, format=BGRx ! "
                f"videoconvert ! video/x-raw, format=BGR ! "
                f"appsink drop=1"
            )
            cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
        elif input_path.startswith('http://') or input_path.startswith('https://'):
            # HTTP/MJPEG 视频流（如 mjpg-streamer）
            print(f"[INFO] 连接 HTTP 视频流: {input_path}")
            raw_cap = cv2.VideoCapture(input_path)
            # 缓冲区设为 1，降低延迟
            raw_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            # 使用线程化捕获，独立线程持续抓取最新帧，避免缓冲区堆积
            cap = ThreadedVideoCapture(raw_cap)
            is_http_stream = True
            print(f"[INFO] 已启用线程化帧捕获（始终获取最新帧）")
        else:
            cap = cv2.VideoCapture(input_path)
        
        if not cap.isOpened():
            print(f"[ERROR] 无法打开视频源: {input_path}")
            sys.exit(1)
        
        # 帧率控制
        target_fps = args.fps
        if target_fps <= 0 and is_http_stream:
            # HTTP 流默认限制为 15 FPS（常见的 MJPEG 流帧率）
            target_fps = 15.0
            print(f"[INFO] HTTP 流自动设置目标帧率: {target_fps} FPS")
        
        if target_fps > 0:
            frame_interval = 1.0 / target_fps
            print(f"[INFO] 帧率限制: {target_fps} FPS (间隔 {frame_interval*1000:.1f}ms)")
        else:
            frame_interval = 0
        
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[INFO] 视频分辨率: {frame_w}x{frame_h}")
        
        # 视频写入器
        video_writer = None
        if args.output != "display" and is_video_file(args.output):
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out_w = frame_w * (1 + int(show_depth)) if show_input else int(frame_w * args.depth_size)
            write_fps = target_fps if target_fps > 0 else 30
            video_writer = cv2.VideoWriter(args.output, fourcc, write_fps, (out_w, frame_h))
        
        print("[INFO] 按 'q' 或 ESC 退出\n")
        frame_count = 0
        
        try:
            loop_start = time.time()
            
            while True:
                frame_start = time.time()
                
                ret, frame = cap.read()
                if not ret:
                    # 对 HTTP 流，read 可能暂时失败，短暂等待后重试
                    if is_http_stream:
                        time.sleep(0.01)
                        continue
                    break
                
                # 推理
                depth_map = estimator.infer(frame)
                
                depth_size = (int(frame_w * args.depth_size), int(frame_h * args.depth_size))
                colored_depth = visualize_depth(depth_map, args.colormap, target_size=depth_size)
                
                # 合成图像
                if show_input and show_depth:
                    if colored_depth.shape[0] != frame.shape[0]:
                        colored_depth = cv2.resize(colored_depth, (colored_depth.shape[1], frame.shape[0]))
                    result = np.hstack([frame, colored_depth])
                elif show_depth:
                    result = colored_depth
                else:
                    result = frame
                
                # 添加 FPS 信息（显示实际输出帧率）
                elapsed = time.time() - loop_start
                actual_fps = frame_count / elapsed if elapsed > 0 else 0
                infer_fps = estimator.get_fps()
                cv2.putText(result, f"Out: {actual_fps:.1f} FPS | Infer: {infer_fps:.1f} FPS", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                
                frame_count += 1
                
                # 输出
                if args.output == "display":
                    cv2.imshow("FastDepth (TRT) - Press Q to quit", result)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q') or key == 27:  # q 或 ESC
                        break
                elif video_writer is not None:
                    video_writer.write(result)
                    if frame_count % 30 == 0:
                        print(f"  已处理 {frame_count} 帧, 输出: {actual_fps:.1f} FPS, 推理: {infer_fps:.1f} FPS")
                
                # ── 帧率限制：等待到下一帧时间点 ──
                if frame_interval > 0:
                    frame_elapsed = time.time() - frame_start
                    sleep_time = frame_interval - frame_elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)
        except KeyboardInterrupt:
            print("\n[INFO] 收到中断信号 (Ctrl+C)，正在安全退出并保存视频...")
        finally:
            cap.release()
            if video_writer is not None:
                video_writer.release()
                print(f"\n[INFO] 视频已保存到: {args.output}")
            
            cv2.destroyAllWindows()
            print(f"\n[INFO] 处理完成，共 {frame_count} 帧，平均 FPS: {estimator.get_fps():.1f}")


if __name__ == "__main__":
    main()
