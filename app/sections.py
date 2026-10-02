"""可复用的界面组件：文件面板、实时预览、五个功能区块、执行栏。

三种布局（标签页 / 智能折叠 / 左侧导航）共用这些组件，
功能设置与收集逻辑只写一份。
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageOps
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QColorDialog, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QScrollArea, QStackedWidget, QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CardWidget, CheckBox, ComboBox, DoubleSpinBox,
    InfoBar, InfoBarPosition, LineEdit, PrimaryPushButton,
    ProgressBar, PushButton, RadioButton, Slider, SpinBox, SubtitleLabel,
    SwitchButton,
)

from app import presets as PS
from app import processors as P
from app.crop_dialog import CropDialog
from app.preset_dialog import PresetManageDialog
from app.workers import ProcessWorker

PREVIEW_W, PREVIEW_H = 300, 210
IMAGE_FILTER = "图片 (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.gif)"


def synced_spinbox(slider, lo: int, hi: int) -> SpinBox:
    """与滑块双向同步的数字输入框。"""
    sb = SpinBox()
    sb.setRange(lo, hi)
    sb.setValue(slider.value())
    slider.valueChanged.connect(sb.setValue)
    sb.valueChanged.connect(slider.setValue)
    sb.setFixedWidth(76)
    return sb


class DropList(QListWidget):
    paths_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def _accept(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragEnterEvent(self, event):
        self._accept(event)

    def dragMoveEvent(self, event):
        self._accept(event)

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)


def hwrap(*widgets, stretch_first: bool = True) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    if widgets:
        h.addWidget(widgets[0], 1 if stretch_first else 0)
    for extra in widgets[1:]:
        h.addWidget(extra, 0)
    return w


class _HeaderRow(QWidget):
    clicked = Signal()

    def __init__(self, title: str):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.mark = CaptionLabel("▾")
        h.addWidget(self.mark)
        h.addWidget(SubtitleLabel(title))
        h.addStretch(1)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def set_mark(self, text: str):
        self.mark.setText(text)


class SectionBase(CardWidget):
    """功能区块：标题 + 启用开关 + 内容区；可折叠（折叠布局用）。"""

    def __init__(self, title: str, collapsible: bool = False):
        super().__init__()
        self._collapsible = collapsible
        self._fold_follows_switch = False
        self._folded = False
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(16, 12, 16, 16)
        self.v.setSpacing(10)

        head = QHBoxLayout()
        self.header = _HeaderRow(title)
        self.header.clicked.connect(self._toggle_fold)
        head.addWidget(self.header, 1)
        self.switch = SwitchButton()
        self.switch.setText("")
        self.switch.setToolTip("启用 / 停用该功能")
        head.addWidget(self.switch, 0, Qt.AlignRight)
        self.v.addLayout(head)

        self.body = QWidget()
        self.body_v = QVBoxLayout(self.body)
        self.body_v.setContentsMargins(0, 0, 0, 0)
        self.body_v.setSpacing(10)
        self.v.addWidget(self.body)

    # ---- 供子类使用的构建辅助 ----

    def row(self, label_text: str, widget, label_w: int = 88) -> QWidget:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        lab = BodyLabel(label_text)
        lab.setFixedWidth(label_w)
        h.addWidget(lab)
        h.addWidget(widget, 1)
        self.body_v.addWidget(wrap)
        return wrap

    def add(self, widget):
        self.body_v.addWidget(widget)
        return widget

    def add_layout(self, layout):
        self.v.addLayout(layout)

    # ---- 折叠 ----

    def set_collapsible(self, follows_switch: bool):
        self._collapsible = True
        self._fold_follows_switch = follows_switch
        self.set_folded(not self.switch.isChecked())
        self.switch.checkedChanged.connect(
            lambda on: self.set_folded(not on))

    def _toggle_fold(self):
        if self._collapsible:
            self.set_folded(not self._folded)

    def set_folded(self, folded: bool):
        self._folded = folded
        self.body.setVisible(not folded)
        self.header.set_mark("▸" if folded else "▾")


# ================= 文件面板 =================

class FilePanel(CardWidget):
    selection_changed = Signal()

    def __init__(self, fixed_width: int | None = 330):
        super().__init__()
        if fixed_width:
            self.setFixedWidth(fixed_width)
        else:
            self.setMinimumWidth(280)  # 放进可拖动分割条时不锁宽度
        self._files: list[Path] = []
        self._skipped: set = set()     # 跳过处理的 key 集合
        self._marks: dict = {}         # key → 裁剪标记（✂ / ⊘）
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(8)

        video_btn = PushButton("视频转 GIF")
        video_btn.setToolTip("打开视频转 GIF 窗口：可选片段、时长、帧率、宽度")
        video_btn.clicked.connect(self._open_video_gif)
        layout_btn = PushButton("切换布局")
        layout_btn.setToolTip("换一种界面排版（标签页 / 智能折叠 / 左侧导航），选定后自动重启")
        layout_btn.clicked.connect(self._switch_layout)
        self.video_btn = video_btn        # 引用保留，导航布局里会隐藏（功能进了侧栏）
        self.layout_btn = layout_btn
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(video_btn, 1)
        btn_row.addWidget(layout_btn, 1)
        v.addLayout(btn_row)

        head = QHBoxLayout()
        head.addWidget(SubtitleLabel("图片文件"))
        head.addStretch(1)
        self.count_label = CaptionLabel("共 0 个文件")
        head.addWidget(self.count_label)
        v.addLayout(head)

        self.file_list = DropList()
        self.file_list.setStyleSheet(
            "QListWidget { background: white; border: 1px solid #e3e5ec;"
            " border-radius: 8px; font-size: 12px; }"
            "QListWidget::item { padding: 4px 6px; border-radius: 4px; }"
            "QListWidget::item:selected { background: #d8e6ff; color: #1a1a1a; }"
        )
        self.file_list.itemSelectionChanged.connect(self.selection_changed.emit)
        self.file_list.paths_dropped.connect(self.add_paths)
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self._show_list_menu)
        v.addWidget(self.file_list, 1)

        row1 = QHBoxLayout()
        b1 = PushButton("添加文件")
        b2 = PushButton("添加文件夹")
        b1.clicked.connect(self._add_files_dialog)
        b2.clicked.connect(self._add_folder_dialog)
        row1.addWidget(b1, 1)
        row1.addWidget(b2, 1)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        self.skip_btn = PushButton("跳过选中")
        self.skip_btn.setToolTip("标记/取消这张图：跳过后任何功能都不处理它")
        self.skip_btn.clicked.connect(lambda: self.toggle_skip())
        b3 = PushButton("清空")
        b3.clicked.connect(self._clear_files)
        row2.addWidget(self.skip_btn, 1)
        row2.addWidget(b3, 1)
        v.addLayout(row2)

        v.addWidget(CaptionLabel("支持拖入文件 / 文件夹；右键列表项可跳过/恢复处理"))

    # ---- 列表 ----

    def files(self) -> list[Path]:
        """参与处理的文件（跳过的不含在内）。"""
        return [p for p in self._files
                if str(p.resolve()).lower() not in self._skipped]

    def is_skipped(self, path) -> bool:
        return str(Path(path).resolve()).lower() in self._skipped

    def toggle_skip(self, path=None) -> bool:
        """切换某张图片（默认当前选中）的跳过状态，返回是否跳过。"""
        path = path or self.current_path()
        if not path:
            return False
        p = Path(path)
        key = str(p.resolve()).lower()
        if key in self._skipped:
            self._skipped.discard(key)
        else:
            self._skipped.add(key)
        self._refresh_items()
        self._refresh_count()
        return key in self._skipped

    def set_file_mark(self, path: str, mark: str):
        """显示裁剪标记（✂ / ⊘），由 CropSection 驱动。"""
        key = str(Path(path).resolve()).lower() if path else ""
        if not key:
            return
        if mark:
            self._marks[key] = mark
        else:
            self._marks.pop(key, None)
        self._refresh_items()

    def _item_text(self, p: Path) -> str:
        key = str(p.resolve()).lower()
        kb = p.stat().st_size / 1024
        extra = (" [跳过]" if key in self._skipped else "") + self._marks.get(key, "")
        return f"{p.name}   ({kb:.0f} KB){extra}"

    def _refresh_items(self):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            p = Path(item.data(Qt.UserRole))
            if not p.exists():
                continue
            item.setText(self._item_text(p))
            item.setForeground(QColor("#9a9a9a")
                               if str(p.resolve()).lower() in self._skipped
                               else self.file_list.palette().text())

    def _refresh_count(self):
        keys = {str(p.resolve()).lower() for p in self._files}
        skipped = len(self._skipped & keys)
        txt = f"共 {len(self._files)} 个文件"
        if skipped:
            txt += f"（将处理 {len(self._files) - skipped}，跳过 {skipped}）"
        self.count_label.setText(txt)

    def _show_list_menu(self, pos):
        item = self.file_list.itemAt(pos)
        if item is None:
            return
        from PySide6.QtWidgets import QMenu
        p = Path(item.data(Qt.UserRole))
        menu = QMenu(self)
        act = menu.addAction("恢复处理" if self.is_skipped(p)
                             else "跳过处理（任何功能都不处理这张）")
        act.triggered.connect(lambda: self.toggle_skip(str(p)))
        menu.exec(self.file_list.mapToGlobal(pos))

    def current_path(self) -> str | None:
        if self.file_list.selectedItems():
            return self.file_list.selectedItems()[0].data(Qt.UserRole)
        if self._files:
            return str(self._files[0])
        return None

    def _add_files_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self.window(), "选择图片", "", IMAGE_FILTER)
        self.add_paths(files)

    def _add_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self.window(), "选择文件夹")
        if d:
            self.add_paths([d])

    def add_paths(self, paths):
        new = P.collect_images(paths)
        existing = {str(p.resolve()).lower() for p in self._files}
        for p in new:
            key = str(p.resolve()).lower()
            if key in existing:
                continue
            existing.add(key)
            self._files.append(p)
            item = QListWidgetItem(self._item_text(p))
            item.setData(Qt.UserRole, str(p))
            self.file_list.addItem(item)
        self._refresh_count()
        if self._files and not self.file_list.selectedItems():
            self.file_list.setCurrentRow(0)
        self.selection_changed.emit()

    def _clear_files(self):
        self._files.clear()
        self.file_list.clear()
        self._refresh_count()
        self.selection_changed.emit()

    def reference_image(self) -> Image.Image | None:
        """当前选中或第一张图片（裁剪参考图用）。"""
        path = self.current_path()
        if not path:
            return None
        with Image.open(path) as im:
            im.load()
            img = ImageOps.exif_transpose(im)
        img = P._normalize_mode(img).convert("RGB")
        img.thumbnail((1200, 1200), Image.LANCZOS)
        return img

    # ---- 视频转 GIF 入口 ----

    def _open_video_gif(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            InfoBar.warning(
                title="缺少依赖", duration=5000, isClosable=True,
                content="视频转 GIF 需要 opencv-python，请先执行：pip install opencv-python",
                orient=Qt.Horizontal, position=InfoBarPosition.TOP,
                parent=self.window())
            return
        from app.video_dialog import VideoGifDialog
        VideoGifDialog(self.window()).exec()

    # ---- 切换布局 ----

    def _switch_layout(self):
        from app import main_window as MW
        current = getattr(self.window(), "layout_key", None)
        dlg = MW.LayoutChooserDialog(self.window(), current=current)
        if not dlg.exec() or not dlg.chosen:
            return
        if dlg.chosen == current:
            InfoBar.info(title="布局未变化",
                         content=f"当前已经在使用「{MW.LAYOUTS[current][0]}」",
                         orient=Qt.Horizontal, isClosable=True,
                         position=InfoBarPosition.TOP, duration=3000,
                         parent=self.window())
            return
        MW.save_layout(dlg.chosen)
        MW.relaunch()          # 拉起新布局的进程
        self.window().close()  # 关闭旧窗口，旧进程随之退出


# ================= 实时预览 =================

PREVIEW_MIN_W, PREVIEW_MIN_H = 260, 190


class _PreviewLabel(QLabel):
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class _PreviewViewer(QDialog):
    """大图查看器：原始分辨率 + 滚动查看，双击或 Esc 关闭。"""

    def __init__(self, name: str, img: Image.Image, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"预览大图 — {name}（滚动条查看，双击或 Esc 关闭）")
        from PySide6.QtGui import QGuiApplication
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(int(geo.width() * 0.72), int(geo.height() * 0.78))
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("viewerScroll")
        scroll.setStyleSheet("QScrollArea#viewerScroll { border: none; }")
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setPixmap(QPixmap.fromImage(ImageQt(img.convert("RGBA"))))
        self.image_label.mouseDoubleClickEvent = lambda _e: self.close()
        scroll.setWidget(self.image_label)
        v.addWidget(scroll)


class PreviewPanel(CardWidget):
    """实时预览：显示 裁剪 → 缩放 → 水印 的完整流水线效果。

    get_pipeline() 返回 (ResizeOptions, CropOptions, WatermarkOptions)。
    """

    def __init__(self, get_path, get_pipeline):
        super().__init__()
        self._get_path = get_path
        self._get_pipeline = get_pipeline
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 16)
        v.setSpacing(10)
        v.addWidget(SubtitleLabel("实时预览（当前选中图片）"))
        self.preview_label = _PreviewLabel()
        self.preview_label.setMinimumSize(PREVIEW_MIN_W, PREVIEW_MIN_H)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setObjectName("previewBox")
        self.preview_label.setStyleSheet(
            "QLabel#previewBox { background: #eceef4; border-radius: 8px; }")
        self.preview_label.doubleClicked.connect(self.open_viewer)
        v.addWidget(self.preview_label, 1)
        self.preview_tip = CaptionLabel("添加文件后自动显示处理效果")
        v.addWidget(self.preview_tip)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.refresh)
        self.preview_label.installEventFilter(self)

    def eventFilter(self, obj, event):
        # 面板被拖宽 / 窗口缩放时，预览图跟随重渲染
        # （基类构造期间本方法也会被 qfw 内部事件链调用，需判空）
        label = getattr(self, "preview_label", None)
        if label is not None and obj is label and event.type() == QEvent.Resize:
            self.schedule()
        return super().eventFilter(obj, event)

    def schedule(self, *_):
        self._timer.start()

    def _load_processed(self, contain_box=None):
        """加载当前图片并应用 裁剪→缩放→水印 流水线，返回 (PIL图, 提示)。"""
        path = self._get_path()
        if not path:
            return None, "添加文件后自动显示处理效果"
        with Image.open(path) as im:
            im.load()
            img = ImageOps.exif_transpose(im)
        img = P._normalize_mode(img)
        if contain_box:
            img = ImageOps.contain(img, contain_box)
        resize_opt, crop_opt, wm_opt = self._get_pipeline(path)
        parts = []
        if crop_opt.enabled:
            img = P.apply_crop(img, crop_opt)
            parts.append("已裁剪")
        if resize_opt.enabled:
            img = P.resize_image(img, resize_opt.mode, resize_opt.value)
            parts.append("已缩放")
        if wm_opt.enabled:
            if wm_opt.kind == "text" and not wm_opt.text.strip():
                return img, "请先输入水印文字"
            img = P.apply_watermark(img, wm_opt)
            parts.append("已加水印")
        tip = ("预览 = " + "、".join(parts) + "（双击看大图）") if parts \
            else "原图预览（双击看大图）"
        return img, tip

    def refresh(self):
        path = self._get_path()
        if not path:
            self.preview_label.setPixmap(QPixmap())
            self.preview_tip.setText("添加文件后自动显示处理效果")
            return
        try:
            lab = self.preview_label
            box = (max(120, lab.width() - 12), max(90, lab.height() - 12))
            img, tip = self._load_processed(contain_box=box)
            self.preview_label.setPixmap(
                QPixmap.fromImage(ImageQt(img.convert("RGBA"))))
            self.preview_tip.setText(tip)
        except Exception as e:
            self.preview_label.setPixmap(QPixmap())
            self.preview_tip.setText(f"预览失败：{e}")

    def open_viewer(self):
        """双击预览图：弹出原始分辨率的流水线效果图。"""
        path = self._get_path()
        if not path:
            return None
        try:
            img, _ = self._load_processed(contain_box=None)
        except Exception as e:
            InfoBar.warning(title="打开大图失败", content=str(e),
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=4000,
                            parent=self.window())
            return None
        dlg = _PreviewViewer(Path(path).name, img, self.window())
        dlg.show()
        return dlg


# ================= 各功能区块 =================

class ResizeSection(SectionBase):
    def __init__(self):
        super().__init__("调整大小")
        self.mode = ComboBox()
        self.mode.addItems(["按百分比缩放", "指定宽度", "指定高度", "限制最长边"])
        self.value = DoubleSpinBox()
        self.value.setRange(1, 100000)
        self.value.setDecimals(1)
        self.value.setValue(50.0)
        self.value.setSuffix("%")
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.row("方式", hwrap(self.mode, self.value))
        tip = CaptionLabel("宽度 / 高度 / 最长边模式只在缩小时生效，不会放大图片")
        tip.setWordWrap(True)
        self.add(tip)

    def _mode_changed(self, idx: int):
        self.value.setSuffix("%" if idx == 0 else " px")

    def options(self) -> P.ResizeOptions:
        modes = ["percent", "width", "height", "longest"]
        return P.ResizeOptions(enabled=self.switch.isChecked(),
                               mode=modes[self.mode.currentIndex()],
                               value=self.value.value())


class CropSection(SectionBase):
    file_mark_changed = Signal(str, str)  # 小写路径, 标记（" ✂" / " ⊘" / ""）

    def __init__(self, get_reference_image=None, get_reference_path=None,
                 on_change=None):
        super().__init__("裁剪")
        self._get_reference_image = get_reference_image
        self._get_reference_path = get_reference_path
        self._on_change = on_change
        self._batch_rect: tuple | None = None   # 批量区域（相对坐标）
        self._own_rects: dict = {}              # key → 单独区域（值可为 None=尚未画框）
        self._skip: set = set()                 # 不裁剪的 key 集合
        self._ref_img: Image.Image | None = None

        # 当前图片状态（三选一）
        self.state_combo = ComboBox()
        self.state_combo.addItems(["跟随批量", "单独区域", "不裁剪"])
        self.state_combo.setToolTip(
            "跟随批量：使用下方批量裁剪框\n"
            "单独区域：这张用自己的框（点“画框…”）\n"
            "不裁剪：这张跳过裁剪")
        self.state_combo.currentIndexChanged.connect(self._on_state_changed)
        self.row("当前图片", self.state_combo)

        # 批量裁剪框
        self.batch_draw_btn = PushButton("画框…")
        self.batch_clear_btn = PushButton("清除")
        self.batch_draw_btn.clicked.connect(lambda: self._draw("batch"))
        self.batch_clear_btn.clicked.connect(self._clear_batch)
        self.row("批量裁剪框",
                 hwrap(self.batch_draw_btn, self.batch_clear_btn,
                       stretch_first=False))
        self.batch_info = CaptionLabel("未设置")
        self.add(self.batch_info)

        # 比例 / 像素预设
        self.ratio_combo = ComboBox()
        manage_btn = PushButton("管理预设…")
        manage_btn.clicked.connect(self._open_manage_presets)
        self.row("比例预设", hwrap(self.ratio_combo, manage_btn))

        self.size_combo = ComboBox()
        self.row("像素预设", self.size_combo)

        # 当前图片自己的框（仅“单独区域”状态显示）
        self.own_row = QWidget()
        oh = QHBoxLayout(self.own_row)
        oh.setContentsMargins(0, 0, 0, 0)
        oh.setSpacing(8)
        self.own_draw_btn = PushButton("画框…")
        self.own_clear_btn = PushButton("清除")
        self.own_draw_btn.clicked.connect(lambda: self._draw("own"))
        self.own_clear_btn.clicked.connect(self._clear_own)
        oh.addWidget(self.own_draw_btn)
        oh.addWidget(self.own_clear_btn)
        oh.addStretch(1)
        self.add(self.own_row)
        self.own_info = CaptionLabel("尚未画框")
        self.add(self.own_info)

        # 生效区域缩略图 + 汇总信息
        info_row = QHBoxLayout()
        info_row.setSpacing(10)
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(132, 99)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setObjectName("cropMini")
        self.preview_label.setStyleSheet(
            "QLabel#cropMini { background: #eceef4; border-radius: 6px; }")
        info_row.addWidget(self.preview_label, 0, Qt.AlignTop)
        self.info = CaptionLabel()
        self.info.setWordWrap(True)
        info_row.addWidget(self.info, 1)
        self.body_v.addLayout(info_row)  # 放进折叠体，折叠时一起隐藏

        tip = CaptionLabel(
            "每张图三选一：跟随批量 / 单独区域（只对这张生效）/ 不裁剪。"
            "选了像素预设时统一缩放到该尺寸，比例预设锁定框形状，"
            "切换预设时已有区域自动重适配。文件列表标记：✂ 单独区域，⊘ 不裁剪")
        tip.setWordWrap(True)
        self.add(tip)
        self.refresh_presets()
        self._update_all()
        self.ratio_combo.currentIndexChanged.connect(self._on_ratio_changed)
        self.size_combo.currentIndexChanged.connect(self._on_ratio_changed)

    # ---- 状态与区域 ----

    def _key(self) -> str:
        path = self._get_reference_path() if self._get_reference_path else None
        return str(Path(path).resolve()).lower() if path else ""

    def _state_of(self, key: str) -> int:
        if key in self._skip:
            return 2
        if key in self._own_rects:
            return 1
        return 0

    def _effective_rect(self, key: str):
        """返回 (区域或 None, 是否为单独状态)。"""
        if key in self._skip:
            return None, False
        if key in self._own_rects:
            return self._own_rects[key], True
        return self._batch_rect, False

    def set_reference(self, img: Image.Image | None):
        self._ref_img = img

    def refresh_for_selection(self):
        """文件列表选中变化时：刷新参考图与当前图片状态显示。"""
        self.set_reference(self._get_reference_image() if self._get_reference_image else None)
        self._update_all()

    def set_rect(self, rect: tuple | None):
        """设置批量裁剪区域（脚本/测试用）。"""
        self._batch_rect = rect
        self._update_all()
        self._notify()

    def set_file_rect(self, path: str, rect: tuple | None):
        """设置某张图片的单独区域，并自动切到“单独区域”状态。"""
        key = str(Path(path).resolve()).lower() if path else ""
        if not key:
            return
        if rect is not None:
            self._own_rects[key] = rect
            self._skip.discard(key)
        else:
            self._own_rects.pop(key, None)
        self._emit_mark(key)
        self._update_all()
        self._notify()

    def set_file_state(self, path: str, state: str):
        """设置某张图片的裁剪状态：follow / own / skip（脚本/测试用）。"""
        key = str(Path(path).resolve()).lower() if path else ""
        if not key:
            return
        self._skip.discard(key)
        self._own_rects.pop(key, None)
        if state == "skip":
            self._skip.add(key)
        elif state == "own":
            self._own_rects[key] = None
        self._emit_mark(key)
        self._update_all()
        self._notify()

    def _emit_mark(self, key: str):
        if key in self._skip:
            mark = " ⊘"
        elif key in self._own_rects:
            mark = " ✂"
        else:
            mark = ""
        self.file_mark_changed.emit(key, mark)

    def _on_state_changed(self, idx: int):
        """当前图片三态切换：清理旧状态并记录新状态。"""
        key = self._key()
        if not key:
            self._update_all()
            return
        self._skip.discard(key)
        self._own_rects.pop(key, None)
        if idx == 2:                 # 不裁剪
            self._skip.add(key)
        elif idx == 1:               # 单独区域（允许先选状态、再画框）
            self._own_rects.setdefault(key, None)
        self._emit_mark(key)
        self._update_all()
        self._notify()

    def _notify(self):
        if self._on_change:
            self._on_change()

    # ---- 按钮 ----

    def _draw(self, mode: str):
        per_file = mode == "own"
        img = self._get_reference_image() if self._get_reference_image else None
        if img is None:
            InfoBar.warning(title="没有图片", content="请先添加图片，裁剪需要一张参考图",
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=3000,
                            parent=self.window())
            return
        key = self._key()
        if per_file and not key:
            InfoBar.warning(title="未选中图片", content="请在左侧列表选中要单独裁剪的图片",
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=3000,
                            parent=self.window())
            return
        self._ref_img = img
        ratio = self.current_ratio()
        pt = self.current_pixel_target()
        if pt:
            ratio = pt[0] / pt[1]
        init = self._own_rects.get(key) if per_file else self._batch_rect
        dlg = CropDialog(img, ratio=ratio, pixel_target=pt,
                         init_rel=init, parent=self.window())
        if dlg.exec():
            rect = dlg.rect_rel()
            if per_file:
                self._own_rects[key] = rect
                self._skip.discard(key)
                self._emit_mark(key)
            else:
                self._batch_rect = rect
            self._update_all()
            self._notify()

    def _clear_batch(self):
        self._batch_rect = None
        self._update_all()
        self._notify()

    def _clear_own(self):
        key = self._key()
        if key:
            self._own_rects.pop(key, None)
        self._update_all()
        self._notify()

    # ---- 预设 ----

    def refresh_presets(self):
        ratios = PS.all_ratios()
        self._ratio_values = [None] + [(w, h) for _, w, h in ratios]
        keep = self.ratio_combo.currentText()
        self.ratio_combo.blockSignals(True)
        self.ratio_combo.clear()
        self.ratio_combo.addItem("自由裁剪")
        for label, _, _ in ratios:
            self.ratio_combo.addItem(label)
        idx = self.ratio_combo.findText(keep)
        self.ratio_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.ratio_combo.blockSignals(False)

        sizes = PS.all_sizes()
        self._size_values = [None] + list(sizes)
        keep = self.size_combo.currentText()
        self.size_combo.blockSignals(True)
        self.size_combo.clear()
        self.size_combo.addItem("不指定")
        for w, h in sizes:
            self.size_combo.addItem(f"{w}×{h}")
        idx = self.size_combo.findText(keep)
        self.size_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.size_combo.blockSignals(False)

    def _open_manage_presets(self):
        dlg = PresetManageDialog(self.window())
        dlg.presets_changed.connect(self.refresh_presets)
        dlg.exec()

    def current_ratio(self) -> float | None:
        idx = self.ratio_combo.currentIndex()
        val = self._ratio_values[idx] if 0 <= idx < len(self._ratio_values) else None
        return (val[0] / val[1]) if val else None

    def current_pixel_target(self) -> tuple | None:
        idx = self.size_combo.currentIndex()
        val = self._size_values[idx] if 0 <= idx < len(self._size_values) else None
        return val

    def _on_ratio_changed(self):
        """切换比例/像素预设：批量区域与当前单图区域自动重适配。"""
        ratio = self.current_ratio()
        pt = self.current_pixel_target()
        if pt:
            ratio = pt[0] / pt[1]
        if ratio and self._ref_img:
            if self._batch_rect:
                self._batch_rect = self._refit(self._batch_rect, ratio)
            key = self._key()
            if key in self._own_rects and self._own_rects[key]:
                self._own_rects[key] = self._refit(self._own_rects[key], ratio)
        self._update_all()
        self._notify()

    def _refit(self, rect: tuple, ratio: float) -> tuple:
        if self._ref_img is None:
            return rect
        W, H = self._ref_img.size
        x, y, w, h = rect
        pw, ph = w * W, h * H
        if pw / max(ph, 1e-6) > ratio:
            pw = ph * ratio          # 太宽 → 收缩宽度
        else:
            ph = pw / ratio          # 太高 → 收缩高度
        nw, nh = pw / W, ph / H
        cx, cy = x + w / 2, y + h / 2
        nx = min(max(cx - nw / 2, 0.0), 1 - nw)
        ny = min(max(cy - nh / 2, 0.0), 1 - nh)
        return (nx, ny, nw, nh)

    # ---- 汇总显示 ----

    def _update_all(self):
        key = self._key()
        idx = self._state_of(key) if key else 0
        self.state_combo.blockSignals(True)
        self.state_combo.setCurrentIndex(idx)
        self.state_combo.blockSignals(False)
        self.own_row.setVisible(idx == 1)
        self.own_info.setVisible(idx == 1)

        pt = self.current_pixel_target()
        pt_txt = f"，输出统一缩放至 {pt[0]}×{pt[1]} px" if pt else ""
        if self._batch_rect:
            x, y, w, h = self._batch_rect
            self.batch_info.setText(
                f"批量区域：x {x:.0%}，y {y:.0%}，宽 {w:.0%}，高 {h:.0%}{pt_txt}")
        else:
            self.batch_info.setText("未设置批量区域")
        if idx == 1:
            r = self._own_rects.get(key)
            self.own_info.setText(
                f"当前图片：x {r[0]:.0%}，y {r[1]:.0%}，宽 {r[2]:.0%}，高 {r[3]:.0%}"
                if r else "当前图片：尚未画框（画框前这张不裁剪）")

        path = self._get_reference_path() if self._get_reference_path else None
        eff = self.effective_options(path) if path else None
        summary = (f"已单独设置 {len(self._own_rects)} 张，不裁剪 {len(self._skip)} 张")
        if not self.switch.isChecked():
            self.preview_label.setPixmap(QPixmap())
            self.info.setText(f"裁剪未启用。{summary}")
        elif eff and eff.enabled and self._ref_img:
            self.info.setText(
                f"当前图片生效区域：x {eff.x:.0%}，y {eff.y:.0%}，"
                f"宽 {eff.w:.0%}，高 {eff.h:.0%}{pt_txt}；{summary}")
            W, H = self._ref_img.size
            box = (round(eff.x * W), round(eff.y * H),
                   round((eff.x + eff.w) * W), round((eff.y + eff.h) * H))
            crop = self._ref_img.crop(box)
            crop.thumbnail((124, 91), Image.LANCZOS)
            self.preview_label.setPixmap(QPixmap.fromImage(ImageQt(crop)))
        else:
            self.preview_label.setPixmap(QPixmap())
            self.info.setText(f"当前图片不裁剪。{summary}")

    # ---- 对外选项 ----

    def options(self) -> P.CropOptions:
        """批量裁剪选项（不含单图覆盖）。"""
        r = self._batch_rect
        pt = self.current_pixel_target() or (0, 0)
        return P.CropOptions(
            enabled=self.switch.isChecked() and r is not None,
            x=r[0] if r else 0.0, y=r[1] if r else 0.0,
            w=r[2] if r else 1.0, h=r[3] if r else 1.0,
            target_w=pt[0], target_h=pt[1],
        )

    def crop_overrides(self) -> dict:
        """按文件覆盖表（键为小写绝对路径）：单独区域 / 不裁剪。"""
        pt = self.current_pixel_target() or (0, 0)
        out = {}
        for key in set(self._own_rects) | self._skip:
            if key in self._skip:
                out[key] = P.CropOptions(enabled=False,
                                         target_w=pt[0], target_h=pt[1])
            else:
                r = self._own_rects[key]
                out[key] = P.CropOptions(enabled=bool(r),
                                         x=r[0] if r else 0.0,
                                         y=r[1] if r else 0.0,
                                         w=r[2] if r else 1.0,
                                         h=r[3] if r else 1.0,
                                         target_w=pt[0], target_h=pt[1])
        return out

    def effective_options(self, path) -> P.CropOptions:
        """某张图片实际生效的裁剪选项（单独/不裁剪 > 批量），实时预览用。"""
        key = str(Path(path).resolve()).lower() if path else ""
        pt = self.current_pixel_target() or (0, 0)
        rect, _own = self._effective_rect(key)
        if rect is None:
            return P.CropOptions(enabled=False, target_w=pt[0], target_h=pt[1])
        return P.CropOptions(
            enabled=self.switch.isChecked(),
            x=rect[0], y=rect[1], w=rect[2], h=rect[3],
            target_w=pt[0], target_h=pt[1],
        )


class WatermarkSection(SectionBase):
    def __init__(self, on_change=None):
        super().__init__("水印")
        self._on_change = on_change
        self._color = QColor("#FFFFFF")

        self.kind_combo = ComboBox()
        self.kind_combo.addItems(["文字水印", "图片水印"])
        from PySide6.QtWidgets import QStackedWidget
        self.stack = QStackedWidget()

        text_page = QWidget()
        tv = QVBoxLayout(text_page)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(8)
        self.text_edit = LineEdit()
        self.text_edit.setPlaceholderText("输入水印文字")
        self._trow = self._page_row(tv, "文字", self.text_edit)
        self.font_edit = LineEdit()
        self.font_edit.setText(P.pick_default_font())
        self.font_edit.setPlaceholderText("字体文件路径（默认微软雅黑）")
        font_btn = PushButton("选择字体")
        font_btn.clicked.connect(self._pick_font)
        self._page_row(tv, "字体", hwrap(self.font_edit, font_btn))
        self.size_spin = DoubleSpinBox()
        self.size_spin.setRange(0.5, 40.0)
        self.size_spin.setSingleStep(0.5)
        self.size_spin.setValue(4.0)
        self.size_spin.setSuffix("%")
        self._page_row(tv, "字号（占宽）", self.size_spin)
        self.color_btn = PushButton()
        self.color_btn.setFixedWidth(140)
        self.color_btn.clicked.connect(self._pick_color)
        self._refresh_color_btn()
        self._page_row(tv, "文字颜色", self.color_btn)
        self.stack.addWidget(text_page)

        img_page = QWidget()
        iv = QVBoxLayout(img_page)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(8)
        self.wm_img_edit = LineEdit()
        self.wm_img_edit.setPlaceholderText("PNG 水印图片路径")
        img_btn = PushButton("选择图片")
        img_btn.clicked.connect(self._pick_wm_image)
        self._page_row(iv, "水印图片", hwrap(self.wm_img_edit, img_btn))
        self.scale_spin = DoubleSpinBox()
        self.scale_spin.setRange(1.0, 100.0)
        self.scale_spin.setSingleStep(1.0)
        self.scale_spin.setValue(15.0)
        self.scale_spin.setSuffix("%")
        self._page_row(iv, "宽度（占宽）", self.scale_spin)
        self.stack.addWidget(img_page)

        self.kind_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.row("类型", self.stack)

        self.opacity = Slider(Qt.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(60)
        self.opacity_spin = synced_spinbox(self.opacity, 0, 100)
        self.row("不透明度", hwrap(self.opacity, self.opacity_spin))

        self.pos_combo = ComboBox()
        self.pos_combo.addItems(list(P.POSITION_LABELS.values()))
        self.pos_combo.setCurrentIndex(8)
        self.row("位置", self.pos_combo)

        self.margin_spin = DoubleSpinBox()
        self.margin_spin.setRange(0.0, 30.0)
        self.margin_spin.setSingleStep(0.5)
        self.margin_spin.setValue(2.0)
        self.margin_spin.setSuffix("%")
        self.row("边距", self.margin_spin)

        for sig in (
            self.kind_combo.currentIndexChanged, self.text_edit.textChanged,
            self.font_edit.textChanged, self.size_spin.valueChanged,
            self.wm_img_edit.textChanged, self.scale_spin.valueChanged,
            self.opacity.valueChanged, self.pos_combo.currentIndexChanged,
            self.margin_spin.valueChanged,
        ):
            sig.connect(self._child_changed)
        self.switch.checkedChanged.connect(lambda _: self._child_changed())

    @staticmethod
    def _page_row(layout, text, widget, label_w=88) -> QWidget:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        lab = BodyLabel(text)
        lab.setFixedWidth(label_w)
        h.addWidget(lab)
        h.addWidget(widget, 1)
        layout.addWidget(wrap)
        return wrap

    def _child_changed(self, *_):
        if self._on_change:
            self._on_change()

    def _refresh_color_btn(self):
        self.color_btn.setText(self._color.name().upper())
        lum = 0.299 * self._color.red() + 0.587 * self._color.green() \
            + 0.114 * self._color.blue()
        fg = "#000000" if lum > 150 else "#FFFFFF"
        self.color_btn.setStyleSheet(
            f"PushButton {{ background: {self._color.name()}; color: {fg};"
            f" border: 1px solid #ccc; border-radius: 6px; }}")

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, "选择水印颜色")
        if c.isValid():
            self._color = c
            self._refresh_color_btn()
            self._child_changed()

    def _pick_font(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择字体文件", "C:/Windows/Fonts",
                                           "字体 (*.ttf *.ttc *.otf)")
        if f:
            self.font_edit.setText(f)

    def _pick_wm_image(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择水印图片", "",
                                           "图片 (*.png *.jpg *.webp *.bmp)")
        if f:
            self.wm_img_edit.setText(f)

    def options(self) -> P.WatermarkOptions:
        kinds = ["text", "image"]
        positions = list(P.POSITION_LABELS.keys())
        return P.WatermarkOptions(
            enabled=self.switch.isChecked(),
            kind=kinds[self.kind_combo.currentIndex()],
            text=self.text_edit.text(),
            font_path=self.font_edit.text().strip(),
            font_size_ratio=self.size_spin.value(),
            color=self._color.name(),
            image_path=self.wm_img_edit.text().strip(),
            image_scale=self.scale_spin.value(),
            opacity=self.opacity.value(),
            position=positions[self.pos_combo.currentIndex()],
            margin_ratio=self.margin_spin.value(),
        )


class FormatSection(SectionBase):
    def __init__(self):
        super().__init__("格式与压缩")
        self.fmt_combo = ComboBox()
        self.fmt_combo.addItems(["保持原格式", "JPG", "PNG", "WEBP", "BMP", "TIFF"])
        self.row("输出格式", self.fmt_combo)

        self.add(BodyLabel("压缩方式"))
        self._mode_values = ["quality", "normal", "high", "target"]
        self.comp_group = QButtonGroup(self)
        modes = [
            ("手动质量", "用下方滑块自己控制（默认）"),
            ("普通压缩", "体积更小，日常分享够用"),
            ("高品质压缩", "更清晰，体积稍大"),
            ("目标体积", "每张图压缩到不超过设定大小"),
        ]
        for i, (name, desc) in enumerate(modes):
            rb = RadioButton(name)
            rb.setChecked(i == 0)
            self.comp_group.addButton(rb, i)
            self.add(rb)
            self.add(CaptionLabel("　　" + desc))
        self.comp_group.idClicked.connect(self._mode_clicked)

        self.quality = Slider(Qt.Horizontal)
        self.quality.setRange(10, 100)
        self.quality.setValue(85)
        self.quality_spin = synced_spinbox(self.quality, 10, 100)
        self.quality_row = self.row("质量", hwrap(self.quality, self.quality_spin))

        self.target_edit = DoubleSpinBox()
        self.target_edit.setRange(0.1, 100000.0)
        self.target_edit.setDecimals(1)
        self.target_edit.setValue(500.0)
        self.target_edit.setFixedWidth(110)
        self.target_unit = ComboBox()
        self.target_unit.addItems(["KB", "MB"])
        self.target_unit.setFixedWidth(76)
        trow = QWidget()
        th = QHBoxLayout(trow)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(8)
        th.addWidget(self.target_edit)
        th.addWidget(self.target_unit)
        th.addStretch(1)
        self.target_row = self.row("每张小于", trow)

        self.downscale_check = CheckBox("质量压不下去时自动缩小分辨率")
        self.downscale_check.setChecked(True)
        self.add(self.downscale_check)

        tip = CaptionLabel(
            "压缩方式仅对 JPG / WEBP / PNG 生效（转 JPG 透明自动铺白底，PNG 无损）；"
            "目标体积模式自动搜索最高可用质量，实在压不到会逐步缩小分辨率（可关）")
        tip.setWordWrap(True)
        self.add(tip)
        self._mode_clicked(0)

    def _mode_clicked(self, idx: int):
        self.quality_row.setVisible(idx == 0)
        is_target = idx == 3
        self.target_row.setVisible(is_target)
        self.downscale_check.setVisible(is_target)

    def options(self) -> P.FormatOptions:
        fmts = ["keep", "jpg", "png", "webp", "bmp", "tiff"]
        idx = self.comp_group.checkedId()
        mode = self._mode_values[idx] if idx >= 0 else "quality"
        kb = self.target_edit.value() * (1024.0 if self.target_unit.currentIndex() == 1 else 1.0)
        return P.FormatOptions(
            enabled=self.switch.isChecked(),
            fmt=fmts[self.fmt_combo.currentIndex()],
            quality=self.quality.value(),
            mode=mode,
            target_kb=kb,
            allow_downscale=self.downscale_check.isChecked(),
        )


class RenameSection(SectionBase):
    def __init__(self):
        super().__init__("批量重命名（输出文件名）")
        self.tpl_edit = LineEdit()
        self.tpl_edit.setText("{name}")
        self.row("文件名模板", self.tpl_edit)

        self.digits = SpinBox()
        self.digits.setRange(1, 6)
        self.digits.setValue(3)
        self.digits.setFixedWidth(76)
        self.start = SpinBox()
        self.start.setRange(1, 99999)
        self.start.setValue(1)
        self.start.setFixedWidth(76)
        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(8)
        lab1 = BodyLabel("序号位数")
        lab1.setFixedWidth(88)
        rh.addWidget(lab1)
        rh.addWidget(self.digits)
        lab2 = BodyLabel("起始序号")
        rh.addWidget(lab2)
        rh.addWidget(self.start)
        rh.addStretch(1)
        self.add(row)

        self.add(CaptionLabel(
            "可用占位符：{name} 原文件名  {index} 序号  {date} 日期  "
            "{time} 时间  {width} 宽  {height} 高。扩展名自动处理，"
            "只勾选重命名时不重新编码图片（直接复制）"))
        self.example = CaptionLabel()
        self.add(self.example)
        self.tpl_edit.textChanged.connect(self._update_example)
        self.digits.valueChanged.connect(self._update_example)
        self.start.valueChanged.connect(self._update_example)
        self._update_example()

    def _update_example(self):
        name = P.render_filename(self.tpl_edit.text(), "photo", 0,
                                 self.digits.value(), 800, 600)
        self.example.setText(f"示例：photo.jpg → {name}.jpg")

    def options(self) -> P.RenameOptions:
        return P.RenameOptions(
            enabled=self.switch.isChecked(),
            template=self.tpl_edit.text().strip() or "{name}",
            index_digits=self.digits.value(),
            start_index=self.start.value(),
        )


# ================= 执行栏 =================

class RunBar(CardWidget):
    """固定在底部的执行栏：输出目录 + 开始处理 + 进度。"""

    def __init__(self, get_files, collect_settings):
        super().__init__()
        self._get_files = get_files
        self._collect_settings = collect_settings
        self._worker: ProcessWorker | None = None
        self._out_dir_used = ""

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        lab = BodyLabel("输出到")
        row.addWidget(lab)
        self.out_edit = LineEdit()
        self.out_edit.setPlaceholderText("默认：源文件所在目录\\图片工具箱输出")
        row.addWidget(self.out_edit, 1)
        out_btn = PushButton("浏览")
        out_btn.clicked.connect(self._pick_out_dir)
        row.addWidget(out_btn)
        self.open_btn = PushButton("打开目录")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_out_dir)
        row.addWidget(self.open_btn)
        self.run_btn = PrimaryPushButton("开始处理")
        self.run_btn.setFixedHeight(34)
        self.run_btn.clicked.connect(self._on_run)
        row.addWidget(self.run_btn)
        v.addLayout(row)

        row2 = QHBoxLayout()
        self.progress = ProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        row2.addWidget(self.progress, 1)
        self.status_label = CaptionLabel("就绪")
        self.status_label.setWordWrap(True)
        row2.addWidget(self.status_label, 2)
        v.addLayout(row2)

    # ---- 输出目录 ----

    def _pick_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.out_edit.setText(d)

    def _open_out_dir(self):
        if self._out_dir_used and Path(self._out_dir_used).exists():
            os.startfile(self._out_dir_used)

    # ---- 执行 ----

    def _on_run(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self.status_label.setText("正在停止…")
            self.run_btn.setEnabled(False)
            return

        files = self._get_files()
        if not files:
            InfoBar.warning(title="没有文件", content="请先添加要处理的图片",
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=3000,
                            parent=self.window())
            return
        settings = self._collect_settings()
        if not (settings.resize.enabled or settings.watermark.enabled
                or settings.fmt.enabled or settings.rename.enabled
                or settings.crop.enabled):
            InfoBar.warning(title="未选择功能", content="请至少打开一个功能开关",
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=3000,
                            parent=self.window())
            return

        out_dir = self.out_edit.text().strip() or str(files[0].parent / "图片工具箱输出")
        self._out_dir_used = out_dir
        self.progress.setRange(0, len(files))
        self.progress.setValue(0)
        self.run_btn.setText("停止处理")
        self.open_btn.setEnabled(False)
        self.status_label.setText(f"开始处理 {len(files)} 个文件 → {out_dir}")

        self._worker = ProcessWorker(files, settings, out_dir, self)
        self._worker.progressed.connect(self._on_progress)
        self._worker.file_finished.connect(self._on_file_finished)
        self._worker.run_finished.connect(self._on_run_finished)
        self._worker.start()

    def _on_progress(self, done: int, total: int, name: str):
        self.progress.setValue(done)
        self.status_label.setText(f"处理中 {done}/{total}：{name}")

    def _on_file_finished(self, ok: bool, src: str, msg: str):
        if not ok:
            self.status_label.setText(f"失败：{Path(src).name} — {msg}")

    def _on_run_finished(self, ok: int, fail: int):
        self.run_btn.setText("开始处理")
        self.run_btn.setEnabled(True)
        self.open_btn.setEnabled(bool(self._out_dir_used))
        if fail:
            self.status_label.setText(
                f"完成：成功 {ok} 个，失败 {fail} 个 → {self._out_dir_used}")
            InfoBar.warning(title="处理完成（有失败项）",
                            content=f"成功 {ok}，失败 {fail}，详情见状态栏",
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=5000,
                            parent=self.window())
        else:
            self.status_label.setText(
                f"完成 ✅ 成功 {ok} 个 → {self._out_dir_used}")
            InfoBar.success(title="处理完成", content=f"成功处理 {ok} 个文件",
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=4000,
                            parent=self.window())

    def shutdown(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
