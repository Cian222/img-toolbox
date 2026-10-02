"""图片工具箱入口。

运行：python main.py [--layout collapse|nav] [--selftest]
--selftest：启动后自动截图 selftest.png 并退出（用于验证打包后的 exe）。
"""
import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme

from app import main_window as MW


def asset_path(name: str) -> str:
    """开发态取项目目录，打包后取解包目录（_MEIPASS）。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(base / "assets" / name)


def main():
    parser = argparse.ArgumentParser(description="图片工具箱")
    parser.add_argument("--layout", choices=list(MW.LAYOUTS),
                        help="界面布局（不指定则用上次的选择或弹出选择框）")
    parser.add_argument("--selftest", action="store_true",
                        help="启动后自动截图 selftest.png 并退出（验证打包用）")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("图片工具箱")
    app.setOrganizationName("imgtoolbox")
    app.setWindowIcon(QIcon(asset_path("icon.ico")))
    setTheme(Theme.LIGHT)  # 界面按浅色设计，避免系统深色主题下窗口底色发黑
    try:
        # 让任务栏把 exe 图标和应用正确分组
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "imgtoolbox.app.1")
    except Exception:
        pass

    if args.selftest:
        key = args.layout or MW.load_saved_layout() or "collapse"
        window = MW.create_window(key)
        window.show()

        def _snap():
            window.grab().save("selftest.png")
            print("SELFTEST OK", flush=True)
            app.quit()

        QTimer.singleShot(1500, _snap)
        app.exec()
        sys.exit(0)

    key = args.layout or MW.load_saved_layout()
    if not key:
        chooser = MW.LayoutChooserDialog()
        chooser.exec()
        key = chooser.chosen or "collapse"
        if chooser.remember_cb.isChecked():
            MW.save_layout(key)

    window = MW.create_window(key)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
