"""视频转 GIF 面板/对话框：拖滑块选起点（带帧预览），设时长/帧率/宽度后转换。

VideoGifPanel 是可嵌入主窗口的功能面板；VideoGifDialog 是独立窗口的薄包装。
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QMovie, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, DoubleSpinBox, InfoBar, InfoBarPosition, LineEdit,
    PrimaryPushButton, ProgressBar, PushButton, SpinBox, SubtitleLabel,
)

from app import video_gif as VG
from app.processors import unique_path
from app.workers import VideoGifWorker

PREVIEW_W, PREVIEW_H = 400, 300


class PreviewLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class VideoGifPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("videoPanel")
        self.setStyleSheet("QWidget#videoPanel { background: #f5f6fa; }")

        self._video: str | None = None
        self._info: dict | None = None
        self._worker: VideoGifWorker | None = None
        self._syncing = False
        self._out_dir_used = ""
        self._movie: QMovie | None = None
        self._result_gif: str | None = None
        self._showing_result = False

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(250)
        self._preview_timer.timeout.connect(self._update_preview)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(12)

        root.addWidget(self._build_top(), 1)
        root.addWidget(self._build_bottom(), 0)

    # ---------- 界面 ----------

    def _labeled(self, text: str, widget, label_w: int = 76) -> QWidget:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        lab = BodyLabel(text)
        lab.setFixedWidth(label_w)
        h.addWidget(lab)
        h.addWidget(widget, 1)
        return wrap

    def _build_top(self) -> QWidget:
        top = QWidget()
        h = QHBoxLayout(top)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)

        # 左：视频选择 + 帧预览
        left = QVBoxLayout()
        left.setSpacing(8)
        self.video_edit = LineEdit()
        self.video_edit.setPlaceholderText("选择视频文件（mp4 / avi / mkv / mov / webm …）")
        self.video_edit.textChanged.connect(self._schedule_preview)
        pick_btn = PushButton("选择视频")
        pick_btn.clicked.connect(self._pick_video)
        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(8)
        rh.addWidget(self.video_edit, 1)
        rh.addWidget(pick_btn, 0)
        left.addWidget(row)

        self.preview_label = PreviewLabel()
        self.preview_label.setFixedSize(PREVIEW_W + 12, PREVIEW_H + 12)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(
            "QLabel { background: #17181c; border-radius: 8px; }")
        self.preview_label.clicked.connect(self._toggle_movie)
        left.addWidget(self.preview_label)

        info_row = QWidget()
        ih = QHBoxLayout(info_row)
        ih.setContentsMargins(0, 0, 0, 0)
        ih.setSpacing(8)
        self.info_label = CaptionLabel("未选择视频")
        ih.addWidget(self.info_label, 1)
        self.result_btn = PushButton("预览转换结果")
        self.result_btn.setEnabled(False)
        self.result_btn.setToolTip("播放刚才转出的 GIF 动画")
        self.result_btn.clicked.connect(self._enter_result_mode)
        ih.addWidget(self.result_btn, 0)
        left.addWidget(info_row)
        left.addStretch(1)
        h.addLayout(left, 1)

        # 右：片段与输出参数
        right = QVBoxLayout()
        right.setSpacing(10)

        self.start_slider = QSlider(Qt.Horizontal)
        self.start_slider.setRange(0, 0)
        self.start_slider.setSingleStep(100)
        self.start_slider.valueChanged.connect(self._on_slider_moved)
        self.start_spin = DoubleSpinBox()
        self.start_spin.setDecimals(1)
        self.start_spin.setSingleStep(0.1)
        self.start_spin.setSuffix(" s")
        self.start_spin.setFixedWidth(92)
        self.start_spin.valueChanged.connect(self._on_spin_changed)
        start_row = QWidget()
        sh = QHBoxLayout(start_row)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(8)
        sh.addWidget(self.start_slider, 1)
        sh.addWidget(self.start_spin, 0)
        right.addWidget(self._labeled("开始时间", start_row))

        self.dur_spin = DoubleSpinBox()
        self.dur_spin.setRange(0.5, 60.0)
        self.dur_spin.setSingleStep(0.5)
        self.dur_spin.setValue(5.0)
        self.dur_spin.setSuffix(" s")
        self.dur_spin.valueChanged.connect(self._update_calc)
        right.addWidget(self._labeled("截取时长", self.dur_spin))

        self.fps_spin = SpinBox()
        self.fps_spin.setRange(2, 30)
        self.fps_spin.setValue(10)
        self.fps_spin.setSuffix(" fps")
        self.fps_spin.valueChanged.connect(self._update_calc)
        right.addWidget(self._labeled("帧率", self.fps_spin))

        self.width_spin = SpinBox()
        self.width_spin.setRange(0, 4096)
        self.width_spin.setValue(480)
        self.width_spin.setSingleStep(40)
        self.width_spin.setSpecialValueText("保持原宽")
        right.addWidget(self._labeled("输出宽度", self.width_spin))

        self.out_edit = LineEdit()
        self.out_edit.setPlaceholderText("默认：与视频同目录、同名 .gif")
        out_btn = PushButton("选择")
        out_btn.clicked.connect(self._pick_out)
        out_row = QWidget()
        oh = QHBoxLayout(out_row)
        oh.setContentsMargins(0, 0, 0, 0)
        oh.setSpacing(8)
        oh.addWidget(self.out_edit, 1)
        oh.addWidget(out_btn, 0)
        right.addWidget(self._labeled("输出文件", out_row))

        right.addStretch(1)
        self.calc_label = CaptionLabel("选择视频后在这里选片段")
        self.calc_label.setWordWrap(True)
        right.addWidget(self.calc_label)
        h.addLayout(right, 1)
        return top

    def _build_bottom(self) -> QWidget:
        bottom = QWidget()
        v = QVBoxLayout(bottom)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        btns = QHBoxLayout()
        self.convert_btn = PrimaryPushButton("开始转换")
        self.convert_btn.setFixedHeight(36)
        self.convert_btn.clicked.connect(self._convert)
        self.open_btn = PushButton("打开所在文件夹")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_out_dir)
        close_btn = PushButton("关闭")
        close_btn.clicked.connect(self.close)
        btns.addWidget(self.convert_btn, 1)
        btns.addWidget(self.open_btn, 0)
        btns.addWidget(close_btn, 0)
        v.addLayout(btns)

        self.progress = ProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        v.addWidget(self.progress)
        self.status_label = CaptionLabel("就绪")
        self.status_label.setWordWrap(True)
        v.addWidget(self.status_label)
        return bottom

    # ---------- 视频 ----------

    def _pick_video(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择视频", "", VG.VIDEO_FILTER)
        if f:
            self.load_video(f)

    def _pick_out(self):
        f, _ = QFileDialog.getSaveFileName(
            self, "选择输出文件", str(Path(self.video_edit.text()).with_suffix(".gif")) if self._video else "",
            "GIF 动图 (*.gif)")
        if f:
            self.out_edit.setText(f)

    def load_video(self, path: str):
        info = VG.get_video_info(path)  # 失败会抛异常，交由调用处提示
        self._video = path
        self._info = info
        self.video_edit.setText(path)
        self.info_label.setText(
            f"{info['width']}x{info['height']}，{info['fps']:.1f} fps，"
            f"共 {info['duration']:.1f} 秒 / {info['frames']} 帧")
        self._syncing = True
        self.start_slider.setRange(0, max(1, int(info["duration"] * 1000)))
        self.start_slider.setValue(0)
        self.start_spin.setRange(0.0, max(0.0, round(info["duration"] - 0.1, 1)))
        self.start_spin.setValue(0.0)
        self.dur_spin.setMaximum(min(60.0, max(0.5, round(info["duration"], 1))))
        self._syncing = False
        self._result_gif = None
        self.result_btn.setEnabled(False)
        self._exit_result_mode()
        self._update_calc()
        self._update_preview()

    # ---------- 预览与联动 ----------

    def _schedule_preview(self):
        self._preview_timer.start()

    def _on_slider_moved(self, ms: int):
        if self._syncing or not self._info:
            return
        self._syncing = True
        self.start_spin.setValue(min(self.start_spin.maximum(), ms / 1000.0))
        self._syncing = False
        self._exit_result_mode()
        self._schedule_preview()

    def _on_spin_changed(self, val: float):
        if self._syncing or not self._info:
            return
        self._syncing = True
        self.start_slider.setValue(int(val * 1000))
        self._syncing = False
        self._exit_result_mode()
        self._schedule_preview()

    def _update_calc(self):
        if not self._info:
            return
        n = round(self.dur_spin.value() * self.fps_spin.value())
        w = self.width_spin.value()
        w_text = f"{w}px" if w > 0 else "原始宽度"
        self.calc_label.setText(
            f"预计输出 {n} 帧 @ {self.fps_spin.value()}fps，宽 {w_text}，"
            f"时长 {self.dur_spin.value():.1f} 秒。提示：帧率和宽度越大 GIF 越大")

    def _update_preview(self):
        if self._showing_result:
            return
        if not self._video:
            self.preview_label.setPixmap(QPixmap())
            return
        try:
            frame = VG.read_frame(self._video, self.start_spin.value())
            if frame is None:
                self.status_label.setText("该时间点无法解码画面")
                return
            frame.thumbnail((PREVIEW_W, PREVIEW_H), Image.LANCZOS)
            self.preview_label.setPixmap(
                QPixmap.fromImage(ImageQt(frame.convert("RGB"))))
        except Exception as e:
            self.preview_label.setPixmap(QPixmap())
            self.status_label.setText(f"预览失败：{e}")

    # ---------- 转换 ----------

    def _convert(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self.status_label.setText("正在停止…")
            self.convert_btn.setEnabled(False)
            return
        if not self._video or not self._info:
            InfoBar.warning(title="未选择视频", content="请先选择要转换的视频文件",
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=3000, parent=self)
            return
        out = self.out_edit.text().strip() or str(Path(self._video).with_suffix(".gif"))
        out = str(unique_path(Path(out)))  # 预先占位命名，转换中也可看到最终文件名
        self.status_label.setText(f"转换中 → {out}")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.convert_btn.setText("停止转换")
        self.open_btn.setEnabled(False)
        self._exit_result_mode()

        self._worker = VideoGifWorker(
            self._video, self.start_spin.value(), self.dur_spin.value(),
            self.fps_spin.value(), self.width_spin.value(), out, self)
        self._worker.progressed.connect(self._on_progress)
        self._worker.run_finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, done: int, total: int):
        if self.progress.maximum() != total:
            self.progress.setRange(0, total)
        self.progress.setValue(done)

    def _on_finished(self, ok: bool, out_or_err: str, note: str):
        self.convert_btn.setText("开始转换")
        self.convert_btn.setEnabled(True)
        if ok:
            self._out_dir_used = str(Path(out_or_err).parent)
            self.open_btn.setEnabled(True)
            self.status_label.setText(f"完成 ✅ {note} → {out_or_err}")
            self._result_gif = out_or_err
            self.result_btn.setEnabled(True)
            self._enter_result_mode()
            InfoBar.success(title="转换完成", content=note,
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=4000, parent=self)
        else:
            self.status_label.setText(f"失败：{out_or_err}")
            InfoBar.warning(title="转换失败", content=out_or_err,
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=5000, parent=self)

    def _open_out_dir(self):
        if self._out_dir_used and Path(self._out_dir_used).exists():
            os.startfile(self._out_dir_used)

    # ---------- 动画预览 ----------

    def _enter_result_mode(self):
        """预览区切换为播放转出的 GIF 动画。"""
        if not self._result_gif or not Path(self._result_gif).exists():
            return
        self._showing_result = True
        self._stop_movie()
        movie = QMovie(self._result_gif, parent=self)
        if not movie.isValid():
            self.status_label.setText(f"GIF 无法播放：{self._result_gif}")
            return
        movie.jumpToFrame(0)
        size = movie.currentPixmap().size()
        scale = min(1.0, PREVIEW_W / size.width(), PREVIEW_H / size.height())
        movie.setScaledSize(QSize(max(1, round(size.width() * scale)),
                                  max(1, round(size.height() * scale))))
        movie.setCacheMode(QMovie.CacheAll)
        self._movie = movie
        self.preview_label.setMovie(movie)
        movie.start()
        self.preview_label.setToolTip("点击暂停 / 继续播放")
        self.status_label.setText(f"正在播放转换结果（点击画面可暂停）：{self._result_gif}")

    def _stop_movie(self):
        if self._movie is not None:
            self._movie.stop()
            self.preview_label.setMovie(None)
            self._movie = None
        self.preview_label.setToolTip("")

    def _toggle_movie(self):
        if self._movie is not None and self._showing_result:
            self._movie.setPaused(self._movie.state() == QMovie.Running)

    def _exit_result_mode(self):
        """回到源视频帧预览（拖动滑块、换视频、再次转换时）。"""
        if not self._showing_result:
            return
        self._showing_result = False
        self._stop_movie()
        self._update_preview()

    def shutdown(self):
        """停止动画与后台转换（窗口关闭/页面隐藏时调用）。"""
        self._stop_movie()
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)


class VideoGifDialog(QDialog):
    """独立窗口包装：主体逻辑都在 VideoGifPanel 里。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("视频转 GIF")
        self.resize(820, 580)
        self.panel = VideoGifPanel()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.panel)

    def __getattr__(self, name):
        return getattr(self.panel, name)

    def closeEvent(self, event):
        self.panel.shutdown()
        super().closeEvent(event)
