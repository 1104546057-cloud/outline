"""
验证码路由

提供图片验证码生成接口。
"""

import io
import base64
import random
from PIL import ImageFilter

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from captcha.image import ImageCaptcha

from captcha_store import generate_captcha_id, save_captcha

router = APIRouter(prefix="/api/auth", tags=["认证"])

# 验证码字符集（去除易混淆字符 0/O/1/l/I）
_CHARS = "23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ"

# ===== 与 UI 匹配的颜色配置 =====
# 背景：与输入框背景渐变中点一致 linear-gradient(rgba(11,73,125,.82), rgba(8,51,96,.72)) → 中点约 rgb(10, 62, 110)
_BG_COLOR = (10, 62, 110)

# 文字颜色候选：浅青白色系，对应 UI 的 #dff9ff / #25d4ff 等
_TEXT_COLORS = [
    (200, 245, 255),   # 淡青白
    (140, 220, 255),   # 中青蓝
    (255, 255, 255),   # 纯白
    (180, 235, 255),   # 浅蓝白
    (100, 210, 255),   # 亮青
]

# 噪点/曲线颜色：低对比度深蓝，不干扰辨识但增加复杂度
_NOISE_COLOR = (20, 80, 130)


@router.get("/captcha")
async def get_captcha():
    """
    生成图片验证码

    返回：
    - captcha_id: 验证码唯一标识，登录时需随表单一起提交
    - image: base64 编码的 PNG 图片（data URI 格式）
    """
    # 生成 4 位随机验证码
    code = "".join(random.choices(_CHARS, k=4))

    # 实例化 ImageCaptcha
    image_captcha = ImageCaptcha(width=140, height=50, font_sizes=(30, 34, 36))

    # 每个字符随机选一种颜色，增加视觉层次
    text_color = random.choice(_TEXT_COLORS)

    # 使用内部 API 控制背景色和文字色
    img = image_captcha.create_captcha_image(code, text_color, _BG_COLOR)

    # 添加噪点和曲线（颜色调暗，不遮挡文字）
    image_captcha.create_noise_dots(img, _NOISE_COLOR, width=2, number=40)
    image_captcha.create_noise_curve(img, _NOISE_COLOR)

    # 轻微平滑，去除锯齿
    img = img.filter(ImageFilter.SMOOTH)

    # 转为 base64 PNG
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    b64 = base64.b64encode(img_bytes.read()).decode("utf-8")
    data_uri = f"data:image/png;base64,{b64}"

    # 保存验证码（忽略大小写）
    captcha_id = generate_captcha_id()
    save_captcha(captcha_id, code)

    return JSONResponse({"captcha_id": captcha_id, "image": data_uri})
