"""视频转 GIF 核心：OpenCV 抽帧 + Pillow 编码。

cv2 延迟导入，未安装 opencv-python 时主程序其余功能不受影响。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image

from app.processors import unique_path

VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".flv", ".wmv"}
VIDEO_FILTER = "视频 (*.mp4 *.avi *.mkv *.mov *.webm *.flv *.wmv);;所有文件 (*.*)"


def _cv2():
    try:
        import cv2
        return cv2
    except ImportError as e:
        raise RuntimeError("缺少 opencv-python 库，请先执行：pip install opencv-python") from e


def get_video_info(path) -> dict:
    """返回 {fps, frames, width, height, duration}。"""
    cv2 = _cv2()
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"无法打开视频文件: {path}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0 or fps != fps:  # 某些容器读不到 fps
            fps = 25.0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()
    if frames <= 0 or width <= 0:
        raise ValueError("视频信息读取失败（帧数为 0，编码可能不受支持）")
    return {"fps": float(fps), "frames": frames, "width": width,
            "height": height, "duration": frames / fps}


def read_frame(path, sec: float) -> Image.Image | None:
    """读取指定时间点的一帧，返回 RGB PIL 图（用于预览）。"""
    cv2 = _cv2()
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"无法打开视频文件: {path}")
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, sec) * 1000.0)
        ok, frame = cap.read()
        if not ok:
            return None
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    finally:
        cap.release()


def video_to_gif(video, start_sec: float, duration_sec: float, fps_out: int,
                 target_width: int, out_path,
                 progress: Callable[[int, int], None] | None = None,
                 is_cancelled: Callable[[], bool] | None = None) -> tuple[Path, str]:
    """把视频从 start_sec 起、持续 duration_sec 秒的片段转成 GIF。

    target_width <= 0 表示保持原始宽度；超过视频末尾自动截断；
    帧率不会超过源视频帧率。被取消时抛出 RuntimeError("已取消")。
    返回 (输出路径, 说明文字)。
    """
    cv2 = _cv2()
    video = Path(video)
    info = get_video_info(video)
    fps_out = max(1, min(int(fps_out), round(info["fps"])))
    duration_sec = max(0.1, float(duration_sec))

    first_idx = int(round(max(0.0, start_sec) * info["fps"]))
    if first_idx >= info["frames"]:
        raise ValueError(f"开始时间超出视频时长（视频共 {info['duration']:.1f} 秒）")

    # 需要抽取的源帧序号（时间点 k/fps_out → 最近源帧）
    n_frames = max(1, round(duration_sec * fps_out))
    needed: list[int] = []
    for k in range(n_frames):
        idx = first_idx + int(round(k / fps_out * info["fps"]))
        if idx >= info["frames"]:
            break
        if not needed or idx != needed[-1]:  # 输出帧率高于源帧率时去重
            needed.append(idx)
    if not needed:
        raise ValueError("截取范围内没有可用的帧")

    # 顺序解码：从第一帧 seek 过去，逐帧 grab，只 retrieve 需要的帧
    cv2 = _cv2()
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"无法打开视频文件: {video}")
    frames_rgb: list = []
    need_set = set(needed)
    total_needed = len(needed)
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, needed[0])
        cur = needed[0]
        while cur <= needed[-1]:
            if is_cancelled and is_cancelled():
                raise RuntimeError("已取消")
            ok = cap.grab()
            if not ok:
                break
            if cur in need_set:
                ok2, frame = cap.retrieve()
                if ok2:
                    frames_rgb.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    if progress:
                        progress(len(frames_rgb), total_needed)
            cur += 1
    finally:
        cap.release()
    if not frames_rgb:
        raise ValueError("解码失败：该视频编码可能不受支持")

    # 缩放 + 256 色量化 + 编码
    out_frames: list[Image.Image] = []
    tw = int(target_width)
    for rgb in frames_rgb:
        im = Image.fromarray(rgb)
        if 0 < tw < im.width:
            im = im.resize((tw, max(1, round(im.height * tw / im.width))), Image.LANCZOS)
        out_frames.append(im.convert("P", palette=Image.ADAPTIVE, colors=256))

    out = unique_path(Path(out_path))
    out.parent.mkdir(parents=True, exist_ok=True)
    dur_ms = max(20, round(1000 / fps_out))
    out_frames[0].save(out, save_all=True, append_images=out_frames[1:],
                       duration=dur_ms, loop=0, optimize=True)

    actual = len(out_frames) / fps_out
    note = (f"{len(out_frames)} 帧 @ {fps_out}fps，实际 {actual:.1f} 秒，"
            f"{out.stat().st_size / 1024:.0f} KB")
    return out, note
