"""手动裁剪对话框：在参考图上拖拽选择裁剪区域，可锁定比例。

交互：图上拖拽=画新框；框内拖拽=移动；角点拖拽=缩放（对角固定）。
裁剪以相对坐标保存，批量处理时对所有图片按同一相对区域应用。
"""
from __future__ import annotations

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, PushButton

CANVAS_MAX_W, CANVAS_MAX_H = 640, 460
HANDLE_R = 7          # 角点命中半径
MIN_SIDE = 6          # 最小框边长（画布像素）
OPPOSITE = {"tl": "br", "br": "tl", "tr": "bl", "bl": "tr"}


class CropCanvas(QWidget):
    rectChanged = Signal()

    def __init__(self, source: Image.Image, ratio: float | None = None,
                 init_rel: tuple | None = None, parent=None):
        super().__init__(parent)
        self._img_w, self._img_h = source.size
        scale = min(CANVAS_MAX_W / self._img_w, CANVAS_MAX_H / self._img_h, 1.0)
        self.setFixedSize(max(1, round(self._img_w * scale)),
                          max(1, round(self._img_h * scale)))
        # 关键：把图缩放到画布尺寸（否则大图只显示左上角一块）
        self._pixmap = QPixmap.fromImage(ImageQt(source)).scaled(
            self.width(), self.height(),
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self._ratio = ratio
        self._drag = None
        W, H = self.width(), self.height()
        if init_rel:
            self._rect = QRect(round(init_rel[0] * W), round(init_rel[1] * H),
                               max(1, round(init_rel[2] * W)),
                               max(1, round(init_rel[3] * H))).normalized()
            self._rect = self._rect.intersected(QRect(0, 0, W, H))
        else:
            self._rect = self._fit_max(ratio) if ratio else QRect(0, 0, W, H)

    # ---------- 几何 ----------

    def _fit_max(self, ratio: float) -> QRect:
        """画布内符合比例的最大居中矩形。"""
        W, H = self.width(), self.height()
        w, h = W, W / ratio
        if h > H:
            h, w = H, H * ratio
        w, h = round(w), round(h)
        return QRect((W - w) // 2, (H - h) // 2, w, h)

    def _corners(self, r: QRect) -> dict:
        return {"tl": r.topLeft(), "tr": r.topRight(),
                "bl": r.bottomLeft(), "br": r.bottomRight()}

    def _norm_rect(self) -> QRect:
        return self._rect.normalized()

    def _draw_rect(self, anchor: QPoint, free: QPoint) -> QRect:
        """从固定角到自由点画框；有比例时按比例收缩并限制在画布内。"""
        w = free.x() - anchor.x()
        h = free.y() - anchor.y()
        if self._ratio:
            max_w = (self.width() - anchor.x()) if w >= 0 else anchor.x()
            max_h = (self.height() - anchor.y()) if h >= 0 else anchor.y()
            cw = min(abs(w), max_w)
            ch = cw / self._ratio
            if ch > max_h:
                ch = max_h
                cw = ch * self._ratio
            w = cw if w >= 0 else -cw
            h = ch if h >= 0 else -ch
        r = QRect(anchor, anchor + QPoint(round(w), round(h))).normalized()
        if r.width() < MIN_SIDE or r.height() < MIN_SIDE:
            return self._rect  # 太小不更新
        return r.intersected(QRect(0, 0, self.width(), self.height()))

    def set_ratio(self, ratio: float | None):
        self._ratio = ratio
        if not ratio:
            return
        r = self._norm_rect()
        if r.width() <= 0:
            return
        cx, cy = r.center().x(), r.center().y()
        w = r.width()
        h = round(w / ratio)
        if h > self.height():
            h = self.height()
            w = round(h * ratio)
        tl = QPoint(max(0, min(self.width() - w, cx - w // 2)),
                    max(0, min(self.height() - h, cy - h // 2)))
        self._rect = QRect(tl, QSize(w, h))
        self.update()
        self.rectChanged.emit()

    def reset(self):
        self._rect = self._fit_max(self._ratio) if self._ratio \
            else QRect(0, 0, self.width(), self.height())
        self.update()
        self.rectChanged.emit()

    def select_all(self):
        self._ratio = None  # 全选意味着解除比例
        self._rect = QRect(0, 0, self.width(), self.height())
        self.update()
        self.rectChanged.emit()

    def rect_rel(self) -> tuple:
        r = self._norm_rect()
        W, H = self.width(), self.height()
        return (r.left() / W, r.top() / H, r.width() / W, r.height() / H)

    def crop_px_on_source(self) -> tuple:
        r = self._norm_rect()
        sx = self._img_w / self.width()
        sy = self._img_h / self.height()
        return (max(1, round(r.width() * sx)), max(1, round(r.height() * sy)))

    # ---------- 鼠标 ----------

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position().toPoint()
        r = self._norm_rect()
        hit = None
        for name, pt in self._corners(r).items():
            if abs(pos.x() - pt.x()) <= HANDLE_R and abs(pos.y() - pt.y()) <= HANDLE_R:
                hit = name
                break
        if hit:
            self._drag = "resize"
            self._anchor = self._corners(r)[OPPOSITE[hit]]
        elif r.contains(pos):
            self._drag = "move"
            self._grab_offset = pos - r.topLeft()
            self._press_rect = QRect(r)
        else:
            self._drag = "new"
            self._anchor = pos
            self._rect = QRect(pos, pos)
        self.update()

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        raw = e.position().toPoint()
        pos = QPoint(max(0, min(self.width() - 1, raw.x())),
                     max(0, min(self.height() - 1, raw.y())))
        if self._drag in ("new", "resize"):
            self._rect = self._draw_rect(self._anchor, pos)
        else:  # move
            r = self._press_rect
            tl = pos - self._grab_offset
            tl.setX(max(0, min(self.width() - r.width(), tl.x())))
            tl.setY(max(0, min(self.height() - r.height(), tl.y())))
            self._rect = QRect(tl, r.size())
        self.update()
        self.rectChanged.emit()

    def mouseReleaseEvent(self, e):
        self._drag = None

    # ---------- 绘制 ----------

    def paintEvent(self, e):
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pixmap)
        r = self._norm_rect()
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        p.save()
        p.setClipRect(r)
        p.drawPixmap(0, 0, self._pixmap)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 235), 1))
        p.drawRect(r)
        p.setPen(QPen(QColor(255, 255, 255, 80), 1))
        for i in (1, 2):
            x = r.left() + r.width() * i // 3
            y = r.top() + r.height() * i // 3
            p.drawLine(x, r.top(), x, r.bottom())
            p.drawLine(r.left(), y, r.right(), y)
        p.setPen(QPen(QColor(0, 0, 0, 180), 1))
        p.setBrush(QColor(255, 255, 255))
        for pt in self._corners(r).values():
            p.drawRect(pt.x() - 4, pt.y() - 4, 8, 8)


class CropDialog(QDialog):
    """返回 rect_rel() = (x, y, w, h)，均为 0~1 相对坐标。"""

    def __init__(self, source: Image.Image, ratio: float | None = None,
                 pixel_target: tuple | None = None, init_rel: tuple | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("手动裁剪")
        self.setStyleSheet("QDialog { background: #f5f6fa; }")
        self.resize(700, 620)
        self._pixel_target = pixel_target

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 14)
        v.setSpacing(10)
        v.addWidget(CaptionLabel(
            "拖拽画框，拖框移动，拖白色角点缩放；所有图片按此相对区域统一裁剪"))
        self.canvas = CropCanvas(source, ratio=ratio, init_rel=init_rel)
        self.canvas.rectChanged.connect(self._update_info)
        v.addWidget(self.canvas)

        self.info = CaptionLabel()
        v.addWidget(self.info)

        btns = QHBoxLayout()
        reset_btn = PushButton("重置")
        reset_btn.clicked.connect(self.canvas.reset)
        if ratio is None:
            all_btn = PushButton("全选")
            all_btn.clicked.connect(self.canvas.select_all)
            btns.addWidget(all_btn)
        btns.addWidget(reset_btn)
        btns.addStretch(1)
        ok_btn = PushButton("确定")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        v.addLayout(btns)

        self._update_info()

    def _update_info(self):
        w, h = self.canvas.crop_px_on_source()
        if self._pixel_target:
            tw, th = self._pixel_target
            self.info.setText(
                f"参考图裁剪区域 {w}×{h} px → 所有图片裁剪后统一缩放至 {tw}×{th} px")
        else:
            self.info.setText(f"参考图裁剪区域 {w}×{h} px（按相对区域应用到所有图片）")

    def rect_rel(self) -> tuple:
        return self.canvas.rect_rel()
