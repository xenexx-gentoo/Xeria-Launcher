import os

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QColor,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PyQt6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)
from PyQt6.QtWidgets import (
    QDialog,
    QGraphicsBlurEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QLineEdit,
    QPlainTextEdit,
    QStyle,
)

from core import paths, theme


def _is_wayland():
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(
        os.environ.get("WAYLAND_DISPLAY")
    )


ICON_SIZE = QSize(16, 16)
ICON_SIZE_LG = QSize(20, 20)

LOADER_ICON = {
    "vanilla": ("applications-games", QStyle.StandardPixmap.SP_DesktopIcon),
    "fabric": ("applications-science", QStyle.StandardPixmap.SP_FileDialogContentsView),
    "forge": ("applications-engineering", QStyle.StandardPixmap.SP_ComputerIcon),
    "neoforge": ("applications-engineering", QStyle.StandardPixmap.SP_ComputerIcon),
    "quilt": ("applications-science", QStyle.StandardPixmap.SP_FileDialogContentsView),
}


class TranslucentDialog(QDialog):
    RADIUS = 14
    BLUR_RADIUS = 12
    TINT_ALPHA = 70
    BLUR_HALFSCALE = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setModal(True)

        self._bg_field = None
        self._blur_cache = None
        self._blur_dirty = True
        self._blur_timer = QTimer(self)
        self._blur_timer.setSingleShot(True)
        self._blur_timer.setInterval(100)
        self._blur_timer.timeout.connect(self._on_blur_timer)

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_bg_field()
        if self._bg_field is not None:
            try:
                self._bg_field.refresh_theme()
            except Exception:  # noqa: BLE001, S110
                pass
        self._mark_dirty()

        QTimer.singleShot(50, self._force_focus)
        QTimer.singleShot(150, self._force_focus)

    def _force_focus(self):
        if not self.isVisible():
            return
        self.raise_()
        self.activateWindow()
        if not _is_wayland():
            try:
                self.grabKeyboard()
            except Exception:  # noqa: BLE001, S110
                pass
        for w in self.findChildren((QLineEdit, QPlainTextEdit)):
            if w.isVisible() and w.focusPolicy() != Qt.FocusPolicy.NoFocus:
                w.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
                break

    def hideEvent(self, event):
        if not _is_wayland():
            try:
                self.releaseKeyboard()
            except Exception:  # noqa: BLE001, S110
                pass
        super().hideEvent(event)

    def closeEvent(self, event):
        if not _is_wayland():
            try:
                self.releaseKeyboard()
            except Exception:  # noqa: BLE001, S110
                pass
        super().closeEvent(event)

    def _ensure_bg_field(self):
        try:
            from ui.particles import LineFieldBackground
        except Exception:  # noqa: BLE001
            return
        if self._bg_field is None:
            self._bg_field = LineFieldBackground(self)
            self._bg_field.setGeometry(0, 0, self.width(), self.height())
            self._bg_field.lower()
            self._bg_field.show()
            self._bg_field.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            try:
                self._bg_field.frame_ready.connect(
                    self._mark_dirty, Qt.ConnectionType.QueuedConnection
                )
            except Exception:  # noqa: BLE001, S110
                pass

    def _mark_dirty(self, *_):
        self._blur_dirty = True
        if not self._blur_timer.isActive():
            self._blur_timer.start()

    def _on_blur_timer(self):
        if not self._blur_dirty:
            return
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._bg_field is not None:
            self._bg_field.setGeometry(0, 0, self.width(), self.height())
        self._blur_dirty = True
        self.update()

    def _rebuild_blur(self):
        if self._bg_field is None:
            return
        w = self._bg_field.width()
        h = self._bg_field.height()
        if w <= 0 or h <= 0:
            return
        src = self._bg_field.grab()
        if src.isNull():
            return

        if self.BLUR_HALFSCALE and w > 200 and h > 200:
            small = src.scaled(
                max(1, w // 2),
                max(1, h // 2),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            out_small = self._apply_blur(small)
            if out_small is None or out_small.isNull():
                return
            final = out_small.scaled(
                w,
                h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._blur_cache = final
        else:
            out = self._apply_blur(src)
            if out is None or out.isNull():
                return
            self._blur_cache = out

        self._blur_dirty = False

    def _apply_blur(self, src):
        try:
            out_img = QImage(src.size(), QImage.Format.Format_ARGB32_Premultiplied)
            out_img.fill(Qt.GlobalColor.transparent)
            scene = QGraphicsScene()
            item = QGraphicsPixmapItem()
            item.setPixmap(src)
            effect = QGraphicsBlurEffect()
            effect.setBlurRadius(self.BLUR_RADIUS)
            effect.setBlurHints(QGraphicsBlurEffect.BlurHint.PerformanceHint)
            item.setGraphicsEffect(effect)
            scene.addItem(item)
            pp = QPainter(out_img)
            scene.render(
                pp,
                QRectF(0, 0, src.width(), src.height()),
                QRectF(0, 0, src.width(), src.height()),
            )
            pp.end()
            scene.clear()
            return QPixmap.fromImage(out_img)
        except Exception:  # noqa: BLE001
            return None

    def paintEvent(self, event):
        no_blur = self.BLUR_RADIUS <= 0 or self._bg_field is None

        if no_blur:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
            p.fillPath(path, QColor(theme.BG))
            p.end()
            super().paintEvent(event)
            return

        if self._blur_cache is None or self._blur_dirty:
            self._rebuild_blur()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._blur_cache is not None and not self._blur_cache.isNull():
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
            p.save()
            p.setClipPath(path)
            p.drawPixmap(0, 0, self._blur_cache)
            p.restore()

        p.end()
        super().paintEvent(event)

    def mouseMoveEvent(self, event):
        if self._bg_field is not None:
            self._bg_field.set_mouse(event.position())
        super().mouseMoveEvent(event)


def dialog_shell_style():
    return (
        "QDialog{background:transparent;outline:none;}"
        "QDialog:focus{outline:none;}" + s_combo_popup()
    )


def _accent_text():
    return theme.accent_text()


def _alpha(hex_color, alpha):
    s = (hex_color or "#000000").lstrip("#")
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except Exception:  # noqa: BLE001
        r = g = b = 0
    return f"rgba({r},{g},{b},{max(0, min(255, int(alpha)))})"


def glass_panel(alpha=120):
    return _alpha(theme.BG2, alpha)


def glass_soft(alpha=90):
    return _alpha(theme.BG3, alpha)


def glass_accent(alpha=130):
    return _alpha(theme.ACCENT, alpha)


def glass_accent2(alpha=170):
    return _alpha(theme.ACCENT2, alpha)


def glass_border(alpha=45):
    return _alpha(theme.FG, alpha)


def s_icon_btn(bg, fg, hover, size=32):
    return (
        f"QPushButton{{background:{bg};color:{fg};"
        f"border:0px solid transparent;border-radius:8px;"
        f"min-width:{size}px;min-height:{size}px;"
        f"max-width:{size}px;max-height:{size}px;padding:0;"
        f"outline:none;}}"
        f"QPushButton:hover{{background:{hover};border:0px solid transparent;}}"
        f"QPushButton:focus{{border:0px solid transparent;outline:none;}}"
        f"QPushButton:disabled{{background:{bg};color:{theme.GRAY};border:0px solid transparent;}}"
    )


def s_plus_btn(size=36):
    fg = _accent_text()
    fill = glass_accent(130)
    hover = glass_accent2(190)
    pressed = glass_accent2(230)
    return (
        f"QPushButton{{background:{fill};color:{fg};"
        f"border:1px solid {glass_border(40)};border-radius:10px;"
        f"font-size:16pt;font-weight:400;"
        f"min-width:{size}px;max-width:{size}px;"
        f"min-height:{size}px;max-height:{size}px;"
        f"padding:0px; margin:0px;"
        f"text-align:center;"
        f"outline:none;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:pressed{{background:{pressed};}}"
        f"QPushButton:focus{{outline:none;}}"
    )


def s_btn(bg, fg, hover):
    if bg == "glass":
        bg = glass_soft(120)
        hover = glass_soft(180)
        fg = _accent_text()

    return (
        f"QPushButton{{background:{bg};color:{fg};"
        f"border:1px solid {glass_border(35)};border-radius:8px;"
        f'padding:8px 16px;font-family:"{theme.UI_FONT}";'
        f"font-weight: 400;"
        f"outline:none;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:focus{{outline:none;}}"
    )


def s_btn_accent():
    fg = _accent_text()
    return (
        f"QPushButton{{background:{glass_accent(180)};color:{fg};"
        f"border:1px solid {glass_accent2(220)};border-radius:8px;"
        f"padding:9px 22px;font-weight:400;"
        f'font-family:"{theme.UI_FONT}";outline:none;}}'
        f"QPushButton:hover{{background:{glass_accent2(230)};}}"
        f"QPushButton:focus{{outline:none;}}"
    )


def s_btn_launch():
    fg = _accent_text()
    fill = glass_accent(130)
    hover = glass_accent2(190)
    pressed = glass_accent2(230)
    return (
        f"QPushButton{{background:{fill};color:{fg};"
        f"border:1px solid {glass_border(40)};border-radius:10px;"
        f"font-weight:400;font-size:11pt;"
        f'padding:0 22px;font-family:"{theme.UI_FONT}";outline:none;}}'
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:pressed{{background:{pressed};}}"
        f"QPushButton:focus{{outline:none;}}"
    )


def s_btn_stop():
    return s_btn_launch()


def s_btn_set():
    fg = _accent_text()
    fill = glass_accent(130)
    hover = glass_accent2(190)
    return (
        f"QPushButton{{background:{fill};color:{fg};"
        f"border:1px solid {glass_border(40)};border-radius:10px;"
        f"font-size:10pt;font-weight:400;"
        f"padding: 0px;text-align: center;outline:none;}}"
        f"QPushButton::menu-indicator{{image:none;width:0px;}}"
        f"QPushButton:hover{{background:{hover};}}"
    )


def s_glass_btn_neutral():
    return (
        f"QPushButton{{background:{glass_soft(120)};"
        f"color:{theme.FG};padding:8px 16px;border-radius:8px;"
        f"border:1px solid {glass_border(35)};outline:none;"
        f'font-family:"{theme.UI_FONT}";font-size:10pt;}}'
        f"QPushButton:hover{{background:{glass_soft(180)};}}"
        f"QPushButton:focus{{outline:none;}}"
    )


def s_glass_list():
    return (
        f"QListWidget{{background:{glass_soft(80)};"
        f"color:{theme.FG};padding:0;border-radius:8px;"
        f"border:1px solid {glass_border(30)};outline:0}}"
        f"QListWidget:focus{{outline:none;}}"
        f"QListWidget::item{{padding:0;outline:none;"
        f"border-radius:6px;}}"
        f"QListWidget::item:focus{{outline:none;"
        f"background:transparent;}}"
        f"QListWidget::item:selected{{background:{glass_accent(90)};"
        f"outline:none;}}"
        f"QListWidget::item:hover{{background:{glass_soft(140)};"
        f"outline:none;}}"
    )


def s_glass_entry():
    return (
        f"QLineEdit{{background:{glass_soft(100)};"
        f"color:{theme.FG};"
        f"border:1px solid {glass_border(30)};"
        f"border-radius:8px;padding:8px 10px;"
        f'font-family:"{theme.UI_FONT}";font-size:10pt}}'
        f"QLineEdit:focus{{outline:none;"
        f"border:1px solid {glass_accent(180)};}}"
    )


def s_glass_textedit():
    return (
        f"QPlainTextEdit{{background:{glass_soft(100)};"
        f"color:{theme.FG};"
        f"border:1px solid {glass_border(30)};"
        f"border-radius:8px;padding:8px;"
        f'font-family:"{theme.MONO_FONT}";font-size:9pt}}'
        f"QPlainTextEdit:focus{{outline:none;"
        f"border:1px solid {glass_accent(180)};}}"
    )


def s_glass_panel():
    return (
        f"QFrame{{background:{glass_panel(110)};"
        f"border:1px solid {glass_border(25)};"
        f"border-radius:10px;}}"
    )


def s_popup_menu():
    bg = theme.popup_bg()
    hover = theme.popup_hover()
    fg = theme.popup_fg()
    brd = theme.popup_border()
    return (
        f"QMenu{{background:{bg};"
        f"color:{fg};"
        f"border:1px solid {brd};border-radius:8px;padding:6px}}"
        f"QMenu::item{{padding:6px 20px 6px 12px;border-radius:6px;"
        f"color:{fg};}}"
        f"QMenu::item:selected{{background:{hover};color:{fg};}}"
        f"QMenu::item:disabled{{color:{theme.GRAY};}}"
        f"QMenu::separator{{height:1px;"
        f"background:{theme.soft_border()};margin:4px 0}}"
    )


def s_combo_popup():
    bg = theme.popup_bg()
    hover = theme.popup_hover()
    fg = theme.popup_fg()
    return (
        f"QComboBox QAbstractItemView{{background:{bg};"
        f"color:{fg};border:none;"
        f"selection-background-color:{hover};"
        f"selection-color:{fg};"
        f"outline:none;padding:4px;}}"
        f"QComboBox QAbstractItemView::item{{padding:6px 10px;"
        f"color:{fg};}}"
        f"QComboBox QAbstractItemView::item:selected{{"
        f"background:{hover};color:{fg};}}"
    )


def s_entry():
    return (
        f"QLineEdit{{background:{glass_soft(100)};"
        f"color:{theme.FG};"
        f"border:1px solid {glass_border(30)};"
        f"border-radius:8px;padding:8px 10px;"
        f'font-family:"{theme.UI_FONT}";font-size:10pt}}'
        f"QLineEdit:focus{{outline:none;"
        f"border:1px solid {glass_accent(180)};}}"
    )


def s_combo():
    return (
        f"QComboBox{{background:{glass_soft(100)};"
        f"color:{theme.FG};"
        f"border:1px solid {glass_border(30)};"
        f"border-radius:8px;padding:6px 10px;"
        f'font-family:"{theme.UI_FONT}";font-size:10pt}}'
        f"QComboBox::drop-down{{border:none;width:20px}}"
        + s_combo_popup()
        + f"QComboBox:focus{{outline:none;"
        f"border:1px solid {glass_accent(180)};}}"
    )


def s_textedit():
    return s_glass_textedit()


def s_spin():
    return (
        f"QSpinBox{{background:{glass_soft(100)};"
        f"color:{theme.FG};"
        f"border:1px solid {glass_border(30)};"
        f"border-radius:8px;padding:6px 10px;"
        f'font-family:"{theme.UI_FONT}";font-size:10pt}}'
        f"QSpinBox:focus{{outline:none;}}"
    )


def s_tabs():
    return (
        f"QTabWidget::pane{{border:none;background:transparent}}"
        f"QTabBar::tab{{background:transparent;color:{theme.FG};"
        f"padding:7px 6px;border:none;margin-right:10;"
        f'font-family:"{theme.UI_FONT}";font-size:9pt;outline:none;}}'
        f"QTabBar::tab:selected{{color:{theme.FG};"
        f"border-bottom:1px solid {theme.ACCENT};outline:none;}}"
        f"QTabBar::tab:hover{{color:{theme.FG};outline:none;}}"
        f"QTabBar::tab:focus{{outline:none;}}"
    )


def s_menu():
    return s_popup_menu()


MC_ICON_PATH = paths.XERIA_ROOT / "cache" / "minecraft.png"
MC_ICON_URL = "https://minecraft.wiki/images/Grass_Block_JE7_BE6.png"
MC_ICON_PATH.parent.mkdir(parents=True, exist_ok=True)

_mc_nam = None


def mc_icon_sync():
    if MC_ICON_PATH.exists():
        pm = QPixmap(str(MC_ICON_PATH))
        if not pm.isNull():
            return QIcon(pm)
    return None


def fetch_mc_icon(callback):
    ic = mc_icon_sync()
    if ic is not None:
        callback(ic)
        return
    global _mc_nam
    if _mc_nam is None:
        _mc_nam = QNetworkAccessManager()
    req = QNetworkRequest(QUrl(MC_ICON_URL))
    req.setAttribute(
        QNetworkRequest.Attribute.RedirectPolicyAttribute,
        QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
    )
    reply = _mc_nam.get(req)

    def done(r=reply):
        if r.error() != QNetworkReply.NetworkError.NoError:
            r.deleteLater()
            return
        data = r.readAll()
        r.deleteLater()
        pm = QPixmap()
        if not pm.loadFromData(data) or pm.isNull():
            return
        pm = pm.scaled(20, 20, aspectRatioMode=1, transformMode=1)
        try:
            pm.save(str(MC_ICON_PATH), "PNG")
        except Exception:  # noqa: BLE001, S110
            pass
        callback(QIcon(pm))

    reply.finished.connect(done)
