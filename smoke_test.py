"""冒烟测试：两种布局截图 + 折叠布局跑真实处理链路。"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme

from app import main_window as MW
from app import processors as P
from app.layout_collapse import CollapseWindow
from app.layout_nav import NavWindow
from app.workers import ProcessWorker

tmp = Path(tempfile.mkdtemp(prefix="imgtoolbox_smoke_"))

img1 = Image.new("RGB", (800, 600), (90, 140, 220))
for x in range(0, 800, 40):
    for y in range(600):
        img1.putpixel((x, y), (255, 255, 255))
p1 = tmp / "测试图片A.jpg"
img1.save(p1, "JPEG", quality=92)
p2 = tmp / "测试图片B.png"
Image.new("RGBA", (600, 600), (250, 180, 60, 255)).save(p2, "PNG")

app = QApplication(sys.argv)
setTheme(Theme.LIGHT)
result = {}
HERE = Path(__file__).parent


def grab_window(w, png, settle_ms=900):
    w.show()
    t0 = time.time()
    while time.time() - t0 < settle_ms / 1000:
        app.processEvents()
    w.grab().save(str(HERE / png))
    print(f"截图: {png}", flush=True)
    w.close()
    app.processEvents()


# --- 布局选择器截图 ---
chooser = MW.LayoutChooserDialog()
chooser.grab().save(str(HERE / "screenshot_layout_chooser.png"))
print("截图: screenshot_layout_chooser.png", flush=True)

# --- 智能折叠布局：配置 + 截图 + 真实处理链路 ---
wc = CollapseWindow()
wc.resize(1180, 800)
wc.files.add_paths([p1, p2])
wc.resize_s.switch.setChecked(True)
wc.crop_s.switch.setChecked(True)
wc.crop_s.set_reference(img1)
# 回归：切换比例预设 → 已有裁剪区域自动按新比例重适配（800x600 → 1:1 = 600x600 居中）
wc.crop_s.set_rect((0.0, 0.0, 1.0, 1.0))
wc.crop_s.ratio_combo.setCurrentIndex(1)   # 1:1
app.processEvents()
rx, ry, rw, rh = wc.crop_s._batch_rect
assert abs(rw - 0.75) < 1e-6 and abs(rh - 1.0) < 1e-6 and abs(rx - 0.125) < 1e-6, \
    f"1:1 重适配失败: {wc.crop_s._rect}"
print("比例重适配 OK", flush=True)
wc.crop_s.set_rect((0.25, 0.25, 0.5, 0.5))

# 回归：三态裁剪（跟随批量 / 单独区域 / 不裁剪）
wc.crop_s.set_file_state(str(p1), "skip")
assert not wc.crop_s.effective_options(str(p1)).enabled, "skip 状态未生效"
assert wc.crop_s.effective_options(str(p2)).enabled, "p2 应回退批量"
wc.crop_s.set_file_state(str(p1), "own")
wc.crop_s.set_file_rect(str(p1), (0.0, 0.0, 0.5, 0.5))
eff1 = wc.crop_s.effective_options(str(p1))
assert eff1.enabled and abs(eff1.w - 0.5) < 1e-6, f"单独裁剪未生效: {eff1}"
wc.crop_s.set_file_state(str(p1), "follow")
eff1 = wc.crop_s.effective_options(str(p1))
assert eff1.enabled and abs(eff1.x - 0.25) < 1e-6, "follow 应回退批量"
print("裁剪三态 OK", flush=True)

# 回归：界面上直接切"单独区域"不会被弹回（允许先选状态、再画框）
wc.crop_s.state_combo.setCurrentIndex(1)
app.processEvents()
assert wc.crop_s.state_combo.currentIndex() == 1, "单独区域被弹回跟随批量"
assert not wc.crop_s.effective_options(str(p1)).enabled, "未画框前不应裁剪"
wc.crop_s.set_file_rect(str(p1), (0.1, 0.1, 0.6, 0.6))
eff1 = wc.crop_s.effective_options(str(p1))
assert eff1.enabled and abs(eff1.w - 0.6) < 1e-6, "选状态后画框未生效"
wc.crop_s.state_combo.setCurrentIndex(0)
app.processEvents()
assert wc.crop_s.state_combo.currentIndex() == 0, "切回跟随批量失败"
print("单独区域选中 OK", flush=True)

# 回归：跳过处理（文件级，任何功能都不碰）
wc.files.toggle_skip(str(p2))
assert all(f.name != "测试图片B.png" for f in wc.files.files()), "跳过未生效"
assert "跳过" in wc.files.count_label.text()
wc.files.toggle_skip(str(p2))
assert any(f.name == "测试图片B.png" for f in wc.files.files()), "恢复未生效"
print("跳过开关 OK", flush=True)
wc.wm.switch.setChecked(True)      # 自动展开
wc.wm.text_edit.setText("测试水印 Demo")
wc.wm.pos_combo.setCurrentIndex(8)
wc.fmt.switch.setChecked(True)     # 自动展开
wc.fmt.comp_group.button(3).setChecked(True)
wc.fmt._mode_clicked(3)
wc.fmt.target_edit.setValue(60)
wc.fmt.target_unit.setCurrentIndex(0)
print(f"格式选项: {wc.fmt.options()}", flush=True)
wc.preview.refresh()
app.processEvents()
tip = wc.preview.preview_tip.text()
assert "已裁剪" in tip and "已加水印" in tip, f"预览未体现完整流水线: {tip}"
img_out, _ = wc.preview._load_processed()
assert img_out.size == (200, 150), f"预览未体现裁剪+缩放: {img_out.size}"
print(f"预览流水线 OK: {tip} {img_out.size}", flush=True)
grab_window(wc, "screenshot_collapse.png")

# 回归：裁剪画布必须把图片缩放到画布尺寸（曾因未缩放只显示图片左上角）
from app.crop_dialog import CropDialog
cd = CropDialog(img1, ratio=4 / 3)
assert cd.canvas._pixmap.width() == cd.canvas.width(), \
    f"画布图片未缩放: {cd.canvas._pixmap.width()} vs {cd.canvas.width()}"
cd.canvas._rect = cd.canvas._rect.__class__(150, 100, 320, 240)
cd.canvas.update()
cd.canvas.rectChanged.emit()
cd.grab().save(str(HERE / "screenshot_crop.png"))
print(f"裁剪画布缩放 OK: canvas={cd.canvas.width()}x{cd.canvas.height()}", flush=True)

settings = wc.collect_settings()
worker = ProcessWorker([p1, p2], settings, tmp / "out", None)
result["worker"] = worker
worker.file_finished.connect(lambda ok, src, msg: print(
    f"  [{'OK' if ok else '失败'}] {Path(src).name} -> {msg}", flush=True))
worker.run_finished.connect(lambda ok, fail: (print(
    f"线程处理完成: 成功{ok} 失败{fail}", flush=True), app.quit()))
worker.start()
app.exec()

out_a = tmp / "out" / "测试图片A.jpg"
with Image.open(out_a) as im:
    print(f"输出验证: {im.size}（期望 200x150 = 先裁剪后缩放）", flush=True)
    assert im.size == (200, 150), f"裁剪+缩放结果不对: {im.size}"

# --- 左侧导航布局 ---
# 注：FluentWindow 是无边框圆角窗口，离屏 grab() 会把透明区域合成黑色，
# 实机上是 Mica/浅色效果；这里另截导航栏组件确认结构。
wn = NavWindow()
wn.resize(1200, 820)
grab_window(wn, "screenshot_nav.png")

# 回归：左侧导航功能项切换
wn.show()
t0 = time.time()
while time.time() - t0 < 0.6:
    app.processEvents()
for key, expect in (("wm", 2), ("fmt", 3), ("ren", 4), ("resize", 0)):
    wn._show_feature(key)
    app.processEvents()
    assert wn.view.stack.currentIndex() == expect, \
        f"导航切换 {key} 失败: {wn.view.stack.currentIndex()}"
    assert wn.stackedWidget.currentWidget() is wn.view
print("导航功能切换 OK", flush=True)

# 回归：三栏分割条可调宽
sizes = wn.view.splitter.sizes()
assert len(sizes) == 3, f"分割条栏数不对: {sizes}"
wn.view.splitter.setSizes([420, 480, 300])
app.processEvents()
s2 = wn.view.splitter.sizes()
assert abs(s2[0] - 420) < 25, f"分割条拖动未生效: {s2}"
print(f"三栏分割 OK: {s2}", flush=True)

# 回归：预览栏开关（QSplitter 下隐藏后其余栏自动补位）
wn.view.preview_switch.setChecked(False)
app.processEvents()
assert not wn.view.preview_column.isVisible(), "预览开关未隐藏预览栏"
wn.view.preview_switch.setChecked(True)
app.processEvents()
assert wn.view.preview_column.isVisible(), "预览开关未恢复预览栏"
print("预览栏开关 OK", flush=True)

# 回归：预览自适应栏大小 + 双击大图（原始分辨率）
wn.view.files.add_paths([p1])
app.processEvents()
wn.view.preview.refresh()
app.processEvents()
pm = wn.view.preview.preview_label.pixmap()
assert not pm.isNull(), "预览为空"
old_w = pm.width()
wn.view.splitter.setSizes([280, 460, 900])
wn.resize(1560, 980)
app.processEvents()
time.sleep(0.45)  # 等防抖重渲染
app.processEvents()
pm2 = wn.view.preview.preview_label.pixmap()
print(f"预览自适应: {old_w}px → {pm2.width()}px", flush=True)
assert pm2.width() > old_w + 60, f"面板变大后预览未跟着变大: {old_w} → {pm2.width()}"
viewer = wn.view.preview.open_viewer()
app.processEvents()
assert viewer is not None
big = viewer.image_label.pixmap()
assert big.width() == 800, f"大图应为原始分辨率 800: {big.width()}"
viewer.close()
app.processEvents()
print("预览自适应+双击大图 OK", flush=True)

wn.navigationInterface.grab().save(str(HERE / "screenshot_nav_panel.png"))
print("截图: screenshot_nav_panel.png（导航栏组件）", flush=True)
wn.switchTo(wn.video_page)
t0 = time.time()
while time.time() - t0 < 0.6:
    app.processEvents()
wn.grab().save(str(HERE / "screenshot_nav_video.png"))
print("截图: screenshot_nav_video.png", flush=True)
wn.close()
app.processEvents()

print("SMOKE TEST OK")
