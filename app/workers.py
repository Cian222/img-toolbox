"""后台处理线程：批量执行 process_file / video_to_gif，不阻塞界面。"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from app.processors import ProcessSettings, process_file
from app.video_gif import video_to_gif


class ProcessWorker(QThread):
    progressed = Signal(int, int, str)      # 已完成数, 总数, 当前文件名
    file_finished = Signal(bool, str, str)  # 是否成功, 源路径, 输出路径或错误信息
    run_finished = Signal(int, int)         # 成功数, 失败数

    def __init__(self, files, settings: ProcessSettings, out_dir, parent=None):
        super().__init__(parent)
        self._files = list(files)
        self._settings = settings
        self._out_dir = out_dir
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        ok = fail = 0
        total = len(self._files)
        for i, src in enumerate(self._files):
            if self._cancel:
                break
            name = src.name if hasattr(src, "name") else str(src)
            try:
                out_path, note = process_file(src, self._settings, self._out_dir, i)
                ok += 1
                self.file_finished.emit(True, str(src), f"{out_path.name}（{note}）")
            except Exception as e:  # 单个文件失败不影响其余
                fail += 1
                self.file_finished.emit(False, str(src), str(e))
            self.progressed.emit(i + 1, total, name)
        self.run_finished.emit(ok, fail)


class VideoGifWorker(QThread):
    progressed = Signal(int, int)          # 已抽帧数, 总帧数
    run_finished = Signal(bool, str, str)  # 是否成功, 输出路径或错误信息, 说明

    def __init__(self, video, start_sec: float, duration_sec: float, fps: int,
                 width: int, out_path, parent=None):
        super().__init__(parent)
        self._args = (video, start_sec, duration_sec, fps, width, out_path)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            out, note = video_to_gif(
                *self._args,
                progress=lambda d, t: self.progressed.emit(d, t),
                is_cancelled=lambda: self._cancel,
            )
            self.run_finished.emit(True, str(out), note)
        except Exception as e:
            self.run_finished.emit(False, str(e), "")
