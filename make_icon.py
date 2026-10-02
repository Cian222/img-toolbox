"""生成应用图标：现代简约风格，渐变圆角底 + 照片图形。

输出 assets/icon.ico（多尺寸）与 assets/icon_1024.png。运行：python make_icon.py
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

S = 2048          # 超采样画布，最终缩到 1024
OUT = Path(__file__).parent / "assets"


def rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1],
                                        radius=radius, fill=255)
    return m


def main():
    OUT.mkdir(exist_ok=True)

    # ---- 背景：圆角方形 + 对角渐变（青绿 → 深蓝青）----
    top = np.array([32, 196, 186], dtype=float)     # #20C4BA
    bottom = np.array([9, 108, 158], dtype=float)   # #096C9E
    t = (np.arange(S) / (S - 1))[:, None, None]
    c = top[None, None, :] + (bottom - top)[None, None, :] * (0.35 + 0.65 * t)
    c = np.concatenate([c, np.full((S, 1, 1), 255.0)], axis=2)  # 补 alpha
    grad = np.repeat(c, S, axis=1).astype(np.uint8)
    bg = Image.fromarray(grad)
    bg.putalpha(rounded_mask(S, int(S * 0.22)))

    img = bg.copy()
    d = ImageDraw.Draw(img)

    # ---- 白色照片图形（填充式圆角矩形）----
    m = S * 0.235                    # 图形外边距
    r = S * 0.055                    # 图形圆角
    frame = [m, m, S - m, S - m]
    d.rounded_rectangle(frame, radius=r, fill=(255, 255, 255, 255))

    # ---- 内部：太阳 + 山（用背景青色镂空，读得清且简约）----
    teal = (14, 138, 166, 255)       # #0E8AA6，取渐变中间色
    inner = [frame[0] + r * 0.9, frame[1] + r * 0.9,
             frame[2] - r * 0.9, frame[3] - r * 0.9]
    iw = inner[2] - inner[0]

    # 太阳
    sun_d = iw * 0.20
    d.ellipse([inner[0] + iw * 0.14, inner[1] + iw * 0.14,
               inner[0] + iw * 0.14 + sun_d, inner[1] + iw * 0.14 + sun_d],
              fill=teal)

    # 双山（大山 + 小山），底部与图形下缘对齐
    base_y = inner[3]
    big = [inner[0] + iw * 0.06, base_y,
           inner[0] + iw * 0.40, inner[1] + iw * 0.30,
           inner[0] + iw * 0.70, base_y]
    small = [inner[0] + iw * 0.50, base_y,
             inner[0] + iw * 0.72, inner[1] + iw * 0.46,
             inner[0] + iw * 0.96, base_y]
    d.polygon(big, fill=teal)
    d.polygon(small, fill=teal)

    # ---- 缩到 1024 并导出 ----
    final = img.resize((1024, 1024), Image.LANCZOS)
    final.save(OUT / "icon_1024.png")

    ico = final.resize((256, 256), Image.LANCZOS)
    ico.save(OUT / "icon.ico",
             sizes=[(256, 256), (128, 128), (96, 96), (64, 64),
                    (48, 48), (32, 32), (24, 24), (16, 16)])
    print(f"图标已生成: {OUT / 'icon.ico'} / icon_1024.png")


if __name__ == "__main__":
    main()
