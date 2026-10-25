from pathlib import Path

from PyQt6.QtCore import QSize, QUrl
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtNetwork import (
    QNetworkAccessManager, QNetworkRequest, QNetworkReply,
)
from PyQt6.QtWidgets import QApplication, QStyle

from core import theme
from core import paths


ICON_SIZE = QSize(16, 16)
ICON_SIZE_LG = QSize(20, 20)

LOADER_ICON = {
    "vanilla":  ("applications-games",
                 QStyle.StandardPixmap.SP_DesktopIcon),
    "fabric":   ("applications-science",
                 QStyle.StandardPixmap.SP_FileDialogContentsView),
    "forge":    ("applications-engineering",
                 QStyle.StandardPixmap.SP_ComputerIcon),
    "neoforge": ("applications-engineering",
                 QStyle.StandardPixmap.SP_ComputerIcon),
    "quilt":    ("applications-science",
                 QStyle.StandardPixmap.SP_FileDialogContentsView),
}


def s_icon_btn(bg, fg, hover, size=32):
    return (f"QPushButton{{background:{bg};color:{fg};border:none;"
            f"min-width:{size}px;min-height:{size}px;"
            f"max-width:{size}px;max-height:{size}px;padding:0}}"
            f"QPushButton:hover{{background:{hover}}}"
            f"QPushButton:disabled{{background:{bg};color:{theme.GRAY}}}")


def s_plus_btn(size=40):
    fg = theme.on_accent()
    return (f"QPushButton{{background:{theme.ACCENT};color:{fg};"
            f"border:none;font-size:18pt;font-weight:bold;"
            f"min-width:{size}px;max-width:{size}px;"
            f"min-height:{size}px;max-height:{size}px;"
            f"padding:0;line-height:1}}"
            f"QPushButton:hover{{background:{theme.ACCENT2}}}")


def s_btn(bg, fg, hover):
    return (f"QPushButton{{background:{bg};color:{fg};border:none;"
            f"padding:8px 16px;font-family:\"{theme.UI_FONT}\"}}"
            f"QPushButton:hover{{background:{hover}}}")


def s_btn_accent():
    fg = theme.on_accent()
    return (f"QPushButton{{background:{theme.ACCENT};color:{fg};"
            f"border:none;padding:8px 20px;font-weight:bold;"
            f"font-family:\"{theme.UI_FONT}\"}}"
            f"QPushButton:hover{{background:{theme.ACCENT2}}}")


def s_btn_launch():
    fg = theme.on_accent()
    return (f"QPushButton{{background:{theme.ACCENT};color:{fg};"
            f"border:none;font-weight:bold;font-size:11pt;"
            f"min-width:140px;"
            f"min-height:40px;max-height:40px;"
            f"padding:0 20px;"
            f"font-family:\"{theme.UI_FONT}\"}}"
            f"QPushButton:hover{{background:{theme.ACCENT2}}}")


def s_entry():
    return (f"QLineEdit{{background:{theme.BG3};color:{theme.FG};"
            f"border:none;padding:6px;"
            f"font-family:\"{theme.UI_FONT}\";font-size:10pt}}")


def s_combo():
    return (f"QComboBox{{background:{theme.BG3};color:{theme.FG};"
            f"border:none;padding:6px;"
            f"font-family:\"{theme.UI_FONT}\";font-size:10pt}}"
            f"QComboBox::drop-down{{border:none;width:20px}}"
            f"QComboBox QAbstractItemView{{background:{theme.BG3};"
            f"color:{theme.FG};border:none;"
            f"selection-background-color:{theme.ACCENT};"
            f"selection-color:{theme.on_accent()}}}")


def s_textedit():
    return (f"QPlainTextEdit{{background:{theme.BG3};color:{theme.FG};"
            f"border:none;padding:6px;"
            f"font-family:\"{theme.MONO_FONT}\";font-size:9pt}}")


def s_spin():
    return (f"QSpinBox{{background:{theme.BG3};color:{theme.FG};"
            f"border:none;padding:6px;"
            f"font-family:\"{theme.UI_FONT}\";font-size:10pt}}")


def s_tabs():
    return (f"QTabWidget::pane{{border:none;background:{theme.BG2}}}"
            f"QTabBar::tab{{background:transparent;color:{theme.FG};"
            f"padding:7px 6px;border:none;margin-right:10;"
            f"font-family:\"{theme.UI_FONT}\";font-size:9pt}}"
            f"QTabBar::tab:selected{{color:{theme.FG};"
            f"border-bottom:1px solid {theme.ACCENT}}}"
            f"QTabBar::tab:hover{{color:{theme.FG}}}")


def s_menu():
    return (f"QMenu{{background:{theme.BG2};color:{theme.FG};"
            f"border:none;padding:4px}}"
            f"QMenu::item{{padding:6px 20px 6px 12px}}"
            f"QMenu::item:selected{{background:{theme.BG3};"
            f"color:{theme.FG}}}"
            f"QMenu::separator{{height:1px;"
            f"background:{theme.BORDER};margin:4px 0}}")


MC_ICON_PATH = paths.XERIA_ROOT / "cache" / "minecraft.png"
MC_ICON_URL = ("https://minecraft.wiki/images/"
               "Grass_Block_JE7_BE6.png")
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
        QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
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
        pm = pm.scaled(
            20, 20,
            aspectRatioMode=1,
            transformMode=1)
        try:
            pm.save(str(MC_ICON_PATH), "PNG")
        except Exception:
            pass
        callback(QIcon(pm))

    reply.finished.connect(done)
