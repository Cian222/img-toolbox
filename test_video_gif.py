"""video_gif.py 功能测试：生成合成视频，验证选段/时长/帧率/取消等。运行：python test_video_gif.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image

from app import video_gif as VG


def make_test_video(path: Path):
    """3 秒 30fps 320x240：每秒一色（红/绿/蓝），白色方块逐帧移动。"""
    import cv2
    import numpy as np
    w, h, fps, n = 320, 240, 30, 90
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (w, h))
    assert writer.isOpened(), "VideoWriter 打开失败"
    colors = [(180, 40, 40), (40, 180, 40), (40, 40, 180)]  # BGR: 红 绿 蓝
    for i in range(n):
        frame = np.full((h, w, 3), colors[i // 30], dtype=np.uint8)
        x = 10 + i * 3
        frame[100:140, x:x + 40] = (255, 255, 255)
        writer.write(frame)
    writer.release()


def main():
    tmp = Path(tempfile.mkdtemp(prefix="videogif_test_"))
    video = tmp / "sample.mp4"
    make_test_video(video)
    print(f"测试视频: {video}")
    ok = 0

    def check(cond, msg):
        nonlocal ok
        assert cond, f"失败: {msg}"
        ok += 1
        print(f"  ✓ {msg}")

    # --- 视频信息 ---
    info = VG.get_video_info(video)
    print(f"  信息: {info}")
    check(abs(info["duration"] - 3.0) < 0.15, f"时长 ≈ 3 秒 ({info['duration']:.2f})")
    check(info["frames"] == 90 and info["width"] == 320, "帧数/分辨率正确")

    # --- 正常转换：1.2s 起截 0.5s，10fps，宽 160 ---
    got = []
    out, note = VG.video_to_gif(
        video, 1.2, 0.5, 10, 160, tmp / "out.gif",
        progress=lambda d, t: got.append((d, t)))
    print(f"  {note}")
    check(out.exists() and out.suffix == ".gif", "GIF 已生成")
    with Image.open(out) as im:
        check(im.n_frames == 5, f"帧数 = 时长×帧率 = 5 (实际 {im.n_frames})")
        check(im.size == (160, 120), f"输出宽度 160 保持宽高比 {im.size}")
        check(abs(im.info.get("duration", 0) - 100) <= 25,
              f"每帧时长 ≈100ms ({im.info.get('duration')}ms)")
        # 第 0 帧应落在绿色段（1.2s ∈ [1s,2s)）
        rgb = im.convert("RGB").getpixel((5, 5))
        check(rgb[1] > 90 and rgb[1] > rgb[0] and rgb[1] > rgb[2],
              f"起点 1.2s 抽到绿色段 {rgb}")
    check(got[-1] == (5, 5), f"进度回调正确 ({got[-1]})")

    # --- 帧率高于源帧率：去重 ---
    out2, note2 = VG.video_to_gif(video, 1.0, 0.5, 60, 0, tmp / "out2.gif")
    with Image.open(out2) as im:
        check(im.n_frames == 15, f"60fps 请求去重为源 30fps→15 帧 (实际 {im.n_frames})")
        check(im.size == (320, 240), "宽度 0 = 保持原宽")

    # --- 超出末尾自动截断 ---
    out3, note3 = VG.video_to_gif(video, 2.5, 5.0, 10, 320, tmp / "out3.gif")
    print(f"  {note3}")
    with Image.open(out3) as im:
        check(im.n_frames == 5, f"2.5s 起截 5s → 只剩 0.5s = 5 帧 (实际 {im.n_frames})")

    # --- 起点超时长 → 报错 ---
    try:
        VG.video_to_gif(video, 10.0, 1.0, 10, 160, tmp / "out4.gif")
        check(False, "应抛出异常")
    except ValueError as e:
        check("超出" in str(e), f"起点超时报错: {e}")

    # --- 取消 ---
    def cancelled():
        return True
    try:
        VG.video_to_gif(video, 0.0, 1.0, 10, 160, tmp / "out5.gif",
                        is_cancelled=cancelled)
        check(False, "应抛出已取消")
    except RuntimeError as e:
        check("取消" in str(e), f"取消生效: {e}")

    # --- 重名自动加后缀 ---
    out6, _ = VG.video_to_gif(video, 0.0, 0.5, 10, 160, out)
    check(out6.name == "out_1.gif", f"重名自动 _1: {out6.name}")

    print(f"\n全部 {ok} 项测试通过 ✅  测试目录: {tmp}")


if __name__ == "__main__":
    main()
