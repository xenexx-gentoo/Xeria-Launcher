import os
import platform
import subprocess
import time
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QSize, QPropertyAnimation, QEasingCurve,
    QRectF, QPointF, QUrl,
)
from PyQt6.QtGui import (
    QFont, QColor, QPalette, QIcon, QAction,
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QApplication, QSplitter, QStackedWidget, QStyle, QSizePolicy,
    QStyledItemDelegate, QStyleOptionViewItem,
)

from core import theme
from core import hardware
from core import translate
from core.paths import MC_ROOT, PROFILES_DIR, IS_WIN
from core.settings import Settings, detect_gpu
from core.worker import Worker, _shutdown, _leaked_threads
from instances.profiles import ProfilesMixin
from instances.launch import LaunchMixin
from instances.fetch import FetchMixin
from ui.console import Console
from ui.dialogs import (
    ChooseInstallDialog, ModpackSearchDialog, fade_in, ProfileDialog,
)
from ui.helpers import (
    s_btn, s_tabs, s_menu,
    s_btn_launch, s_plus_btn,
)
from ui.loader_icons import (
    loader_icon_sync, fetch_loader_icon, fetch_all_loaders,
)
from ui.menu import MenuView
from ui.account import AccountView
from browse.mods import ModsDialog
from browse.resourcepacks import ResourcePacksDialog
from browse.shaderpacks import ShadersDialog
from integration import net as http


BROWSE_BY_KIND = {
    "mod": ModsDialog,
    "resourcepack": ResourcePacksDialog,
    "shader": ShadersDialog,
}


class _NoTintDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is None or icon.isNull():
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.icon = QIcon()
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt,
                          painter, widget)
        size = opt.decorationSize
        if size.isValid() and not size.isEmpty():
            x = opt.rect.left() + 8
            y = opt.rect.top() + (opt.rect.height() - size.height()) // 2
            rect = QRectF(x, y, size.width(), size.height())
            icon.paint(painter, rect.toRect(),
                       Qt.AlignmentFlag.AlignCenter, QIcon.Mode.Normal)


def slide_widget_h(widget, visible, target=340, duration=180):
    if visible and widget.isVisible() and widget.maximumWidth() == target:
        return
    if not visible and (not widget.isVisible()
                        or widget.maximumWidth() == 0):
        return
    hw = hardware.get()
    if hw.tier == "potato":
        if visible:
            widget.setVisible(True)
            widget.setMaximumWidth(target)
        else:
            widget.setVisible(False)
            widget.setMaximumWidth(0)
        return
    if visible:
        widget.setVisible(True)
        widget.setMaximumWidth(0)
        start, end = 0, target
    else:
        start = max(widget.width(), 200)
        end = 0
    a = QPropertyAnimation(widget, b"maximumWidth", widget)
    a.setDuration(duration)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setEasingCurve(QEasingCurve.Type.OutCubic)
    if not visible:
        a.finished.connect(lambda: (
            widget.setVisible(False), widget.setMaximumWidth(0)))
    else:
        a.finished.connect(lambda: widget.setMaximumWidth(target))
    widget._anim_h = a
    a.start()


