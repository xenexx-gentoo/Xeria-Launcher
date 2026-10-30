import contextlib
import math

from PyQt6.QtCore import QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QWidget

from core import hardware, theme

HW = hardware.get()


class ParticleBackground(QWidget):
    MOUSE_LIGHT_RADIUS = 460
    RING_PHASE_SPEED = 0.05

    def __init__(self, parent):
        super().__init__(parent)
        self._mouse = QPointF(-1000, -1000)
        self._phase = 0.0
        self._dt_ms = 16
        self._timer = QTimer(self)
        self._timer.setInterval(self._dt_ms)
        self._timer.timeout.connect(self._tick)
        if HW.animations:
            self._timer.start()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._mask_widget = None
        self._glow_pixmap = None
        self._glow_accent = None
        self._build_glow_cache()

    def set_mask_widget(self, widget):
        self._mask_widget = widget

    def _build_glow_cache(self):
        r = self.MOUSE_LIGHT_RADIUS
        size = int(r * 2)
        if size <= 0:
            return
        self._glow_accent = (theme.ACCENT or "").lower()
        self._glow_pixmap = QPixmap(size, size)
        self._glow_pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(self._glow_pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        glow = QRadialGradient(r, r, r)
        a = QColor(theme.ACCENT)
        a.setAlpha(90)
        m = QColor(theme.ACCENT)
        m.setAlpha(30)
        b = QColor(theme.ACCENT)
        b.setAlpha(0)
        glow.setColorAt(0.0, a)
        glow.setColorAt(0.35, m)
        glow.setColorAt(1.0, b)
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, size, size)
        p.end()

    def _ensure_glow(self):
        if self._glow_accent != (theme.ACCENT or "").lower():
            self._build_glow_cache()

    def refresh_theme(self):
        self._build_glow_cache()
        self.update()

    def set_mouse(self, pos):
        self._mouse = QPointF(pos)

    def _tick(self):
        dt = self._dt_ms / 1000.0
        self._phase += dt
        self._sync_mouse_from_cursor()
        self.update()

    def _sync_mouse_from_cursor(self):
        if not self.isVisible() or not self.window().isActiveWindow():
            return
        with contextlib.suppress(Exception):
            gpos = QCursor.pos()
            local = self.mapFromGlobal(gpos)
            if 0 <= local.x() < self.width() and 0 <= local.y() < self.height():
                self._mouse = QPointF(local)
            else:
                self._mouse = QPointF(-1000, -1000)

    def _draw_ring(
        self,
        p,
        center,
        radius,
        squash,
        base_alpha,
        mouse,
        glow_radius,
        dim_col,
        lit_col,
    ):
        if radius <= 1.0:
            return
        cx, cy = center.x(), center.y()
        steps = max(48, int(radius * 0.8))
        arc = math.tau / steps
        prev_x = prev_y = None
        for i in range(steps + 1):
            a = i * arc
            x = cx + math.cos(a) * radius
            y = cy + math.sin(a) * radius * squash
            if prev_x is not None:
                strength = 0.0
                if mouse.x() > -500:
                    px = (prev_x + x) * 0.5
                    py = (prev_y + y) * 0.5
                    dx = px - mouse.x()
                    dy = py - mouse.y()
                    d = math.sqrt(dx * dx + dy * dy)
                    if d < glow_radius:
                        t = 1.0 - (d / glow_radius)
                        strength = t * t
                alpha = base_alpha * 0.35 + strength * 0.45
                if alpha > 0.005:
                    col = lit_col if strength > 0 else dim_col
                    col.setAlphaF(min(1.0, alpha))
                    width = 1.0 + strength * 1.0
                    p.setPen(QPen(col, width))
                    p.drawLine(QPointF(prev_x, prev_y), QPointF(x, y))
            prev_x, prev_y = x, y

    def paintEvent(self, ev):
        self._ensure_glow()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        base = QLinearGradient(0, 0, w, h)
        base.setColorAt(0.0, QColor(theme.BG).darker(120))
        base.setColorAt(0.55, QColor(theme.BG))
        base.setColorAt(1.0, QColor(theme.BG).lighter(112))
        p.fillRect(self.rect(), base)
        if self._mouse.x() > -500 and self._glow_pixmap:
            r = self.MOUSE_LIGHT_RADIUS
            p.drawPixmap(
                int(self._mouse.x() - r), int(self._mouse.y() - r), self._glow_pixmap
            )
        cx, cy = w * 0.5, h * 0.5
        center = QPointF(cx, cy)
        speed = self.RING_PHASE_SPEED
        num_rings = 9
        max_radius = math.hypot(w, h) * 0.55 * 1.25
        squash = 1
        dim_col = QColor(theme.ACCENT).darker(200)
        lit_col = QColor(theme.ACCENT).lighter(110)
        for i in range(num_rings):
            step = i / (num_rings - 1)
            offset = (self._phase * speed) % 1.0
            pseudo_step = (step + offset) % 1.0
            radius = max_radius * (0.05 + 0.95 * (pseudo_step**2.0))
            if radius <= 1.0:
                continue
            fade_in = min(1.0, pseudo_step / 0.1)
            fade_out = min(1.0, (1.0 - pseudo_step) / 0.15)
            fade = fade_in * fade_out
            alpha = fade * 0.5
            alpha *= 0.4 + pseudo_step * 0.6
            self._draw_ring(
                p,
                center,
                radius,
                squash,
                alpha,
                self._mouse,
                self.MOUSE_LIGHT_RADIUS * 0.85,
                dim_col,
                lit_col,
            )
        p.end()


