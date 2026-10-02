"""视频转 GIF 冒烟测试：加载视频 → 截图对话框 → 走真实转换线程 → 验证 GIF。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtGui import QMovie
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme

from app.video_dialog import VideoGifDialog

tmp = Path(tempfile.mkdtemp(prefix="videogif_smoke_"))
video = tmp / "sample.mp4"

# 生成 3 秒测试视频（红/绿/蓝三段 + 移动方块）
import cv2
import numpy as np
w, h, fps, n = 480, 320, 30, 90
writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
colors = [(180, 40, 40), (40, 180, 40), (40, 40, 180)]
for i in range(n):
    frame = np.full((h, w, 3), colors[i // 30], dtype=np.uint8)
    x = 10 + i * 4
    frame[130:190, x:x + 60] = (255, 255, 255)
    writer.write(frame)
writer.release()

app = QApplication(sys.argv)
setTheme(Theme.LIGHT)
dlg = VideoGifDialog()
dlg.load_video(str(video))
dlg.start_spin.setValue(1.2)      # 拖到绿色段
dlg.dur_spin.setValue(1.5)
dlg._update_calc()
dlg.show()

result = {}

def snap():
    dlg.grab().save(str(Path(__file__).parent / "screenshot_video.png"))
    print("对话框截图已保存", flush=True)
    dlg._convert()  # 走真实的按钮逻辑

real_finished = dlg.panel._on_finished

def on_finish(ok, out_or_err, note):
    result["ok"] = ok
    real_finished(ok, out_or_err, note)  # 先走真实的完成逻辑（含自动播放动画）
    print(f"转换完成: ok={ok} -> {out_or_err} | {note}", flush=True)
    assert ok, f"转换失败: {result}"
    with Image.open(out_or_err) as im:
        print(f"GIF 验证: {im.n_frames} 帧, {im.size}", flush=True)
    result["running"] = (dlg._movie is not None
                         and dlg._movie.state() == QMovie.Running)
    print(f"动画自动播放: {result['running']}", flush=True)

    def snap_result():
        dlg.grab().save(str(Path(__file__).parent / "screenshot_video_result.png"))
        print("动画预览截图已保存", flush=True)
        # 拖动滑块 → 应自动切回视频帧预览
        dlg.start_slider.setValue(500)
        print(f"拖滑块后回到帧预览: {not dlg._showing_result}, "
              f"movie={dlg._movie is not None}", flush=True)
        QTimer.singleShot(400, app.quit)

    QTimer.singleShot(600, snap_result)

dlg.panel._on_finished = on_finish  # 挂到面板上（转换线程连接的是面板的方法）

QTimer.singleShot(1000, snap)
app.exec()
assert result.get("ok"), f"转换失败: {result}"
assert result.get("running"), "动画未自动播放"
print("VIDEO SMOKE TEST OK")
