"""图片处理核心逻辑：调整大小、裁剪、水印、格式转换/压缩、批量重命名。

纯函数实现，不依赖任何 UI，便于单独测试和复用。
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

# 本地工具，允许处理用户自己的大图
Image.MAX_IMAGE_PIXELS = None

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}

# 源扩展名 -> 统一输出扩展名
EXT_ALIASES = {
    ".jpeg": "jpg", ".jpg": "jpg", ".png": "png", ".webp": "webp",
    ".bmp": "bmp", ".tif": "tiff", ".tiff": "tiff", ".gif": "gif",
}

# 九宫格水印位置：key -> (纵向, 横向)
POSITIONS = {
    "top-left": ("top", "left"), "top-center": ("top", "center"),
    "top-right": ("top", "right"), "middle-left": ("middle", "left"),
    "center": ("middle", "center"), "middle-right": ("middle", "right"),
    "bottom-left": ("bottom", "left"), "bottom-center": ("bottom", "center"),
    "bottom-right": ("bottom", "right"),
}
POSITION_LABELS = {
    "top-left": "左上", "top-center": "上中", "top-right": "右上",
    "middle-left": "左中", "center": "正中", "middle-right": "右中",
    "bottom-left": "左下", "bottom-center": "下中", "bottom-right": "右下",
}

FALLBACK_FONTS = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\arial.ttf",
]

RESIZE_MODES = ["percent", "width", "height", "longest"]


def pick_default_font() -> str:
    for f in FALLBACK_FONTS:
        if Path(f).exists():
            return f
    return ""


@dataclass
class CropOptions:
    enabled: bool = False
    x: float = 0.0                 # 相对坐标 0~1，对所有图片按比例应用
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0
    target_w: int = 0              # 裁剪后统一缩放到的像素尺寸（0 = 保持裁剪尺寸）
    target_h: int = 0


@dataclass
class ResizeOptions:
    enabled: bool = False
    mode: str = "percent"          # percent / width / height / longest
    value: float = 50.0            # percent 为百分比，其余为像素


@dataclass
class WatermarkOptions:
    enabled: bool = False
    kind: str = "text"             # text / image
    text: str = ""
    font_path: str = ""
    font_size_ratio: float = 4.0   # 字号 = 图片宽度 * 该百分比
    color: str = "#FFFFFF"
    image_path: str = ""
    image_scale: float = 15.0      # 水印图宽度 = 主图宽度 * 该百分比
    opacity: int = 60              # 0-100
    position: str = "bottom-right"
    margin_ratio: float = 2.0      # 边距 = 短边 * 该百分比


@dataclass
class FormatOptions:
    enabled: bool = False
    fmt: str = "keep"              # keep / jpg / png / webp / bmp / tiff
    quality: int = 85              # 仅对 jpg / webp 生效
    mode: str = "quality"          # quality / normal / high / target
    target_kb: float = 500.0       # 目标体积模式：每张不超过（KB）
    allow_downscale: bool = True   # 目标体积达不成时允许缩小分辨率


QUALITY_PRESETS = {"normal": 75, "high": 90}
TARGET_FMTS = ("jpg", "jpeg", "webp", "png")


@dataclass
class RenameOptions:
    enabled: bool = False
    template: str = "{name}"
    index_digits: int = 3
    start_index: int = 1


@dataclass
class ProcessSettings:
    resize: ResizeOptions
    watermark: WatermarkOptions
    fmt: FormatOptions
    rename: RenameOptions
    crop: CropOptions = field(default_factory=CropOptions)
    crop_overrides: dict = field(default_factory=dict)  # 路径小写 → CropOptions（单独裁剪优先）


def collect_images(paths) -> list[Path]:
    """从文件/文件夹混合列表收集图片，去重并保持顺序。"""
    out: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        p = Path(p)
        if p.is_dir():
            candidates = sorted(
                c for c in p.iterdir() if c.is_file() and c.suffix.lower() in IMAGE_EXTS
            )
        else:
            candidates = [p] if p.suffix.lower() in IMAGE_EXTS else []
        for c in candidates:
            key = str(c.resolve()).lower()
            if key not in seen:
                seen.add(key)
                out.append(c)
    return out


def apply_crop(img: Image.Image, opt: CropOptions) -> Image.Image:
    """按相对坐标裁剪，越界部分自动钳制；可选缩放到指定像素尺寸。"""
    W, H = img.size
    x1 = max(0, min(round(opt.x * W), W - 1))
    y1 = max(0, min(round(opt.y * H), H - 1))
    x2 = max(x1 + 1, min(round((opt.x + opt.w) * W), W))
    y2 = max(y1 + 1, min(round((opt.y + opt.h) * H), H))
    out = img.crop((x1, y1, x2, y2))
    tw, th = opt.target_w, opt.target_h
    if tw > 0 and th > 0 and out.size != (tw, th):
        out = out.resize((tw, th), Image.LANCZOS)
    return out


def resize_image(img: Image.Image, mode: str, value: float) -> Image.Image:
    w, h = img.size
    if mode == "percent":
        scale = max(0.001, value / 100.0)
        new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    elif mode == "width":
        if value >= w:
            return img  # 不放大
        new_size = (int(value), max(1, round(h * value / w)))
    elif mode == "height":
        if value >= h:
            return img
        new_size = (max(1, round(w * value / h)), int(value))
    elif mode == "longest":
        longest = max(w, h)
        if value >= longest:
            return img
        scale = value / longest
        new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    else:
        raise ValueError(f"未知的调整大小模式: {mode}")
    return img.resize(new_size, Image.LANCZOS)


def _load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    size = max(8, size)
    candidates = [font_path] if font_path else []
    candidates += FALLBACK_FONTS
    for f in candidates:
        if f and Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.strip().lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    try:
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except (ValueError, IndexError):
        return (255, 255, 255)


def _apply_opacity(layer: Image.Image, opacity: int) -> None:
    alpha = layer.getchannel("A").point(lambda v: v * max(0, min(100, opacity)) // 100)
    layer.putalpha(alpha)


def _make_text_layer(canvas_wh, opt: WatermarkOptions) -> Image.Image | None:
    w, _ = canvas_wh
    font_size = max(8, round(w * opt.font_size_ratio / 100.0))
    font = _load_font(opt.font_path, font_size)
    layer = Image.new("RGBA", canvas_wh, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    fill = _hex_to_rgb(opt.color) + (255,)
    lines = opt.text.split("\n")
    if len(lines) > 1:
        draw.multiline_text((0, 0), opt.text, font=font, fill=fill,
                            spacing=max(4, font_size // 5))
    else:
        draw.text((0, 0), opt.text, font=font, fill=fill)
    bbox = layer.getbbox()
    if bbox is None:
        return None
    layer = layer.crop(bbox)
    _apply_opacity(layer, opt.opacity)
    return layer


def _make_image_layer(canvas_wh, opt: WatermarkOptions) -> Image.Image | None:
    if not opt.image_path or not Path(opt.image_path).exists():
        raise ValueError(f"水印图片不存在: {opt.image_path}")
    w, _ = canvas_wh
    with Image.open(opt.image_path) as im:
        im.load()
        wm = im.convert("RGBA")
    target_w = max(1, round(w * opt.image_scale / 100.0))
    target_h = max(1, round(wm.height * target_w / wm.width))
    wm = wm.resize((target_w, target_h), Image.LANCZOS)
    _apply_opacity(wm, opt.opacity)
    return wm


def _paste_position(base_wh, layer_wh, position: str, margin: int) -> tuple[int, int]:
    w, h = base_wh
    lw, lh = layer_wh
    vert, horiz = POSITIONS.get(position, ("bottom", "right"))
    x_map = {"left": margin, "center": (w - lw) // 2, "right": w - lw - margin}
    y_map = {"top": margin, "middle": (h - lh) // 2, "bottom": h - lh - margin}
    return max(0, x_map[horiz]), max(0, y_map[vert])


def apply_watermark(img: Image.Image, opt: WatermarkOptions) -> Image.Image:
    base = img if img.mode == "RGBA" else img.convert("RGBA")
    if opt.kind == "text":
        if not opt.text.strip():
            raise ValueError("水印文字为空")
        layer = _make_text_layer(base.size, opt)
    else:
        layer = _make_image_layer(base.size, opt)
    if layer is None:
        return base
    margin = max(2, round(min(base.size) * opt.margin_ratio / 100.0))
    xy = _paste_position(base.size, layer.size, opt.position, margin)
    base.alpha_composite(layer, xy)
    return base


def _flatten_to_rgb(img: Image.Image) -> Image.Image:
    if img.mode == "RGB":
        return img
    rgba = img.convert("RGBA")
    bg = Image.new("RGB", rgba.size, (255, 255, 255))
    bg.paste(rgba, mask=rgba.getchannel("A"))
    return bg


def encode_image(img: Image.Image, fmt: str, quality: int,
                 webp_method: int = 6) -> bytes:
    """编码到内存，供目标体积压缩做尺寸探测。"""
    buf = io.BytesIO()
    fmt = fmt.lower()
    if fmt in ("jpg", "jpeg"):
        _flatten_to_rgb(img).save(buf, "JPEG", quality=quality, optimize=True)
    elif fmt == "webp":
        img.save(buf, "WEBP", quality=quality, method=webp_method)
    elif fmt == "png":
        img.save(buf, "PNG", optimize=True)
    elif fmt == "bmp":
        _flatten_to_rgb(img).save(buf, "BMP")
    elif fmt == "tiff":
        img.save(buf, "TIFF")
    else:
        img.save(buf, fmt.upper())
    return buf.getvalue()


def save_image(img: Image.Image, path: Path, fmt: str, quality: int) -> None:
    path.write_bytes(encode_image(img, fmt, quality))


def compress_to_target(img: Image.Image, fmt: str, target_bytes: int,
                       allow_downscale: bool = True) -> tuple[bytes, int, bool, Image.Image]:
    """把图片压到不超过 target_bytes。

    JPG / WEBP 先在原尺寸上对质量做二分搜索；仍超标（或 PNG 这类无损格式）
    则按 90%→20% 逐步缩小分辨率后重试。返回 (数据, 质量值, 是否达标, 最终图片)。
    """
    fmt = fmt.lower()

    def bisect_quality(im: Image.Image):
        """在 10~94 间搜索不超标的最高质量，找不到返回 None。"""
        if len(encode_image(im, fmt, 10, webp_method=4)) > target_bytes:
            return None
        lo, hi, best = 10, 94, None
        while lo <= hi:
            mid = (lo + hi) // 2
            data = encode_image(im, fmt, mid, webp_method=4)
            if len(data) <= target_bytes:
                best = (data, mid, im)
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    if fmt in ("jpg", "jpeg", "webp"):
        big_q = encode_image(img, fmt, 95, webp_method=4)
        if len(big_q) <= target_bytes:
            return big_q, 95, True, img
        found = bisect_quality(img)
        if found:
            return found[0], found[1], True, found[2]
    else:
        # PNG 等无损格式：原尺寸已达标就直接用，避免无谓缩放
        data = encode_image(img, fmt, 0)
        if len(data) <= target_bytes:
            return data, 0, True, img

    best = None  # (bytes, quality, img)
    if allow_downscale:
        W, H = img.size
        for scale in (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2):
            nw, nh = max(1, round(W * scale)), max(1, round(H * scale))
            if nw >= W and nh >= H:
                continue
            smaller = img.resize((nw, nh), Image.LANCZOS)
            if fmt in ("jpg", "jpeg", "webp"):
                found = bisect_quality(smaller)
                if found:
                    return found[0], found[1], True, found[2]
                cand = (encode_image(smaller, fmt, 10, webp_method=4), 10, smaller)
            else:
                data = encode_image(smaller, fmt, 0)
                cand = (data, 0, smaller)
                if len(data) <= target_bytes:
                    return data, 0, True, smaller
            if best is None or len(cand[0]) < len(best[0]):
                best = cand

    if best is None:
        if fmt in ("jpg", "jpeg", "webp"):
            best = (encode_image(img, fmt, 10, webp_method=4), 10, img)
        else:
            best = (encode_image(img, fmt, 0), 0, img)
    return best[0], best[1], False, best[2]


def sanitize_filename(name: str, fallback: str = "image") -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip().strip(".")
    return cleaned or fallback


def render_filename(tpl: str, name: str, index: int, digits: int,
                    width: int, height: int) -> str:
    now = datetime.now()
    out = (
        tpl.replace("{name}", name)
        .replace("{index}", f"{index:0{max(1, digits)}d}")
        .replace("{date}", now.strftime("%Y%m%d"))
        .replace("{time}", now.strftime("%H%M%S"))
        .replace("{width}", str(width))
        .replace("{height}", str(height))
    )
    return sanitize_filename(out, fallback=name)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(1, 10000):
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not cand.exists():
            return cand
    raise RuntimeError(f"无法为 {path} 生成不重复的文件名")


def _normalize_mode(img: Image.Image) -> Image.Image:
    if img.mode in ("RGB", "RGBA", "L", "LA"):
        return img
    return img.convert("RGBA")


def process_file(path, settings: ProcessSettings, out_dir,
                 index: int = 1) -> tuple[Path, str]:
    """处理单个文件，返回 (输出路径, 说明文字)。"""
    src = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(src) as im:
        im.load()
        img = ImageOps.exif_transpose(im)
    img = _normalize_mode(img)
    orig_size = img.size

    crop_opt = settings.crop
    override = settings.crop_overrides.get(str(src.resolve()).lower())
    if override is not None and override.enabled:
        crop_opt = override            # 单独裁剪优先于批量
    if crop_opt.enabled:
        img = apply_crop(img, crop_opt)
    if settings.resize.enabled:
        img = resize_image(img, settings.resize.mode, settings.resize.value)
    if settings.watermark.enabled:
        img = apply_watermark(img, settings.watermark)

    if settings.fmt.enabled and settings.fmt.fmt != "keep":
        out_fmt = settings.fmt.fmt
    else:
        out_fmt = EXT_ALIASES.get(src.suffix.lower(), "png")

    if settings.rename.enabled:
        stem = render_filename(
            settings.rename.template, src.stem,
            settings.rename.start_index + index,
            settings.rename.index_digits, *img.size,
        )
    else:
        stem = sanitize_filename(src.stem)

    out_path = unique_path(out_dir / f"{stem}.{out_fmt}")

    fmt_opts = settings.fmt
    target_used = False
    if fmt_opts.enabled and fmt_opts.mode == "target" and out_fmt in TARGET_FMTS:
        data, q, reached, final_img = compress_to_target(
            img, out_fmt, max(1024, int(fmt_opts.target_kb * 1024)),
            fmt_opts.allow_downscale)
        out_path.write_bytes(data)
        target_used = True
        resized_by_target = final_img.size != img.size
        if resized_by_target:
            img = final_img
    else:
        q = fmt_opts.quality
        if fmt_opts.enabled and fmt_opts.mode in QUALITY_PRESETS:
            q = QUALITY_PRESETS[fmt_opts.mode]
        save_image(img, out_path, out_fmt, q)

    note = f"{orig_size[0]}x{orig_size[1]}"
    if img.size != orig_size:
        note += f" → {img.size[0]}x{img.size[1]}"
    note += f"，{out_path.stat().st_size / 1024:.0f} KB"
    if target_used:
        if not reached:
            note += "（目标体积未达成，已输出最小可达结果）"
        elif resized_by_target:
            note += f"（目标体积已达成，分辨率调整为 {img.size[0]}×{img.size[1]}）"
        elif out_fmt in ("jpg", "jpeg", "webp"):
            note += f"（目标体积已达成，质量 {q}）"
        else:
            note += "（目标体积已达成）"
    return out_path, note
