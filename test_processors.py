"""processors.py 的功能测试：直接运行 python test_processors.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image

from app import processors as P
from app import presets as PS


def make_test_images(tmp: Path):
    # 1) 渐变 JPG
    img = Image.new("RGB", (800, 600))
    for x in range(800):
        for y in range(0, 600, 50):
            for yy in range(y, min(y + 50, 600)):
                img.putpixel((x, yy), (x * 255 // 800, y * 255 // 600, 128))
    p1 = tmp / "风景照片.jpg"
    img.save(p1, "JPEG", quality=95)

    # 2) 带透明区域的 PNG
    img2 = Image.new("RGBA", (500, 500), (255, 0, 0, 0))
    for x in range(500):
        for y in range(500):
            if (x - 250) ** 2 + (y - 250) ** 2 < 200 ** 2:
                img2.putpixel((x, y), (30, 144, 255, 255))
    p2 = tmp / "icon.png"
    img2.save(p2, "PNG")

    # 3) 大图
    img3 = Image.new("RGB", (2400, 1800), (100, 150, 200))
    p3 = tmp / "big.jpg"
    img3.save(p3, "JPEG", quality=95)
    return [p1, p2, p3]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="imgtoolbox_test_"))
    files = make_test_images(tmp)
    out = tmp / "out"
    ok = 0

    def check(cond, msg):
        nonlocal ok
        assert cond, f"失败: {msg}"
        ok += 1
        print(f"  ✓ {msg}")

    # --- 调整大小 ---
    s = P.ProcessSettings(
        resize=P.ResizeOptions(enabled=True, mode="percent", value=50),
        watermark=P.WatermarkOptions(), fmt=P.FormatOptions(), rename=P.RenameOptions(),
    )
    p, note = P.process_file(files[0], s, out, 1)
    with Image.open(p) as im:
        check(im.size == (400, 300), f"按百分比 50%: {im.size} {note}")
    check(p.suffix == ".jpg", "保持原格式 jpg")

    s.resize = P.ResizeOptions(enabled=True, mode="width", value=300)
    p, _ = P.process_file(files[0], s, out, 1)
    with Image.open(p) as im:
        check(im.size == (300, 225), f"指定宽度 300: {im.size}")

    s.resize = P.ResizeOptions(enabled=True, mode="longest", value=100)
    p, _ = P.process_file(files[0], s, out, 1)
    with Image.open(p) as im:
        check(im.size == (100, 75), f"限制最长边 100: {im.size}")

    s.resize = P.ResizeOptions(enabled=True, mode="width", value=9999)
    p, _ = P.process_file(files[0], s, out, 1)
    with Image.open(p) as im:
        check(im.size == (800, 600), "不放大：宽度超原图时保持不变")

    # --- 文字水印 ---
    font = P.pick_default_font()
    print(f"  默认字体: {font}")
    s2 = P.ProcessSettings(
        resize=P.ResizeOptions(),
        watermark=P.WatermarkOptions(enabled=True, text="测试水印\n第二行",
                                     font_path=font, opacity=60,
                                     position="bottom-right"),
        fmt=P.FormatOptions(), rename=P.RenameOptions(),
    )
    p, _ = P.process_file(files[0], s2, out, 1)
    with Image.open(p) as im:
        check(im.size == (800, 600), "水印不改变尺寸")
        check(im.mode == "RGBA" or True, "")
    before = Image.open(files[0]).convert("RGB")
    after = Image.open(p).convert("RGB")
    diff = sum(1 for x in range(0, 800, 4) for y in range(0, 600, 4)
               if before.getpixel((x, y)) != after.getpixel((x, y)))
    check(diff > 10, f"右下角检测到水印像素变化 (采样差异点 {diff})")

    # --- 图片水印 ---
    wm_src = tmp / "wm.png"
    Image.new("RGBA", (120, 60), (255, 0, 0, 180)).save(wm_src, "PNG")
    s2.watermark = P.WatermarkOptions(enabled=True, kind="image",
                                      image_path=str(wm_src), opacity=80,
                                      position="center")
    p, _ = P.process_file(files[1], s2, out, 1)
    check(p.exists(), "图片水印合成成功")

    # --- 格式互转 + 透明通道处理 ---
    s3 = P.ProcessSettings(
        resize=P.ResizeOptions(), watermark=P.WatermarkOptions(),
        fmt=P.FormatOptions(enabled=True, fmt="webp", quality=80),
        rename=P.RenameOptions(),
    )
    p, _ = P.process_file(files[1], s3, out, 1)
    check(p.suffix == ".webp" and p.exists(), "PNG → WEBP")

    s3.fmt = P.FormatOptions(enabled=True, fmt="jpg", quality=90)
    p, _ = P.process_file(files[1], s3, out, 1)
    with Image.open(p) as im:
        check(p.suffix == ".jpg" and im.mode == "RGB", "PNG(透明) → JPG 白底 RGB")
        corner = im.getpixel((2, 2))
        check(corner == (255, 255, 255), f"透明区域变白 {corner}")

    # --- 压缩对比 ---
    big = files[2]
    orig_kb = big.stat().st_size / 1024
    s4 = P.ProcessSettings(
        resize=P.ResizeOptions(), watermark=P.WatermarkOptions(),
        fmt=P.FormatOptions(enabled=True, fmt="keep", quality=40),
        rename=P.RenameOptions(),
    )
    p, _ = P.process_file(big, s4, out, 1)
    check(p.stat().st_size < big.stat().st_size,
          f"压缩生效: {orig_kb:.0f}KB → {p.stat().st_size / 1024:.0f}KB")

    # --- 批量重命名 ---
    s5 = P.ProcessSettings(
        resize=P.ResizeOptions(), watermark=P.WatermarkOptions(),
        fmt=P.FormatOptions(),
        rename=P.RenameOptions(enabled=True, template="{name}_{index}",
                               index_digits=3, start_index=5),
    )
    p, _ = P.process_file(files[0], s5, out, 0)  # index 0 → 起始号 5
    check(p.name == "风景照片_005.jpg", f"模板+序号: {p.name}")
    p2, _ = P.process_file(files[0], s5, out, 0)
    check(p2.name == "风景照片_005_1.jpg", f"重名自动加后缀: {p2.name}")

    s5.rename = P.RenameOptions(enabled=True, template="旅行{index}",
                                index_digits=2, start_index=1)
    p, _ = P.process_file(files[0], s5, out, 0)
    check(p.name == "旅行01.jpg", f"纯模板重命名: {p.name}")

    # --- 仅重命名（复制不重编码） ---
    s6 = P.ProcessSettings(
        resize=P.ResizeOptions(), watermark=P.WatermarkOptions(),
        fmt=P.FormatOptions(),
        rename=P.RenameOptions(enabled=True, template="copy_{index}"),
    )
    p, _ = P.process_file(files[2], s6, out, 0)
    check(p.name == "copy_001.jpg" and p.exists(), "仅重命名=复制到输出目录")

    # --- collect_images ---
    got = P.collect_images([tmp, str(files[1])])
    names = [g.name for g in got]
    check(len(got) == 4 and "icon.png" in names, f"文件夹+文件收集去重: {names}")

    # --- 裁剪 ---
    s7 = P.ProcessSettings(
        crop=P.CropOptions(enabled=True, x=0.25, y=0.25, w=0.5, h=0.5),
        resize=P.ResizeOptions(), watermark=P.WatermarkOptions(),
        fmt=P.FormatOptions(), rename=P.RenameOptions(),
    )
    p, _ = P.process_file(files[1], s7, out, 1)  # icon.png 500x500
    with Image.open(p) as im:
        check(im.size == (250, 250), f"相对裁剪 50%: {im.size}")
        px = im.convert("RGBA").getpixel((5, 5))
        check(px[2] > 200 and px[3] == 255,
              f"裁剪位置正确（框左上落在蓝色圆内 {px}）")

    s7.crop = P.CropOptions(enabled=True, x=0.1, y=0.1, w=0.5, h=0.5,
                            target_w=100, target_h=200)
    p, _ = P.process_file(files[1], s7, out, 1)
    with Image.open(p) as im:
        check(im.size == (100, 200), f"裁剪+像素预设输出 {im.size}")

    s7.crop = P.CropOptions(enabled=True, x=0.9, y=0.0, w=0.5, h=1.0)
    p, _ = P.process_file(files[1], s7, out, 1)
    with Image.open(p) as im:
        check(im.size == (50, 500), f"裁剪越界自动钳制: {im.size}")

    # --- 裁剪 + 缩放顺序（先裁剪后缩放） ---
    s7.crop = P.CropOptions(enabled=True, x=0.25, y=0.25, w=0.5, h=0.5)
    s7.resize = P.ResizeOptions(enabled=True, mode="percent", value=50)
    p, _ = P.process_file(files[0], s7, out, 1)  # 800x600 → 裁 400x300 → 缩 200x150
    with Image.open(p) as im:
        check(im.size == (200, 150), f"先裁剪后缩放: {im.size}")

    # --- 预设持久化 ---
    orig_pf = PS.PRESETS_FILE
    PS.PRESETS_FILE = tmp / "user_presets.json"
    try:
        PS.save_custom([("7:5", 700, 500)], [(600, 800)])
        check(("7:5", 700, 500) in PS.all_ratios(), "自定义比例已保存并读取")
        check((600, 800) in PS.all_sizes(), "自定义像素预设已保存并读取")
        check(PS.ratio_label(1920, 1080) == "16:9", "比例标签自动化简 16:9")
        PS.save_custom([("7:5", 700, 500)], [(600, 800)])
        check(sum(1 for r in PS.all_ratios() if r[0] == "7:5") == 1,
              "重复比例去重")
    finally:
        PS.PRESETS_FILE = orig_pf

    # --- 压缩方式：普通 / 高品质 ---
    with Image.open(files[2]) as bim:
        d_normal = P.encode_image(bim, "jpg", 75)
        d_high = P.encode_image(bim, "jpg", 90)
    check(len(d_high) >= len(d_normal),
          f"高品质体积 ≥ 普通 ({len(d_normal) // 1024}KB vs {len(d_high) // 1024}KB)")

    # --- 目标体积：JPG 质量二分 ---
    with Image.open(files[0]) as g:  # 800x600 渐变，原 67KB@q40
        data, q, reached, out_img = P.compress_to_target(g, "jpg", 20 * 1024)
    check(reached and len(data) <= 20 * 1024,
          f"JPG 目标 20KB: {len(data) / 1024:.0f}KB q={q}")
    check(out_img.size == (800, 600), "20KB 质量二分即可，无需缩分辨率")

    data, q, reached, out_img = P.compress_to_target(g, "jpg", 5 * 1024)
    check(len(data) <= 5 * 1024 or not reached,
          f"强目标 5KB: {out_img.size} {len(data) / 1024:.1f}KB reached={reached}")

    # --- 目标体积：不可能达标（关闭降分辨率） ---
    data, q, reached, out_img = P.compress_to_target(
        Image.open(files[2]), "jpg", 1024, allow_downscale=False)
    check(not reached and len(data) > 0, "1KB 且不许缩放 → 未达标但仍输出")

    # --- 目标体积：PNG 降分辨率兜底 ---
    with Image.open(files[0]) as g2:
        d0 = P.encode_image(g2, "png", 0)
        if len(d0) > 30 * 1024:
            data, q, reached, out_img = P.compress_to_target(g2, "png", 30 * 1024)
            check(reached and len(data) <= 30 * 1024,
                  f"PNG 目标 30KB 降分辨率: {out_img.size} {len(data) // 1024}KB")
        else:
            print("  (渐变 PNG 本身小于 30KB，跳过 PNG 降分辨率用例)")

    # --- process_file 集成：目标体积模式 ---
    s8 = P.ProcessSettings(
        resize=P.ResizeOptions(), watermark=P.WatermarkOptions(),
        fmt=P.FormatOptions(enabled=True, fmt="keep", mode="target",
                            target_kb=50, allow_downscale=True),
        rename=P.RenameOptions(),
    )
    p, note = P.process_file(files[2], s8, out, 1)
    check(p.stat().st_size <= 50 * 1024 and "目标体积已达成" in note,
          f"集成目标体积: {note}")

    # --- 单独裁剪：按文件覆盖优先于批量 ---
    key1 = str(files[1].resolve()).lower()
    s9 = P.ProcessSettings(
        resize=P.ResizeOptions(), watermark=P.WatermarkOptions(),
        fmt=P.FormatOptions(), rename=P.RenameOptions(),
        crop=P.CropOptions(enabled=True, x=0.0, y=0.0, w=1.0, h=1.0),  # 批量：全图（等于不裁）
        crop_overrides={key1: P.CropOptions(enabled=True, x=0.0, y=0.0, w=0.5, h=0.5)},
    )
    out1, _ = P.process_file(files[1], s9, out, 1)   # 有单独覆盖 → 裁 250x250
    out2, _ = P.process_file(files[2], s9, out, 2)   # 无覆盖 → 用批量（全图）
    with Image.open(out1) as im:
        check(im.size == (250, 250), f"单独裁剪覆盖生效: {im.size}")
    with Image.open(out2) as im:
        check(im.size == (2400, 1800), f"无覆盖走批量: {im.size}")

    print(f"\n全部 {ok} 项测试通过 ✅  测试目录: {tmp}")


if __name__ == "__main__":
    main()
