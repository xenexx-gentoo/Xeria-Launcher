#!/usr/bin/env python3
import os
import sys
from pathlib import Path

if sys.platform.startswith("linux") and not os.environ.get("QT_QPA_PLATFORM"):
    st = os.environ.get("XDG_SESSION_TYPE", "").lower()
    wl = bool(os.environ.get("WAYLAND_DISPLAY")) or st == "wayland"
    os.environ["QT_QPA_PLATFORM"] = "wayland;xcb" if wl else "xcb"

from PyQt6.QtCore import QCoreApplication, Qt
QCoreApplication.setAttribute(
    Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

HERE = Path(__file__).parent
SRC = HERE / "src"
sys.path.insert(0, str(SRC))

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from core.settings import Settings
from core import translate
from core import theme

_settings = Settings()
translate.init(_settings.get_language())
theme.apply(_settings.get("theme", "dark"))
theme.apply_accent(_settings.get("accent", "Blue"))

from ui.launcher import MainWindow
from core.worker import stop_all_workers
from integration import net as _http


def _build_palette():
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(theme.BG))
    p.setColor(QPalette.ColorRole.WindowText, QColor(theme.FG))
    p.setColor(QPalette.ColorRole.Base, QColor(theme.BG2))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.BG3))
    p.setColor(QPalette.ColorRole.Text, QColor(theme.FG))
    p.setColor(QPalette.ColorRole.Button, QColor(theme.BG3))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(theme.FG))
    p.setColor(QPalette.ColorRole.Highlight, QColor(theme.ACCENT))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.on_accent()))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.BG2))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.FG))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.GRAY))
    return p


def _build_global_css():
    return (
        f"QToolTip{{background:{theme.BG2};color:{theme.FG};"
        f"border:1px solid {theme.BORDER};padding:4px}}"
        f"QScrollBar:vertical{{background:{theme.BG2};width:8px;margin:0}}"
        f"QScrollBar:horizontal{{background:{theme.BG2};height:8px;margin:0}}"
        f"QScrollBar::handle:vertical{{background:{theme.BG3};"
        f"min-height:20px;border:none}}"
        f"QScrollBar::handle:horizontal{{background:{theme.BG3};"
        f"min-width:20px;border:none}}"
        f"QScrollBar::handle:hover{{background:{theme.BORDER}}}"
        f"QScrollBar::add-line,QScrollBar::sub-line{{width:0;height:0;"
        f"background:transparent}}"
        f"QScrollBar::add-page,QScrollBar::sub-page{{background:transparent}}"
        f"QComboBox QAbstractItemView{{background:{theme.BG3};"
        f"color:{theme.FG};border:none;"
        f"selection-background-color:{theme.ACCENT};"
        f"selection-color:{theme.on_accent()}}}"
        f"QMenu{{background:{theme.BG2};color:{theme.FG};"
        f"border:none;padding:4px}}"
        f"QMenu::item{{padding:6px 20px 6px 12px}}"
        f"QMenu::item:selected{{background:{theme.BG3};color:{theme.FG}}}"
        f"QMenu::separator{{height:1px;background:{theme.BORDER};margin:4px 0}}"
    )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(translate.t("app.title"))
    app.setPalette(_build_palette())
    app.setStyleSheet(_build_global_css())

    win = MainWindow()
    win.show()
    code = app.exec()

    stop_all_workers(timeout_ms=3000)
    _http.close()
    sys.exit(code)