class _DraggableTitle(QLabel):
    SPRING = 0.18
    DAMPING = 0.82
    GRAVITY = 0.6

    def __init__(self, text, parent):
        super().__init__(text, parent)
        self._parent = parent
        self._held = False
        self._vel = QPointF(0, 0)
        self._home = None
        self._drag_off = QPointF(0, 0)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._physics_step)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def _home_point(self):
        if self._home is None:
            self._home = self.pos()
        return self._home

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._held = True
            self._vel = QPointF(0, 0)
            self._drag_off = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.raise_()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._held:
            local = e.position()
            p = self.mapToParent(local - self._drag_off)
            self.move(p)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._held:
            self._held = False
            self._vel = QPointF(
                (self.pos().x() - getattr(self, "_lx", self.pos().x())) * 0.4,
                (self.pos().y() - getattr(self, "_ly", self.pos().y())) * 0.4)
            self._timer.start()
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(e)

    def _physics_step(self):
        parent = self._parent
        if parent is None:
            self._timer.stop()
            return
        hx, hy = self._home_point().x(), self._home_point().y()
        cx, cy = self.pos().x(), self.pos().y()

        self._vel.setX(
            self._vel.x() * self.DAMPING + (hx - cx) * self.SPRING)
        self._vel.setY(
            self._vel.y() * self.DAMPING + (hy - cy) * self.SPRING)
        self._vel.setY(self._vel.y() + self.GRAVITY)

        nx, ny = cx + self._vel.x(), cy + self._vel.y()
        w, h = self.width(), self.height()
        pw, ph = parent.width(), parent.height()
        if nx < 0:
            nx = 0
            self._vel.setX(abs(self._vel.x()) * 0.5)
        if ny < 0:
            ny = 0
            self._vel.setY(abs(self._vel.y()) * 0.5)
        if nx + w > pw:
            nx = pw - w
            self._vel.setX(-abs(self._vel.x()) * 0.5)
        if ny + h > ph:
            ny = ph - h
            self._vel.setY(-abs(self._vel.y()) * 0.5)

        self._lx, self._ly = cx, cy
        self.move(int(nx), int(ny))

        if (abs(nx - hx) < 0.6 and abs(ny - hy) < 0.6
                and abs(self._vel.x()) < 0.5
                and abs(self._vel.y()) < 0.5):
            self.move(int(hx), int(hy))
            self._vel = QPointF(0, 0)
            self._timer.stop()


