#!/usr/bin/env python3
import sys
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, Qt

QCoreApplication.setAttribute(
    Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

HERE = Path(__file__).parent
SRC = HERE / "src"
sys.path.insert(0, str(SRC))

from PyQt6.QtGui import QColor, QPalette  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication, QProxyStyle, QStyle,
)

from core.settings import Settings  # noqa: E402
from core import translate  # noqa: E402
from core import theme  # noqa: E402

_settings = Settings()
translate.init(_settings.get_language())
theme.apply(_settings.get("theme", "dark"))
theme.apply_accent(_settings.get("accent", "Blue"))

from ui.main_window import MainWindow  # noqa: E402
from core.worker import stop_all_workers  # noqa: E402
from integration import net as _http  # noqa: E402


class BlankStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element in (
            QStyle.PrimitiveElement.PE_FrameFocusRect,
            QStyle.PrimitiveElement.PE_Frame,
        ):
            return
        if element == QStyle.PrimitiveElement.PE_PanelItemViewItem:
            try:
                option.state &= ~QStyle.StateFlag.State_HasFocus
                option.state &= ~QStyle.StateFlag.State_KeyboardFocusChange
            except Exception:  # noqa: BLE001, S110
                pass
        super().drawPrimitive(element, option, painter, widget)

    def drawControl(self, element, option, painter, widget=None):
        try:
            option.state &= ~QStyle.StateFlag.State_HasFocus
            option.state &= ~QStyle.StateFlag.State_KeyboardFocusChange
        except Exception:  # noqa: BLE001, S110
            pass
        super().drawControl(element, option, painter, widget)

    def drawComplexControl(self, element, option, painter, widget=None):
        try:
            option.state &= ~QStyle.StateFlag.State_HasFocus
            option.state &= ~QStyle.StateFlag.State_KeyboardFocusChange
        except Exception:  # noqa: BLE001, S110
            pass
        super().drawComplexControl(element, option, painter, widget)


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
    p.setColor(QPalette.ColorRole.HighlightedText,
               QColor(theme.on_accent()))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.BG2))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.FG))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.GRAY))
    return p


def _build_global_css():
    return (
        f"QToolTip{{background:{theme.BG2};color:{theme.FG};"
        f"border-radius:6px;padding:6px}}"
        f"QScrollBar:vertical{{background:transparent;width:10px;margin:0}}"
        f"QScrollBar:horizontal{{background:transparent;height:10px;margin:0}}"
        f"QScrollBar::handle:vertical{{background:{theme.BG3};"
        f"min-height:24px;border-radius:5px}}"
        f"QScrollBar::handle:horizontal{{background:{theme.BG3};"
        f"min-width:24px;border-radius:5px}}"
        f"QScrollBar::handle:hover{{background:{theme.BORDER}}}"
        f"QScrollBar::add-line,QScrollBar::sub-line{{width:0;height:0;"
        f"background:transparent}}"
        f"QScrollBar::add-page,QScrollBar::sub-page{{background:transparent}}"
        f"* {{ outline: none !important; }}"
        f"*:focus {{ outline: none !important; }}"
        f"QComboBox QAbstractItemView{{background:{theme.BG3};"
        f"color:{theme.FG};"
        f"selection-background-color:{theme.ACCENT};"
        f"selection-color:{theme.on_accent()}}}"
        f"QMenu{{background:{theme.BG2};color:{theme.FG};"
        f"border-radius:10px;padding:6px}}"
        f"QMenu::item{{padding:6px 20px 6px 12px;border-radius:6px}}"
        f"QMenu::item:selected{{background:{theme.BG3};color:{theme.FG}}}"
        f"QStackedWidget{{background:transparent}}"
        f"QStackedWidget::pane{{background:transparent}}"
    )


if __name__ == "__main__":
    app = QApplication(sys.argv)

    app.setStyle(BlankStyle("Fusion"))
    app.setApplicationName(translate.t("app.title"))
    app.setPalette(_build_palette())
    app.setStyleSheet(_build_global_css())

    win = MainWindow()
    win.setAutoFillBackground(False)
    win.show()

    code = app.exec()

    stop_all_workers(timeout_ms=3000)
    _http.close()
    sys.exit(code)