class LineFieldBackground(QWidget):
    frame_ready = pyqtSignal()
    ANGLE_DEG = 80
    MOUSE_LIGHT_RADIUS = 460
    PHASE_SPEED_BASE = 40.0
    LINE_WIDTH = 2.0
    MIN_ALPHA = 20
    MAX_ALPHA = 110
    STRIPE_SPACING = 48

    def __init__(self, parent):
        super().__init__(parent)
        self._mouse = QPointF(-9999, -9999)
        self._phase = 0.0
        self._dt_ms = 16
        self._phase_speed = self.PHASE_SPEED_BASE
        self._spacing = self.STRIPE_SPACING
        self._width_scale = 1.0
        self._glow_radius = self.MOUSE_LIGHT_RADIUS
        self._min_alpha = self.MIN_ALPHA
        self._max_alpha = self.MAX_ALPHA
        self._timer = QTimer(self)
        self._timer.setInterval(self._dt_ms)
        self._timer.timeout.connect(self._tick)
        if HW.animations:
            self._timer.start()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._glow_pixmap = None
        self._glow_accent = None
        self._build_glow_cache()

    def _build_glow_cache(self):
        r = self.MOUSE_LIGHT_RADIUS
        size = int(r * 2)
        if size <= 0:
            return
        self._glow_accent = (theme.ACCENT or "").lower()
        self._glow_pixmap = QPixmap(size, size)
        self._glow_pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(self._glow_pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        glow = QRadialGradient(r, r, r)
        a = QColor(theme.ACCENT)
        a.setAlpha(90)
        m = QColor(theme.ACCENT)
        m.setAlpha(30)
        b = QColor(theme.ACCENT)
        b.setAlpha(0)
        glow.setColorAt(0.0, a)
        glow.setColorAt(0.35, m)
        glow.setColorAt(1.0, b)
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, size, size)
        p.end()

    def _ensure_glow(self):
        if self._glow_accent != (theme.ACCENT or "").lower():
            self._build_glow_cache()

    def refresh_theme(self):
        self._build_glow_cache()
        self.update()

    def set_mouse(self, pos):
        self._mouse = QPointF(pos)

    def _tick(self):
        self._phase += (self._dt_ms / 1000.0) * self._phase_speed
        self._sync_mouse_from_cursor()
        self.update()
        with contextlib.suppress(Exception):
            self.frame_ready.emit()

    def _sync_mouse_from_cursor(self):
        if not self.isVisible() or not self.window().isActiveWindow():
            return
        with contextlib.suppress(Exception):
            gpos = QCursor.pos()
            local = self.mapFromGlobal(gpos)
            if 0 <= local.x() < self.width() and 0 <= local.y() < self.height():
                self._mouse = QPointF(local)
            else:
                self._mouse = QPointF(-9999, -9999)

    def paintEvent(self, ev):
        self._ensure_glow()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            p.end()
            return
        base = QLinearGradient(0, 0, w, h)
        base.setColorAt(0.0, QColor(theme.BG).darker(120))
        base.setColorAt(0.55, QColor(theme.BG))
        base.setColorAt(1.0, QColor(theme.BG).lighter(112))
        p.fillRect(self.rect(), base)
        if self._mouse.x() > -500 and self._glow_pixmap:
            r = self.MOUSE_LIGHT_RADIUS
            p.drawPixmap(
                int(self._mouse.x() - r), int(self._mouse.y() - r), self._glow_pixmap
            )
        center_y = h * 0.5
        gap = h * 0.28
        top_limit = center_y - gap
        bot_limit = center_y + gap
        angle_rad = math.radians(self.ANGLE_DEG)
        dx = math.cos(angle_rad)
        dy = math.sin(angle_rad)
        nx = -dy
        ny = dx
        max_len = math.hypot(w, h) * 1.5
        cx = w * 0.5
        num_lines = int(max_len / self._spacing) + 2
        offset = (self._phase) % self._spacing
        base_col = QColor(theme.ACCENT)
        for i in range(-num_lines, num_lines):
            dist = i * self._spacing + offset
            px = cx + nx * dist
            py = center_y + ny * dist
            x0 = px - dx * max_len
            y0 = py - dy * max_len
            x1 = px + dx * max_len
            y1 = py + dy * max_len
            alpha = self._max_alpha
            if top_limit < py < bot_limit:
                fade_factor = abs(py - center_y) / gap
                alpha = int(alpha * (0.15 + 0.85 * fade_factor))
            strength = 0.0
            if self._mouse.x() > -500:
                ddx = px - self._mouse.x()
                ddy = py - self._mouse.y()
                d = math.sqrt(ddx * ddx + ddy * ddy)
                if d < self._glow_radius:
                    t = 1.0 - (d / self._glow_radius)
                    strength = t * t
                    alpha += strength * 120
            if alpha < 3:
                continue
            col = QColor(base_col)
            col.setAlpha(int(min(255, alpha)))
            pen = QPen(col)
            pen.setWidthF(self.LINE_WIDTH * self._width_scale + strength * 2.0)
            p.setPen(pen)
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        p.end()


class ParticleOverlayMixin:
    _bg = None

    def _install_particles(self):
        try:
            central = self.centralWidget()
        except Exception:  # noqa: BLE001
            return
        if central is None:
            return
        bg = ParticleBackground(central)
        bg.lower()
        bg.setGeometry(central.rect())
        self._bg = bg
        app = QApplication.instance()
        app.installEventFilter(self)

    def _resize_bg(self):
        if self._bg is None:
            return
        with contextlib.suppress(Exception):
            central = self.centralWidget()
            if central is not None:
                self._bg.setGeometry(central.rect())

    def eventFilter(self, obj, event):
        return super().eventFilter(obj, event)
