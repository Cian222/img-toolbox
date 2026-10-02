"""布局配置、选择对话框与窗口创建。"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel, CheckBox, PushButton, SubtitleLabel, BodyLabel,
)

LAYOUTS = {
    "collapse": ("智能折叠", "保持单列卡片，未启用的功能折叠成一行，启用即展开；执行栏固定"),
    "nav": ("左侧导航", "五个功能和视频转 GIF 都在左侧导航，更像正式软件"),
}
CONFIG_FILE = Path.home() / ".imgtoolbox" / "layout.txt"


def load_saved_layout() -> str | None:
    try:
        key = CONFIG_FILE.read_text("utf-8").strip()
        return key if key in LAYOUTS else None
    except OSError:
        return None


def save_layout(key: str) -> None:
    if key not in LAYOUTS:
        return
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(key, encoding="utf-8")


def relaunch():
    """以当前保存的布局重启程序（切换布局用）。

    PyInstaller onefile 会给自身进程注入 _MEIPASS2 / _PYI_* 环境变量；
    直接拉起新实例会继承它们，子进程会误用父进程的解包目录，导致
    "Failed to start embedded python interpreter" 和临时目录删除失败。
    因此必须为子进程清掉这些变量。
    """
    if getattr(sys, "frozen", False):
        program, args = sys.executable, list(sys.argv[1:])
    else:
        program, args = sys.executable, list(sys.argv)

    from PySide6.QtCore import QProcess, QProcessEnvironment
    proc = QProcess()
    env = QProcessEnvironment.systemEnvironment()
    for var in ("_MEIPASS2", "_MEIPASS", "_PYI_APPLICATION_HOME_DIR",
                "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_HANDLE"):
        env.remove(var)
    proc.setProcessEnvironment(env)
    proc.setProgram(program)
    proc.setArguments(args)
    proc.startDetached()


def create_window(key: str):
    if key == "nav":
        from app.layout_nav import NavWindow
        window = NavWindow()
    else:
        from app.layout_collapse import CollapseWindow
        window = CollapseWindow()
    window.layout_key = key
    return window


class LayoutChooserDialog(QDialog):
    """选择布局。chosen 保存所选 key；current 用于标记正在使用的布局。"""

    def __init__(self, parent=None, current: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("选择界面布局")
        self.resize(460, 460)
        self.chosen: str | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 16)
        v.setSpacing(8)
        v.addWidget(SubtitleLabel("选择界面布局"))
        tip = "三种布局共用同一套功能，随时可换" + \
            (f"（当前使用：{LAYOUTS[current][0]}）" if current in LAYOUTS else
             "（删除 ~/.imgtoolbox/layout.txt 或用 --layout 参数也可切换）")
        v.addWidget(CaptionLabel(tip))
        v.addSpacing(6)

        self._buttons = []
        for key, (name, desc) in LAYOUTS.items():
            btn = PushButton(name + ("（当前使用中）" if key == current else ""))
            btn.setFixedHeight(40)
            btn.clicked.connect(lambda _=False, k=key: self._choose(k))
            v.addWidget(btn)
            v.addWidget(CaptionLabel("　　" + desc))
            v.addSpacing(4)
            self._buttons.append(btn)

        v.addStretch(1)
        self.remember_cb = CheckBox("记住我的选择，下次直接打开")
        self.remember_cb.setChecked(True)
        v.addWidget(self.remember_cb)

    def _choose(self, key: str):
        self.chosen = key
        self.accept()
