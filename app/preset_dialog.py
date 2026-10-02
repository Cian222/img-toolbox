"""预设管理对话框：添加 / 删除自定义裁剪比例与像素尺寸。"""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidgetItem, QTabWidget, QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    InfoBar, InfoBarPosition, ListWidget, PushButton, SpinBox, SubtitleLabel,
)

from app import presets


class PresetManageDialog(QDialog):
    """关闭时若发生修改会发出 presets_changed 信号。"""

    presets_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理预设")
        self.resize(420, 460)
        self.setStyleSheet("QDialog { background: #f5f6fa; }")

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 14)
        v.setSpacing(10)
        tabs = QTabWidget()
        tabs.addTab(self._build_ratio_tab(), "比例预设")
        tabs.addTab(self._build_size_tab(), "像素预设")
        v.addWidget(tabs, 1)
        v.addWidget(QLabel("预设保存在 " + str(presets.PRESETS_FILE)))

    # ---------- 比例 ----------

    def _build_ratio_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)
        v.addWidget(SubtitleLabel("添加比例预设"))
        row = QHBoxLayout()
        self.rw_spin = SpinBox()
        self.rw_spin.setRange(1, 10000)
        self.rw_spin.setValue(5)
        self.rh_spin = SpinBox()
        self.rh_spin.setRange(1, 10000)
        self.rh_spin.setValue(4)
        add_btn = PushButton("添加")
        add_btn.clicked.connect(self._add_ratio)
        row.addWidget(QLabel("宽"))
        row.addWidget(self.rw_spin, 1)
        row.addWidget(QLabel("高"))
        row.addWidget(self.rh_spin, 1)
        row.addWidget(add_btn)
        v.addLayout(row)

        v.addWidget(SubtitleLabel("我的自定义预设"))
        self.ratio_list = ListWidget()
        v.addWidget(self.ratio_list, 1)
        del_btn = PushButton("删除选中")
        del_btn.clicked.connect(self._del_ratio)
        v.addWidget(del_btn)
        self._reload_ratio_list()
        return w

    def _reload_ratio_list(self):
        self.ratio_list.clear()
        for label, rw, rh in presets.load_presets()["custom_ratios"]:
            item = QListWidgetItem(f"{label}（{rw}×{rh}）")
            item.setData(Qt.UserRole, (label, rw, rh))
            self.ratio_list.addItem(item)

    def _add_ratio(self):
        rw, rh = self.rw_spin.value(), self.rh_spin.value()
        label = presets.ratio_label(rw, rh)
        customs = presets.load_presets()["custom_ratios"]
        if any(lb == label for lb, _, _ in customs) or \
                any(lb == label for lb, _, _ in presets.DEFAULT_RATIOS):
            self._warn(f"比例 {label} 已存在")
            return
        customs.append((label, rw, rh))
        presets.save_custom(customs, presets.load_presets()["custom_sizes"])
        self._reload_ratio_list()
        self.presets_changed.emit()

    def _del_ratio(self):
        item = self.ratio_list.currentItem()
        if not item:
            self._warn("请先在列表中选中一项")
            return
        label, rw, rh = item.data(Qt.UserRole)
        customs = [c for c in presets.load_presets()["custom_ratios"]
                   if c[0] != label]
        presets.save_custom(customs, presets.load_presets()["custom_sizes"])
        self._reload_ratio_list()
        self.presets_changed.emit()

    # ---------- 像素 ----------

    def _build_size_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)
        v.addWidget(SubtitleLabel("添加像素预设（裁剪后输出尺寸）"))
        row = QHBoxLayout()
        self.sw_spin = SpinBox()
        self.sw_spin.setRange(1, 10000)
        self.sw_spin.setValue(1080)
        self.sh_spin = SpinBox()
        self.sh_spin.setRange(1, 10000)
        self.sh_spin.setValue(1920)
        add_btn = PushButton("添加")
        add_btn.clicked.connect(self._add_size)
        row.addWidget(QLabel("宽"))
        row.addWidget(self.sw_spin, 1)
        row.addWidget(QLabel("高"))
        row.addWidget(self.sh_spin, 1)
        row.addWidget(add_btn)
        v.addLayout(row)

        v.addWidget(SubtitleLabel("我的自定义预设"))
        self.size_list = ListWidget()
        v.addWidget(self.size_list, 1)
        del_btn = PushButton("删除选中")
        del_btn.clicked.connect(self._del_size)
        v.addWidget(del_btn)
        self._reload_size_list()
        return w

    def _reload_size_list(self):
        self.size_list.clear()
        for sw, sh in presets.load_presets()["custom_sizes"]:
            item = QListWidgetItem(f"{sw}×{sh}")
            item.setData(Qt.UserRole, (sw, sh))
            self.size_list.addItem(item)

    def _add_size(self):
        sw, sh = self.sw_spin.value(), self.sh_spin.value()
        customs = presets.load_presets()["custom_sizes"]
        if (sw, sh) in customs or (sw, sh) in presets.DEFAULT_SIZES:
            self._warn(f"{sw}×{sh} 已存在")
            return
        customs.append((sw, sh))
        presets.save_custom(presets.load_presets()["custom_ratios"], customs)
        self._reload_size_list()
        self.presets_changed.emit()

    def _del_size(self):
        item = self.size_list.currentItem()
        if not item:
            self._warn("请先在列表中选中一项")
            return
        sw, sh = item.data(Qt.UserRole)
        customs = [c for c in presets.load_presets()["custom_sizes"]
                   if tuple(c) != (sw, sh)]
        presets.save_custom(presets.load_presets()["custom_ratios"], customs)
        self._reload_size_list()
        self.presets_changed.emit()

    # ---------- 公共 ----------

    def _warn(self, msg: str):
        InfoBar.warning(title="无法添加", content=msg, orient=Qt.Horizontal,
                        isClosable=True, position=InfoBarPosition.TOP,
                        duration=3000, parent=self)
