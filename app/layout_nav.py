"""方案三：Fluent 左侧导航多页 —— 五个功能也放进左侧导航。

内容区始终是 ProcessorView（文件 + 预览 + 功能设置 + 执行栏），
左侧导航负责切换功能页、视频转 GIF 页和关于页。
"""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, FluentIcon, FluentWindow, NavigationItemPosition, SubtitleLabel,
)

from app.processor_view import ProcessorView
from app.video_dialog import VideoGifPanel

FEATURE_NAV = [
    ("resize", "调整大小", FluentIcon.ZOOM_IN),
    ("crop", "裁剪", FluentIcon.FIT_PAGE),
    ("wm", "水印", FluentIcon.BRUSH),
    ("fmt", "格式压缩", FluentIcon.SAVE),
    ("ren", "重命名", FluentIcon.EDIT),
]


class AboutPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("aboutPage")
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(10)
        v.addWidget(SubtitleLabel("图片工具箱"))
        for line in (
            "批量图片处理：压缩、水印、批量重命名、调整大小、手动裁剪、格式互转；"
            "附带视频转 GIF（选片段、定时长、调帧率）。",
            "所有处理都在后台进行，输出到独立目录，绝不覆盖原图。",
            "自定义的裁剪比例 / 像素预设保存在 ~/.imgtoolbox/presets.json。",
            "技术栈：Python + PySide6 + qfluentwidgets + Pillow + OpenCV。",
        ):
            lab = BodyLabel(line)
            lab.setWordWrap(True)
            v.addWidget(lab)
        v.addStretch(1)


class NavWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("图片工具箱 · 导航布局")
        self.resize(1240, 840)
        self.setMinimumSize(1180, 720)

        # 主内容：图片处理视图（功能由左侧导航驱动）
        self.view = ProcessorView()
        self.view.setObjectName("processorView")
        self.view.files.video_btn.hide()   # 功能与按钮都进了左侧导航
        self.view.files.layout_btn.hide()
        self.stackedWidget.addWidget(self.view)

        # 五个功能 → 左侧导航
        for key, label, icon in FEATURE_NAV:
            self.navigationInterface.addItem(
                routeKey=f"f_{key}", icon=icon, text=label,
                onClick=lambda checked=False, k=key: self._show_feature(k),
                selectable=True, position=NavigationItemPosition.TOP)

        # 视频转 GIF / 关于 / 切换布局
        self.video_page = VideoGifPanel()
        self.addSubInterface(self.video_page, FluentIcon.VIDEO, "视频转 GIF")
        self.about = AboutPage()
        self.addSubInterface(self.about, FluentIcon.INFO, "关于",
                             NavigationItemPosition.BOTTOM)
        self.navigationInterface.addItem(
            routeKey="switch_layout", icon=FluentIcon.LAYOUT, text="切换布局",
            onClick=self._switch_layout, selectable=False,
            position=NavigationItemPosition.BOTTOM)

        self.switchTo(self.view)
        self.navigationInterface.setCurrentItem("f_resize")

    def _show_feature(self, key: str):
        self.view.switch_feature(key)
        self.stackedWidget.setCurrentWidget(self.view)
        self.navigationInterface.setCurrentItem(f"f_{key}")

    def _switch_layout(self):
        from app import main_window as MW
        dlg = MW.LayoutChooserDialog(self, current=self.layout_key)
        if dlg.exec() and dlg.chosen and dlg.chosen != self.layout_key:
            MW.save_layout(dlg.chosen)
            MW.relaunch()
            self.close()

    def closeEvent(self, event):
        self.view.shutdown()
        self.video_page.shutdown()
        super().closeEvent(event)
