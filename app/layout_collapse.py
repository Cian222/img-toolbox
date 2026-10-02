"""方案二：智能折叠卡片 + 固定执行栏。

保持单列卡片，但未启用的功能折叠成一行，启用即展开；
底部执行栏固定，永远可见。
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QScrollArea, QVBoxLayout, QWidget

from app.sections import (
    CropSection, FilePanel, FormatSection, PreviewPanel, RenameSection,
    ResizeSection, RunBar, WatermarkSection,
)
from app import processors as P


class CollapseWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("图片工具箱 · 折叠布局")
        self.resize(1180, 800)
        self.setMinimumSize(1000, 700)

        central = QWidget()
        central.setObjectName("central")
        central.setStyleSheet("QWidget#central { background-color: #f5f6fa; }")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        content = QWidget()
        h = QHBoxLayout(content)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        h.addWidget(self._build_left(), 0)
        h.addWidget(self._build_right(), 1)
        root.addWidget(content, 1)

        self.run_bar = RunBar(self.files.files, self.collect_settings)
        root.addWidget(self.run_bar, 0)

    def _build_left(self) -> QWidget:
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(12)
        self.files = FilePanel()
        lv.addWidget(self.files, 1)
        return left

    def _build_right(self) -> QWidget:
        self.wm = WatermarkSection()
        self.preview = PreviewPanel(
            self.files.current_path,
            lambda p: (self.resize_s.options(), self.crop_s.effective_options(p),
                       self.wm.options()))
        self.files.selection_changed.connect(self.preview.schedule)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("rightScroll")
        scroll.setStyleSheet("QScrollArea#rightScroll { border: none; background: transparent; }")
        inner = QWidget()
        inner.setObjectName("panelInner")
        inner.setStyleSheet("QWidget#panelInner { background: transparent; }")
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 20, 0)
        v.setSpacing(12)

        self.resize_s = ResizeSection()
        self.crop_s = CropSection(self.files.reference_image, self.files.current_path,
                                  on_change=lambda: self.preview.schedule())
        self.fmt = FormatSection()
        self.ren = RenameSection()
        for card in (self.preview, self.resize_s, self.crop_s, self.wm,
                     self.fmt, self.ren):
            v.addWidget(card)
        v.addStretch(1)
        scroll.setWidget(inner)

        # 智能折叠：开关=展开/收起；标题点击也可手动折叠
        for card in (self.resize_s, self.crop_s, self.wm, self.fmt, self.ren):
            card.set_collapsible(follows_switch=True)
        self.files.selection_changed.connect(self.crop_s.refresh_for_selection)
        return scroll

    def collect_settings(self) -> P.ProcessSettings:
        return P.ProcessSettings(
            resize=self.resize_s.options(),
            watermark=self.wm.options(),
            fmt=self.fmt.options(),
            rename=self.ren.options(),
            crop=self.crop_s.options(),
            crop_overrides=self.crop_s.crop_overrides(),
        )

    def closeEvent(self, event):
        self.run_bar.shutdown()
        super().closeEvent(event)