class MainWindow(LaunchMixin, ProfilesMixin, FetchMixin, QMainWindow):
    mc_log = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.account = self.settings.get_account()
        self.setWindowTitle(translate.t("app.title"))
        self.resize(1180, 740)
        self.setMinimumSize(960, 600)
        self.setStyleSheet(
            f"QMainWindow,QWidget{{background:{theme.BG};"
            f"color:{theme.FG}}}")
        self.manifest, self.releases, self.profiles = None, [], []
        self._row_map = []
        self.current_profile = None
        self._workers = []
        self._process = None
        self._running_profile = None
        self._launching_profile = None
        self._build_ui()
        self.mc_log.connect(self._on_mc_log,
                            Qt.ConnectionType.QueuedConnection)

        self._auto_check_timer = QTimer(self)
        self._auto_check_timer.setSingleShot(True)
        self._auto_check_timer.timeout.connect(self._run_auto_check)

        QTimer.singleShot(100, self._startup)

    def _on_mc_log(self, line):
        if line == "__exit__":
            self._set_launch_state(False)
            return
        if line:
            self.console.log("mc", line)

    def _set_account(self, acc):
        self.account = acc
        self.settings.set_account(acc)

    @staticmethod
    def _title_color(t):
        a = (t.ACCENT or "").lower()
        if a in ("#ffffff", "#fff", "white"):
            return t.FG
        return t.ACCENT

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        h = QHBoxLayout()
        h.setSpacing(6)
        self.title_lbl = _DraggableTitle(
            translate.t("app.title"), central)
        self.title_lbl.setStyleSheet(
            f"background:transparent;color:{self._title_color(theme)};"
            f"font-size:15pt;font-weight:bold")
        h.addWidget(self.title_lbl)
        h.addStretch()

        self.account_btn = QPushButton(translate.t("btn.account"))
        self.account_btn.setStyleSheet(
            s_btn(theme.BG2, theme.FG, theme.BG3))
        self.account_btn.setMinimumWidth(90)
        self.account_btn.clicked.connect(self.open_account_view)
        h.addWidget(self.account_btn)

        self.gear_btn = QPushButton(translate.t("btn.menu"))
        self.gear_btn.setStyleSheet(
            s_btn(theme.BG2, theme.FG, theme.BG3))
        self.gear_btn.setMinimumWidth(90)
        self.gear_btn.clicked.connect(self.toggle_menu)
        h.addWidget(self.gear_btn)
        root.addLayout(h)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(20)
        self.split.setStyleSheet("QSplitter::handle{background:transparent}")
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)

        self.left = QFrame()
        self.left.setMinimumWidth(220)
        self.left.setMaximumWidth(340)
        self.left.setSizePolicy(QSizePolicy.Policy.Preferred,
                                QSizePolicy.Policy.Expanding)
        self.left.setStyleSheet(f"QFrame{{background:{theme.BG2}}}")
        ll = QVBoxLayout(self.left)
        ll.setContentsMargins(14, 12, 14, 12)
        ll.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        lbl_col = QVBoxLayout()
        lbl_col.setSpacing(2)
        self.instances_lbl = QLabel(translate.t("header.instances"))
        self.instances_lbl.setStyleSheet(
            f"background:transparent;color:{theme.FG};"
            f"font-size:14pt;font-weight:bold")
        lbl_col.addWidget(self.instances_lbl)
        self.instances_sub = QLabel("")
        self.instances_sub.setStyleSheet(
            f"background:transparent;color:{theme.GRAY};font-size:10pt")
        lbl_col.addWidget(self.instances_sub)
        bar.addLayout(lbl_col, 1)

        self.add_btn = QPushButton("+")
        self.add_btn.setToolTip(translate.t("header.instances"))
        self.add_btn.setStyleSheet(s_plus_btn())
        self.add_btn.setFixedSize(36, 36)
        self.add_btn.setSizePolicy(QSizePolicy.Policy.Fixed,
                                   QSizePolicy.Policy.Fixed)
        self.add_btn.clicked.connect(self.add_new)
        bar.addWidget(self.add_btn, 0,
                      Qt.AlignmentFlag.AlignVCenter
                      | Qt.AlignmentFlag.AlignRight)
        ll.addLayout(bar)

        self.plist = QListWidget()
        self.plist.setFont(QFont(theme.UI_FONT, 10))
        self.plist.setSpacing(0)
        self.plist.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.plist.setIconSize(QSize(20, 20))
        self.plist.setItemDelegate(_NoTintDelegate(self.plist))
        self.plist.setStyleSheet(
            f"QListWidget{{background:{theme.BG2};color:{theme.FG};"
            f"border:none;outline:none;padding:0}}"
            f"QListWidget::item{{padding:8px;border:none}}"
            f"QListWidget::item:hover{{background:{theme.BG3};"
            f"border:none}}"
            f"QListWidget::item:selected{{background:{theme.BG3};"
            f"color:{theme.FG};padding:8px;border:none}}")
        pal = self.plist.palette()
        pal.setColor(QPalette.ColorRole.Highlight, QColor(theme.BG3))
        pal.setColor(QPalette.ColorRole.HighlightedText,
                     QColor(theme.FG))
        self.plist.setPalette(pal)
        self.plist.currentRowChanged.connect(self._on_row_changed)
        self.plist.customContextMenuRequested.connect(self._ctx_menu)
        ll.addWidget(self.plist, 1)

        self.lang_box = QPushButton()
        self.lang_box.setStyleSheet(
            s_btn(theme.BG2, theme.GRAY, theme.BG3))
        self.lang_box.setFixedHeight(28)
        self.lang_box.clicked.connect(self._show_lang_menu)
        self._refresh_lang_button()
        ll.addWidget(self.lang_box)

        self.split.addWidget(self.left)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Expanding)

        self.inst_view = QWidget()
        self.inst_view.setStyleSheet(
            f"QWidget{{background:{theme.BG}}}")
        il = QVBoxLayout(self.inst_view)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(20)

        self.card = QFrame()
        self.card.setStyleSheet(f"QFrame{{background:{theme.BG2}}}")
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(12)
        info = QVBoxLayout()
        info.setSpacing(2)
        self.card_title = QLabel(translate.t("card.no_instance"))
        self.card_title.setStyleSheet(
            f"background:transparent;color:{theme.FG};"
            f"font-size:14pt;font-weight:bold")
        self.card_title.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Preferred)
        info.addWidget(self.card_title)
        self.card_sub = QLabel(translate.t("card.create_hint"))
        self.card_sub.setStyleSheet(
            f"background:transparent;color:{theme.GRAY};font-size:10pt")
        self.card_sub.setWordWrap(True)
        self.card_sub.setSizePolicy(QSizePolicy.Policy.Expanding,
                                    QSizePolicy.Policy.Preferred)
        info.addWidget(self.card_sub)
        top.addLayout(info, 1)

        self.launch_btn = QPushButton(translate.t("btn.launch"))
        self.launch_btn.setMinimumWidth(140)
        self.launch_btn.setSizePolicy(QSizePolicy.Policy.Preferred,
                                      QSizePolicy.Policy.Fixed)
        self.launch_btn.setStyleSheet(s_btn_launch())
        self.launch_btn.clicked.connect(self.launch_toggle)
        top.addWidget(self.launch_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        cl.addLayout(top)
        il.addWidget(self.card)

        self.console_frame = QFrame()
        self.console_frame.setStyleSheet(
            f"QFrame{{background:{theme.BG2}}}")
        cfl = QVBoxLayout(self.console_frame)
        cfl.setContentsMargins(10, 10, 10, 10)
        cfl.setSpacing(0)
        self.console = Console()
        self.console.setMinimumHeight(200)
        cfl.addWidget(self.console, 1)
        il.addWidget(self.console_frame, 1)

        self.stack.addWidget(self.inst_view)

        self.menu_view = MenuView(self, self.settings)
        self.menu_view.theme_changed.connect(self._apply_theme_live)
        self.stack.addWidget(self.menu_view)

        self.account_view = AccountView(
            self, self.settings, log=self.console.log)
        self.stack.addWidget(self.account_view)

        self.split.addWidget(self.stack)
        self.split.setSizes([260, 920])
        root.addWidget(self.split, 1)

    def _refresh_lang_button(self):
        code = translate.get_language()
        name = next((n for c, n in translate.available_languages()
                     if c == code), code)
        self.lang_box.setText(name)

    def _show_lang_menu(self):
        m = QMenu(self)
        m.setStyleSheet(s_menu())
        for code, name in translate.available_languages():
            a = QAction(name, m)
            a.setCheckable(True)
            a.setChecked(code == translate.get_language())
            a.triggered.connect(lambda _=False, c=code: self._set_lang(c))
            m.addAction(a)
        m.exec(self.lang_box.mapToGlobal(
            self.lang_box.rect().bottomLeft()))

    def _set_lang(self, code):
        if code == translate.get_language():
            return
        translate.set_language(code)
        self.settings.set_language(code)
        name = next((n for c, n in translate.available_languages()
                     if c == code), code)
        self.console.log("ok", translate.t(
            "console.language_changed", name=name))
        self.console.log("warn", translate.t(
            "console.language_restart"))
        self._refresh_lang_button()
        self.gear_btn.setText(translate.t("btn.menu"))
        self.account_btn.setText(translate.t("btn.account"))
        self.launch_btn.setText(
            translate.t("btn.launch") if self._process is None
            else translate.t("btn.stop"))

    def toggle_menu(self):
        i = self.stack.currentIndex()
        if i == 1:
            self.stack.setCurrentIndex(0)
            self._reset_header()
            slide_widget_h(self.left, True)
        else:
            self.stack.setCurrentIndex(1)
            self._set_back_mode("Menu")
            slide_widget_h(self.left, False)

    def open_account_view(self):
        i = self.stack.currentIndex()
        if i == 2:
            self.stack.setCurrentIndex(0)
            self._reset_header()
            slide_widget_h(self.left, True)
        else:
            self.stack.setCurrentIndex(2)
            self.account_view.refresh()
            self._set_back_mode("Account")
            slide_widget_h(self.left, False)

    def _set_back_mode(self, source):
        if source == "Menu":
            self.gear_btn.setText(translate.t("btn.back"))
            self.account_btn.setText(translate.t("btn.account"))
        else:
            self.account_btn.setText(translate.t("btn.back"))
            self.gear_btn.setText(translate.t("btn.menu"))

    def _reset_header(self):
        self.gear_btn.setText(translate.t("btn.menu"))
        self.account_btn.setText(translate.t("btn.account"))

    def _apply_theme_live(self, theme_name, accent_name):
        from core import theme as _theme
        _theme.apply(theme_name)
        _theme.apply_accent(accent_name)

        app = QApplication.instance()
        pal = app.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(_theme.BG))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(_theme.FG))
        pal.setColor(QPalette.ColorRole.Base, QColor(_theme.BG2))
        pal.setColor(QPalette.ColorRole.AlternateBase,
                     QColor(_theme.BG3))
        pal.setColor(QPalette.ColorRole.Text, QColor(_theme.FG))
        pal.setColor(QPalette.ColorRole.Button, QColor(_theme.BG3))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(_theme.FG))
        pal.setColor(QPalette.ColorRole.Highlight, QColor(_theme.ACCENT))
        pal.setColor(QPalette.ColorRole.HighlightedText,
                     QColor(_theme.on_accent()))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(_theme.BG2))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor(_theme.FG))
        pal.setColor(QPalette.ColorRole.PlaceholderText,
                     QColor(_theme.GRAY))
        app.setPalette(pal)

        app.setStyleSheet(
            f"QToolTip{{background:{_theme.BG2};color:{_theme.FG};"
            f"border:1px solid {_theme.BORDER};padding:4px}}"
            f"QScrollBar:vertical{{background:{_theme.BG2};"
            f"width:8px;margin:0}}"
            f"QScrollBar:horizontal{{background:{_theme.BG2};"
            f"height:8px;margin:0}}"
            f"QScrollBar::handle:vertical{{background:{_theme.BG3};"
            f"min-height:20px;border:none}}"
            f"QScrollBar::handle:horizontal{{background:{_theme.BG3};"
            f"min-width:20px;border:none}}"
            f"QScrollBar::handle:hover{{background:{_theme.BORDER}}}"
            f"QScrollBar::add-line,QScrollBar::sub-line{{width:0;"
            f"height:0;background:transparent}}"
            f"QScrollBar::add-page,QScrollBar::sub-page{{"
            f"background:transparent}}"
            f"QComboBox QAbstractItemView{{background:{_theme.BG3};"
            f"color:{_theme.FG};border:none;"
            f"selection-background-color:{_theme.ACCENT};"
            f"selection-color:{_theme.on_accent()}}}"
            f"QMenu{{background:{_theme.BG2};color:{_theme.FG};"
            f"border:none;padding:4px}}"
            f"QMenu::item{{padding:6px 20px 6px 12px}}"
            f"QMenu::item:selected{{background:{_theme.BG3};"
            f"color:{_theme.FG}}}"
            f"QMenu::separator{{height:1px;"
            f"background:{_theme.BORDER};margin:4px 0}}")

        self.setStyleSheet(
            f"QMainWindow,QWidget{{background:{_theme.BG};"
            f"color:{_theme.FG}}}")

        self.title_lbl.setStyleSheet(
            f"background:transparent;"
            f"color:{self._title_color(_theme)};"
            f"font-size:15pt;font-weight:bold")

        self.left.setStyleSheet(f"QFrame{{background:{_theme.BG2}}}")
        self.instances_lbl.setStyleSheet(
            f"background:transparent;color:{_theme.FG};"
            f"font-size:14pt;font-weight:bold")
        self.instances_sub.setStyleSheet(
            f"background:transparent;color:{_theme.GRAY};"
            f"font-size:10pt")
        self.plist.setStyleSheet(
            f"QListWidget{{background:{_theme.BG2};color:{_theme.FG};"
            f"border:none;outline:none;padding:0}}"
            f"QListWidget::item{{padding:8px;border:none}}"
            f"QListWidget::item:hover{{background:{_theme.BG3};"
            f"border:none}}"
            f"QListWidget::item:selected{{background:{_theme.BG3};"
            f"color:{_theme.FG};padding:8px;border:none}}")
        pal = self.plist.palette()
        pal.setColor(QPalette.ColorRole.Highlight, QColor(_theme.BG3))
        pal.setColor(QPalette.ColorRole.HighlightedText,
                     QColor(_theme.FG))
        self.plist.setPalette(pal)
        self.add_btn.setStyleSheet(s_plus_btn())
        self.add_btn.setFixedSize(36, 36)
        self.lang_box.setStyleSheet(
            s_btn(_theme.BG2, _theme.GRAY, _theme.BG3))

        self.inst_view.setStyleSheet(
            f"QWidget{{background:{_theme.BG}}}")
        self.card.setStyleSheet(f"QFrame{{background:{_theme.BG2}}}")
        self.card_title.setStyleSheet(
            f"background:transparent;color:{_theme.FG};"
            f"font-size:14pt;font-weight:bold")
        self.card_sub.setStyleSheet(
            f"background:transparent;color:{_theme.GRAY};"
            f"font-size:10pt")
        self.console_frame.setStyleSheet(
            f"QFrame{{background:{_theme.BG2}}}")
        if hasattr(self.console, "restyle"):
            self.console.restyle()
        self.account_btn.setStyleSheet(
            s_btn(_theme.BG2, _theme.FG, _theme.BG3))
        self.gear_btn.setStyleSheet(
            s_btn(_theme.BG2, _theme.FG, _theme.BG3))
        self.launch_btn.setStyleSheet(s_btn_launch())
        self.launch_btn.setMinimumWidth(140)

        self.menu_view.tabs.setStyleSheet(s_tabs())
        if hasattr(self.menu_view, "restyle"):
            self.menu_view.restyle()
        if hasattr(self.account_view, "restyle"):
            self.account_view.restyle()

        self._update_card()
        self.console.log("ok", translate.t(
            "console.theme_applied",
            theme=theme_name, accent=accent_name))

    def _track(self, w):
        self._workers.append(w)
        w.finished.connect(
            lambda: self._workers.remove(w)
            if w in self._workers else None)

    def _startup(self):
        hw = hardware.get()
        self.console.log(
            "sys",
            f"Platform {platform.system()} "
            f"Python {platform.python_version()}")
        self.console.log("sys", f"Hardware {hw.summary()}")
        self.console.log("sys", f"GPU {detect_gpu()}")
        self.console.log("sys", f"Minecraft root {MC_ROOT}")
        self.load_profiles()
        self.fetch_manifest()
        self._warm_modrinth()
        fetch_all_loaders(self._apply_loader_icon)
        self._schedule_auto_check()

    def _schedule_auto_check(self):
        try:
            interval = int(
                self.settings.get("auto_check_interval", 86400))
        except (TypeError, ValueError):
            interval = 86400
        if interval <= 0:
            self._auto_check_timer.stop()
            return
        try:
            last = float(
                self.settings.get("auto_check_last_run", 0))
        except (TypeError, ValueError):
            last = 0.0
        elapsed = time.time() - last if last > 0 else interval
        delay = max(30, int(interval - elapsed))
        self._auto_check_timer.start(delay * 1000)

    def _run_auto_check(self):
        try:
            self.settings.set("auto_check_last_run", time.time())
            self.settings.save()
        except Exception:
            pass
        profiles = list(self.profiles)
        if not profiles:
            self._schedule_auto_check()
            return
        self.console.log("sys", translate.t("console.auto_check"))
        for prof in profiles:
            try:
                mods_dir = prof.dir / "mods"
                if not mods_dir.exists():
                    continue
                jars = [f for f in mods_dir.iterdir()
                        if f.is_file() and f.suffix.lower() == ".jar"]
                if not jars:
                    continue
                mv = prof.version
                ld = (prof.loader or "vanilla").lower()
                paths = [str(j) for j in jars]

                def task(log, progress, progress_end,
                         paths_=paths, mv_=mv, ld_=ld, prof_=prof):
                    from integration import modrinth
                    result = modrinth.resolve_mods_parallel(
                        paths_, mv_, "mod", ld_, workers=3)
                    try:
                        meta = getattr(prof_, "mods_meta", {}) or {}
                        meta.update(result)
                        prof_.mods_meta = meta
                        prof_.save()
                    except Exception:
                        pass
                    return prof_, result

                w = Worker(task)
                w.log.connect(self.console.log,
                              Qt.ConnectionType.QueuedConnection)
                w.done.connect(self._on_auto_check_done,
                               Qt.ConnectionType.QueuedConnection)
                self._track(w)
                w.start()
            except Exception as e:
                self.console.log("warn", str(e))
        self._schedule_auto_check()

    def _on_auto_check_done(self, payload):
        if not payload:
            return
        prof, result = payload
        hits = sum(1 for r in (result or {}).values()
                   if r.get("project_id"))
        total = len(result or {})
        self.console.log("ok", translate.t(
            "console.auto_check_done",
            hits=hits, total=total, name=prof.name))

    def _warm_modrinth(self):
        if not hasattr(self, "_warm_nam"):
            self._warm_nam = QNetworkAccessManager(self)
        req = QNetworkRequest(QUrl("https://api.modrinth.com/"))
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        req.setRawHeader(b"User-Agent", b"Xeria-Launcher/2.504")
        self._warm_nam.get(req)

    def _apply_loader_icon(self, name, ic):
        for i, p in enumerate(self._row_map):
            if (p.loader or "").lower() == name:
                it = self.plist.item(i)
                if it is not None:
                    it.setIcon(ic)

    def _ctx_menu(self, pos):
        it = self.plist.itemAt(pos)
        if not it:
            return
        self.plist.setCurrentItem(it)
        if not self.current_profile:
            return
        m = QMenu(self)
        m.setStyleSheet(s_menu())
        for label_key, kind in (("title.mods", "mod"),
                                ("title.resourcepacks", "resourcepack"),
                                ("title.shaders", "shader")):
            a = QAction(translate.t(label_key), m)
            a.triggered.connect(lambda _, k=kind: self._open_browse(k))
            m.addAction(a)
        m.addSeparator()
        for label_key, fn in (
            ("menu.edit_instance", self.edit_profile),
            ("menu.open_folder", self.open_folder),
            ("menu.rename", self.rename_profile),
            ("menu.duplicate", self.duplicate_profile),
        ):
            a = QAction(translate.t(label_key), m)
            a.triggered.connect(fn)
            m.addAction(a)
        m.addSeparator()
        exp = m.addMenu(translate.t("menu.export_instance"))
        exp.setStyleSheet(s_menu())
        for label_key, fn in (
            ("menu.export_modrinth", self.export_mrpack),
            ("menu.export_xeria", self.export_xeriapack),
        ):
            a = QAction(translate.t(label_key), exp)
            a.triggered.connect(fn)
            exp.addAction(a)
        for label_key, fn in (
            ("menu.import_instance", self.import_instance),
            ("menu.backup", self.backup_instance),
            ("menu.copy_cmd", self.copy_launch_command),
            ("menu.open_logs", self.open_logs),
        ):
            a = QAction(translate.t(label_key), m)
            a.triggered.connect(fn)
            m.addAction(a)
        m.addSeparator()
        a = QAction(translate.t("btn.delete"), m)
        a.triggered.connect(self.delete_profile)
        m.addAction(a)
        m.exec(self.plist.mapToGlobal(pos))

    def _open_browse(self, kind):
        if not self.current_profile:
            return
        dlg_cls = BROWSE_BY_KIND[kind]
        dlg_cls(self, self.current_profile, self.console.log).exec()

    def closeEvent(self, event):
        _shutdown.set()
        try:
            self._auto_check_timer.stop()
        except Exception:
            pass
        p = self._process
        if p and p.poll() is None:
            try:
                if IS_WIN:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                        capture_output=True)
                else:
                    p.terminate()
                p.wait(2000)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        for w in list(self._workers):
            try:
                if w.isRunning():
                    try:
                        w.log.disconnect()
                        w.done.disconnect()
                        w.progress.disconnect()
                        w.progress_end.disconnect()
                    except Exception:
                        pass
                    w.quit()
                    if not w.wait(3000):
                        _leaked_threads.append(w)
                        w.setParent(None)
            except Exception:
                pass
        http.close()
        event.accept()
