"""图片处理主视图：文件面板 + 功能设置页 + 固定执行栏。

被左侧导航布局（layout_nav）作为内容页复用；
功能页的切换由外部（导航栏）调用 switch_feature() 驱动。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, SwitchButton

from app import processors as P
from app.sections import (
    CropSection, FilePanel, FormatSection, PreviewPanel, RenameSection,
    ResizeSection, RunBar, WatermarkSection,
)

EMPTY_HINT = "已启用：无（打开功能开关即可自由组合）"


class ProcessorView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("processorView")
        self.setStyleSheet("QWidget#processorView { background-color: #f5f6fa; }")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        # 三栏：可拖动分割条调整宽度
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)
        outer.addWidget(self.splitter, 1)

        # 左：图片文件
        self.files = FilePanel(fixed_width=None)
        self.files.setMinimumWidth(270)
        self.splitter.addWidget(self.files)

        # 中：状态行 + 当前功能的设置页
        self.crop_s = CropSection(self.files.reference_image, self.files.current_path,
                                  on_change=lambda: self.preview.schedule())
        self.wm = WatermarkSection(on_change=lambda: self.preview.schedule())
        middle = QWidget()
        middle.setMinimumWidth(340)
        mv = QVBoxLayout(middle)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.enabled_label = CaptionLabel(EMPTY_HINT)
        top.addWidget(self.enabled_label, 1)
        top.addWidget(BodyLabel("实时预览"))
        self.preview_switch = SwitchButton()
        self.preview_switch.setText("")
        self.preview_switch.setToolTip("显示 / 隐藏右侧实时预览栏")
        self.preview_switch.setChecked(True)
        self.preview_switch.checkedChanged.connect(
            lambda on: self.preview_column.setVisible(on))
        top.addWidget(self.preview_switch)
        mv.addLayout(top)

        self.resize_s = ResizeSection()
        self.fmt = FormatSection()
        self.ren = RenameSection()
        self._pages = [
            ("resize", "调整大小", self.resize_s),
            ("crop", "裁剪", self.crop_s),
            ("wm", "水印", self.wm),
            ("fmt", "格式压缩", self.fmt),
            ("ren", "重命名", self.ren),
        ]
        self.stack = QStackedWidget()
        self._key_index = {}
        for i, (key, text, wdg) in enumerate(self._pages):
            page = QWidget()
            pv = QVBoxLayout(page)
            pv.setContentsMargins(0, 0, 0, 0)
            pv.addWidget(wdg)
            pv.addStretch(1)  # 卡片保持自然高度，顶部对齐
            page.setObjectName(f"page_{key}")
            self.stack.addWidget(page)
            self._key_index[key] = i
        mv.addWidget(self.stack)
        mv.addStretch(1)
        self.splitter.addWidget(middle)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([330, 620, 380])

        # 右：实时预览（可开关，卡片纵向撑满栏高）
        self.preview_column = QWidget()
        self.preview_column.setMinimumWidth(300)
        pcv = QVBoxLayout(self.preview_column)
        pcv.setContentsMargins(0, 0, 0, 0)
        pcv.setSpacing(0)
        self.preview = PreviewPanel(
            self.files.current_path,
            lambda p: (self.resize_s.options(), self.crop_s.effective_options(p),
                       self.wm.options()))
        pcv.addWidget(self.preview, 1)
        self.splitter.addWidget(self.preview_column)
        self.files.selection_changed.connect(self.preview.schedule)
        self.files.selection_changed.connect(self.crop_s.refresh_for_selection)

        # 底部固定执行栏（横跨三栏）
        self.run_bar = RunBar(self.files.files, self.collect_settings)
        outer.addWidget(self.run_bar, 0)

        for _, _, s in self._pages:
            s.switch.checkedChanged.connect(lambda _: self._update_enabled())
        self.stack.setCurrentIndex(0)
        self._update_enabled()

    def switch_feature(self, key: str):
        """切换功能设置页（左侧导航调用）。"""
        self.stack.setCurrentIndex(self._key_index[key])

    def _update_enabled(self):
        names = [t for _, t, s in self._pages if s.switch.isChecked()]
        self.enabled_label.setText(
            ("已启用：" + "、".join(names)) if names else EMPTY_HINT)

    def collect_settings(self) -> P.ProcessSettings:
        return P.ProcessSettings(
            resize=self.resize_s.options(),
            watermark=self.wm.options(),
            fmt=self.fmt.options(),
            rename=self.ren.options(),
            crop=self.crop_s.options(),
            crop_overrides=self.crop_s.crop_overrides(),
        )

    def shutdown(self):
        self.run_bar.shutdown()
