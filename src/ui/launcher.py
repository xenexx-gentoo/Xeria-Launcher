import contextlib
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QPainter,
    QPalette,
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from browse.items import ItemsDialog
from browse.modpacks import ModpackSearchDialog
from core import hardware, theme, translate
from core.java import best_java
from core.jvm import build_jvm_flags
from core.paths import (
    IS_MAC,
    IS_WIN,
    MANIFEST_URL,
    MC_ROOT,
    NO_WINDOW,
    PROFILES_DIR,
    XERIA_ROOT,
)
from core.settings import Settings, detect_gpu
from core.worker import Worker, _leaked_threads, _shutdown
from instances import modpack
from instances.env import build_launch_env
from instances.profile import Profile
from integration import loaders
from integration import net as http
from ui.account import AccountView
from ui.console import Console
from ui.dialogs import (
    ChooseInstallDialog,
    ProfileDialog,
)
from ui.helpers import (
    s_btn_launch,
    s_btn_set,
    s_btn_stop,
    s_combo_popup,
    s_menu,
    s_plus_btn,
    s_popup_menu,
    s_tabs,
)
from ui.loader_icons import (
    fetch_all_loaders,
    fetch_loader_icon,
    loader_icon_sync,
)
from ui.menu import MenuView
from ui.particles import ParticleOverlayMixin

HW = hardware.get()


def _detached_flags():
    if IS_WIN:
        return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    return 0


def _square_pixmap(pm, side=20):
    if pm is None or pm.isNull():
        return None

    img = pm.toImage().convertToFormat(pm.toImage().Format.Format_ARGB32)
    w, h = img.width(), img.height()
    if w > 0 and h > 0:
        ptr = img.bits()
        ptr.setsize(img.sizeInBytes())
        buf = bytes(ptr)
        bpl = img.bytesPerLine()
        minx, miny, maxx, maxy = w, h, -1, -1
        for y in range(h):
            row = y * bpl
            for x in range(w):
                if buf[row + x * 4 + 3] > 8:
                    minx = min(minx, x)
                    miny = min(miny, y)
                    maxx = max(maxx, x)
                    maxy = max(maxy, y)
        if maxx >= 0:
            pm = pm.copy(minx, miny, maxx - minx + 1, maxy - miny + 1)

    return pm.scaled(
        side,
        side,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class _InstanceRow(QWidget):
    ICON_SIDE = 20

    def __init__(self, name, version, folder_name, loader_icon=None):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._raw_name = name
        self._raw_folder = folder_name

        self.icon_lbl = QLabel(self)
        self.icon_lbl.setFixedSize(self.ICON_SIDE, self.ICON_SIDE)
        self.icon_lbl.setStyleSheet("background:transparent;")
        self.icon_lbl.setScaledContents(False)

        if loader_icon and not loader_icon.isNull():
            src = loader_icon.pixmap(self.ICON_SIDE * 2, self.ICON_SIDE * 2)
            square = _square_pixmap(src, self.ICON_SIDE)
            if square is not None:
                self.icon_lbl.setPixmap(square)

        self.name_lbl = QLabel(self)
        self.name_lbl.setStyleSheet(
            f"background:transparent;color:{theme.FG};"
            f"font-size:10pt;font-weight:400;"
            f"font-family:'{theme.UI_FONT}';"
        )
        self.name_lbl.setWordWrap(False)
        self.name_lbl.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self.ver_lbl = QLabel(self)
        self.ver_lbl.setStyleSheet(
            f"background:transparent;color:{theme.GRAY};"
            f"font-size:8pt;font-weight:300;"
            f"font-family:'{theme.UI_FONT}';"
        )
        self.ver_lbl.setWordWrap(False)
        self.ver_lbl.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)

        x_icon = 8
        y_icon = (self.height() - self.ICON_SIDE) // 2
        self.icon_lbl.move(x_icon, y_icon)

        x_text = x_icon + self.ICON_SIDE + 10
        avail_width = max(10, self.width() - x_text - 12)

        total_text_height = 20 + 16
        y_top = (self.height() - total_text_height) // 2

        fm_name = QFontMetrics(self.name_lbl.font())
        elided_name = fm_name.elidedText(
            self._raw_name, Qt.TextElideMode.ElideRight, avail_width
        )
        self.name_lbl.setText(elided_name)
        self.name_lbl.setGeometry(x_text, y_top, avail_width, 20)

        fm_ver = QFontMetrics(self.ver_lbl.font())
        elided_ver = fm_ver.elidedText(
            self._raw_folder, Qt.TextElideMode.ElideRight, avail_width
        )
        self.ver_lbl.setText(elided_ver)
        self.ver_lbl.setGeometry(x_text, y_top + 20, avail_width, 16)

    def set_icon(self, icon):
        if not icon or icon.isNull():
            return
        src = icon.pixmap(self.ICON_SIDE * 2, self.ICON_SIDE * 2)
        square = _square_pixmap(src, self.ICON_SIDE)
        if square is not None:
            self.icon_lbl.setPixmap(square)


class _NoTintDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            accent_col = QColor(theme.ACCENT)
            accent_col.setAlpha(60 if selected else 30)
            painter.setBrush(accent_col)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 8, 8)

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(0, 48)


def slide_widget_h(widget, visible, target=340, duration=180):
    if visible and widget.isVisible() and widget.maximumWidth() == target:
        return
    if not visible and (not widget.isVisible() or widget.maximumWidth() == 0):
        return
    hw = hardware.get()
    if not getattr(hw, "animations", True):
        if visible:
            widget.setVisible(True)
            widget.setMaximumWidth(target)
        else:
            widget.setVisible(False)
            widget.setMaximumWidth(0)
        return
    widget.setMinimumWidth(0)
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
        a.finished.connect(
            lambda: (widget.setVisible(False), widget.setMaximumWidth(0))
        )
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
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
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
            self.move(int(p.x()), int(p.y()))
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._held:
            self._held = False
            self._vel = QPointF(
                (self.pos().x() - getattr(self, "_lx", self.pos().x())) * 0.4,
                (self.pos().y() - getattr(self, "_ly", self.pos().y())) * 0.4,
            )
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

        self._vel.setX(self._vel.x() * self.DAMPING + (hx - cx) * self.SPRING)
        self._vel.setY(self._vel.y() * self.DAMPING + (hy - cy) * self.SPRING)
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

        if (
            abs(nx - hx) < 0.6
            and abs(ny - hy) < 0.6
            and abs(self._vel.x()) < 0.5
            and abs(self._vel.y()) < 0.5
        ):
            self.move(int(hx), int(hy))
            self._vel = QPointF(0, 0)
            self._timer.stop()


class MainWindow(ParticleOverlayMixin, QMainWindow):
    mc_log = pyqtSignal(str)

    ROW_HEIGHT = 48
    ROW_GAP = 0

    def __init__(self):
        super().__init__()

        self.settings = Settings()
        self.account = self.settings.get_account()
        self.setWindowTitle(translate.t("app.title"))
        self.resize(1180, 740)
        self.setMinimumSize(960, 600)

        self.manifest = None
        self.releases = []
        self.profiles = []
        self._row_map = []
        self._row_widgets = {}
        self.current_profile = None
        self._workers = []
        self._process = None
        self._running_profile = None
        self._launching_profile = None

        self._build_ui()
        self.mc_log.connect(self._on_mc_log, Qt.ConnectionType.QueuedConnection)

        self._apply_theme_live(theme.current_name, self.settings.get("accent", "White"))

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

    def _title_css(self, t):
        a = (t.ACCENT or "").lower()
        color = t.FG if a in ("#ffffff", "#fff", "white") else t.ACCENT
        return (
            f"background:transparent;color:{color};"
            f"font-size:16pt;font-family:'{theme.UI_FONT}';"
            f"font-weight:300; letter-spacing: 1px;"
        )

    def _build_ui(self):
        central = QWidget()
        central.setAutoFillBackground(False)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(10)

        h = QHBoxLayout()
        h.setSpacing(12)

        self.title_frame = QFrame()
        self.title_frame.setStyleSheet("background:transparent;")
        tf = QHBoxLayout(self.title_frame)
        tf.setContentsMargins(0, 0, 0, 0)
        tf.setSpacing(0)
        self.title_lbl = _DraggableTitle(translate.t("app.title"), self.title_frame)
        self.title_lbl.setStyleSheet(self._title_css(theme))
        tf.addWidget(self.title_lbl)
        h.addWidget(self.title_frame)
        h.addStretch()

        self.launch_btn = QPushButton(translate.t("btn.launch"))
        self.launch_btn.setFixedSize(140, 36)
        self.launch_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.launch_btn.setStyleSheet(s_btn_launch())
        self.launch_btn.clicked.connect(self.launch_toggle)
        h.addWidget(self.launch_btn, 0)

        self.settings_btn = QPushButton("SET")
        self.settings_btn.setFixedSize(60, 36)
        self.settings_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.settings_btn.setStyleSheet(s_btn_set())
        self.settings_btn.clicked.connect(self._on_settings_click)

        self.settings_menu = QMenu(self)
        self.settings_menu.setStyleSheet(s_popup_menu())

        self.act_account = QAction(translate.t("btn.account"), self)
        self.act_account.triggered.connect(self.open_account_view)
        self.settings_menu.addAction(self.act_account)

        self.act_menu = QAction(translate.t("btn.menu"), self)
        self.act_menu.triggered.connect(self.toggle_menu)
        self.settings_menu.addAction(self.act_menu)

        h.addWidget(self.settings_btn, 0)
        root.addLayout(h)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(20)
        self.split.setStyleSheet(
            "QSplitter{background:transparent;}"
            "QSplitter::handle{background:transparent;}"
        )
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)

        self.left = QFrame()
        self.left.setMinimumWidth(220)
        self.left.setMaximumWidth(340)
        self.left.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self.left.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.left.setAutoFillBackground(False)
        self.left.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.left.setStyleSheet(
            f"QFrame{{background:{theme.panel_bg(245)};border-radius:12px}}"
        )
        ll = QVBoxLayout(self.left)
        ll.setContentsMargins(14, 12, 14, 12)
        ll.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        lbl_col = QVBoxLayout()
        lbl_col.setSpacing(2)

        self.instances_lbl = QLabel(translate.t("header.instances"))
        self.instances_lbl.setFrameShape(QFrame.Shape.NoFrame)
        self.instances_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.instances_lbl.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.instances_lbl.setStyleSheet(
            f"background:transparent;color:{theme.FG};"
            f"font-size:14pt;font-weight:300;"
            f"font-family:'{theme.UI_FONT}'; letter-spacing: 0.5px;"
        )
        lbl_col.addWidget(self.instances_lbl)

        self.instances_sub = QLabel("")
        self.instances_sub.setFrameShape(QFrame.Shape.NoFrame)
        self.instances_sub.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.instances_sub.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.instances_sub.setStyleSheet(
            f"background:transparent;color:{theme.GRAY};font-size:9pt;"
            f"font-family:'{theme.UI_FONT}'"
        )
        lbl_col.addWidget(self.instances_sub)
        bar.addLayout(lbl_col, 1)

        self.add_btn = QPushButton("+")
        self.add_btn.setToolTip(translate.t("header.instances"))
        self.add_btn.setStyleSheet(s_plus_btn(36))
        self.add_btn.setFixedSize(36, 36)
        self.add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.add_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.add_btn.clicked.connect(self.add_new)
        bar.addWidget(
            self.add_btn, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        )
        ll.addLayout(bar)

        self.plist = QListWidget()
        self.plist.setFont(QFont(theme.UI_FONT, 10))
        self.plist.setSpacing(0)
        self.plist.setFrameShape(QFrame.Shape.NoFrame)
        self.plist.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.plist.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.plist.viewport().setAutoFillBackground(False)
        self.plist.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.plist.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.plist.setIconSize(QSize(20, 20))
        self.plist.setViewportMargins(0, 0, 0, 0)
        self.plist.setContentsMargins(0, 0, 0, 0)
        self.plist.setViewMode(QListWidget.ViewMode.ListMode)
        self.plist.setUniformItemSizes(True)
        self.plist.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.plist.setWordWrap(False)
        self.plist.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.plist.viewport().setContentsMargins(0, 0, 0, 0)
        self.plist.setItemDelegate(_NoTintDelegate(self.plist))
        self.plist.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.plist.setStyleSheet(
            f"QListWidget{{background:transparent;color:{theme.FG};"
            f"padding:0;border:none;}}"
            f"QListWidget::item{{padding:0;padding-left:0;margin:0;"
            f"border:none;border-radius:8px;}}"
        )
        pal = self.plist.palette()
        accent_col = QColor(theme.ACCENT)
        accent_col.setAlpha(60)
        pal.setColor(QPalette.ColorRole.Highlight, accent_col)
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.FG))
        self.plist.setPalette(pal)
        self.plist.viewport().setAutoFillBackground(False)
        self.plist.currentRowChanged.connect(self._on_profile_row_changed)
        self.plist.customContextMenuRequested.connect(self._ctx_menu)
        ll.addWidget(self.plist, 1)

        self.split.addWidget(self.left)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.stack.setStyleSheet("QStackedWidget{background:transparent;}")
        self.stack.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.stack.setAutoFillBackground(False)

        self.inst_view = QWidget()
        self.inst_view.setStyleSheet("QWidget{background:transparent;}")
        self.inst_view.setAutoFillBackground(False)
        self.inst_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        il = QVBoxLayout(self.inst_view)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(0)

        self.card = QFrame()
        self.card.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.card.setAutoFillBackground(False)
        self.card.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.card.setStyleSheet(
            f"QFrame{{background:{theme.panel_bg(235)};border-radius:14px}}"
        )
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(16, 8, 16, 6)
        cl.setSpacing(0)

        self.card_label = QLabel("")
        self.card_label.setFrameShape(QFrame.Shape.NoFrame)
        self.card_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.card_label.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.card_label.setContentsMargins(0, 0, 0, 0)
        self.card_label.setTextFormat(Qt.TextFormat.RichText)
        self.card_label.setStyleSheet("background:transparent;")
        cl.addWidget(self.card_label, 0, Qt.AlignmentFlag.AlignTop)
        il.addWidget(self.card, 0)

        self.console_frame = QFrame()
        self.console_frame.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        self.console_frame.setAutoFillBackground(False)
        self.console_frame.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.console_frame.setStyleSheet(
            f"QFrame{{background:{theme.panel_dim(180)};border-radius:14px}}"
        )
        cfl = QVBoxLayout(self.console_frame)
        cfl.setContentsMargins(16, 8, 16, 8)
        cfl.setSpacing(0)
        self.console = Console()
        self.console.setMinimumHeight(200)
        cfl.addWidget(self.console, 1)
        il.addWidget(self.console_frame, 1)

        self.stack.addWidget(self.inst_view)

        self.menu_view = MenuView(self, self.settings)
        self.menu_view.theme_changed.connect(self._apply_theme_live)
        self.menu_view.setAutoFillBackground(False)
        self.menu_view.back_requested.connect(self._back_from_menu)
        self.stack.addWidget(self.menu_view)

        self.account_view = AccountView(self, self.settings, log=self.console.log)
        self.account_view.setAutoFillBackground(False)
        self.stack.addWidget(self.account_view)

        self.split.addWidget(self.stack)
        self.split.setSizes([260, 920])
        root.addWidget(self.split, 1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addStretch(1)

        self.lang_frame = QFrame()
        self.lang_frame.setObjectName("langFrame")
        self.lang_frame.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.lang_frame.setAutoFillBackground(False)
        self.lang_frame.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lang_frame.setStyleSheet(
            f"QFrame#langFrame{{background:{theme.panel_glass(210)};border-radius:0px}}"
        )
        lf = QHBoxLayout(self.lang_frame)
        lf.setContentsMargins(2, 2, 2, 2)
        lf.setSpacing(0)

        self.lang_box = QComboBox()
        self.lang_box.setFrame(False)
        self.lang_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lang_box.setStyleSheet(
            f"QComboBox{{background:transparent;color:{theme.FG};"
            f"padding:4px 20px 4px 10px;"
            f"font-family:'{theme.UI_FONT}';font-size:9pt;"
            f"min-width:110px}}"
            f"QComboBox::drop-down{{width:18px;"
            f"background:transparent}}"
            f"QComboBox::down-arrow{{image:none;width:0;height:0;}}" + s_combo_popup()
        )
        self._populate_languages()
        self.lang_box.currentIndexChanged.connect(self._on_lang_changed)
        lf.addWidget(self.lang_box)
        bottom.addWidget(self.lang_frame, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(bottom)

        self._install_particles()

        if self._bg:
            self._bg.set_mask_widget(self.left)

        for _lbl in self.findChildren(QLabel):
            _lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            _lbl.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        for _btn in self.findChildren(QPushButton):
            _btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for _cb in self.findChildren(QComboBox):
            _cb.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _back_from_menu(self):
        if self.stack.currentIndex() in (1, 2):
            self.stack.setCurrentIndex(0)
            self._reset_header()
            slide_widget_h(self.left, True)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.stack.currentIndex() in (1, 2):
            self._back_from_menu()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_settings_click(self):
        if self.stack.currentIndex() in (1, 2):
            self._back_from_menu()
        else:
            self.settings_menu.exec(
                self.settings_btn.mapToGlobal(self.settings_btn.rect().bottomLeft())
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_bg()

    def _populate_languages(self):
        self.lang_box.blockSignals(True)
        self.lang_box.clear()
        current = translate.get_language()
        for code, name in translate.available_languages():
            self.lang_box.addItem(name, code)
        idx = self.lang_box.findData(current)
        if idx >= 0:
            self.lang_box.setCurrentIndex(idx)
        self.lang_box.blockSignals(False)

    def _on_lang_changed(self, _idx):
        code = self.lang_box.currentData()
        if not code or code == translate.get_language():
            return
        translate.set_language(code)
        self.settings.set_language(code)
        self.retranslate_ui()

    def retranslate_ui(self):
        self.setWindowTitle(translate.t("app.title"))
        self.title_lbl.setText(translate.t("app.title"))
        self.act_account.setText(translate.t("btn.account"))
        self.act_menu.setText(translate.t("btn.menu"))
        self.instances_lbl.setText(translate.t("header.instances"))
        self.add_btn.setToolTip(translate.t("header.instances"))
        if self._process is None:
            self.launch_btn.setText(translate.t("btn.launch"))
        else:
            self.launch_btn.setText(translate.t("btn.stop"))
        self._update_card()
        if hasattr(self.menu_view, "retranslate_ui"):
            self.menu_view.retranslate_ui()
        if hasattr(self.account_view, "retranslate_ui"):
            self.account_view.retranslate_ui()
        name = translate.language_display_name(translate.get_language())
        self.console.log("ok", translate.t("console.language_changed", name=name))

    def toggle_menu(self):
        if self.stack.currentIndex() == 1:
            self._back_from_menu()
        else:
            self.stack.setCurrentIndex(1)
            self._set_back_mode("Menu")
            slide_widget_h(self.left, False)
            self.menu_view.setFocus()

    def open_account_view(self):
        if self.stack.currentIndex() == 2:
            self._back_from_menu()
        else:
            self.stack.setCurrentIndex(2)
            self.account_view.refresh()
            self._set_back_mode("Account")
            slide_widget_h(self.left, False)
            self.account_view.setFocus()

    def _set_back_mode(self, source):
        self.settings_btn.setText("BACK")
        self.settings_btn.setStyleSheet(s_btn_set())

    def _reset_header(self):
        self.settings_btn.setText("SET")
        self.settings_btn.setStyleSheet(s_btn_set())

    def _apply_theme_live(self, theme_name, accent_name):
        from core import theme as _theme

        _theme.apply(theme_name)
        _theme.apply_accent(accent_name)

        app = QApplication.instance()
        pal = app.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(_theme.BG))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(_theme.FG))
        pal.setColor(QPalette.ColorRole.Base, QColor(_theme.BG2))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(_theme.BG3))
        pal.setColor(QPalette.ColorRole.Text, QColor(_theme.FG))
        pal.setColor(QPalette.ColorRole.Button, QColor(_theme.BG3))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(_theme.FG))
        pal.setColor(QPalette.ColorRole.Highlight, QColor(_theme.ACCENT))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(_theme.accent_text()))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(_theme.BG2))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor(_theme.FG))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(_theme.GRAY))
        app.setPalette(pal)

        app.setStyleSheet(
            f"QToolTip{{background:{_theme.BG2};color:{_theme.FG};"
            f"border-radius:6px;padding:6px}}"
            f"QScrollBar:vertical{{background:transparent;width:10px;margin:0}}"
            f"QScrollBar:horizontal{{background:transparent;height:10px;margin:0}}"
            f"QScrollBar::handle:vertical{{background:{_theme.BG3};"
            f"min-height:24px;border-radius:5px}}"
            f"QScrollBar::handle:horizontal{{background:{_theme.BG3};"
            f"min-width:24px;border-radius:5px}}"
            f"QScrollBar::handle:hover{{background:{_theme.BORDER}}}"
            f"QScrollBar::add-line,QScrollBar::sub-line{{width:0;height:0;"
            f"background:transparent}}"
            f"QScrollBar::add-page,QScrollBar::sub-page{{background:transparent}}"
            f"QComboBox QAbstractItemView{{background:{_theme.popup_bg()};"
            f"color:{_theme.popup_fg()};"
            f"selection-background-color:{_theme.popup_hover()};"
            f"selection-color:{_theme.popup_fg()};"
            f"border:none;outline:none;padding:4px;}}"
            f"QComboBox QAbstractItemView::item{{padding:6px 10px;"
            f"color:{_theme.popup_fg()};}}"
            f"QComboBox QAbstractItemView::item:selected{{"
            f"background:{_theme.popup_hover()};"
            f"color:{_theme.popup_fg()};}}"
            f"QMenu{{background:{_theme.popup_bg()};color:{_theme.popup_fg()};"
            f"border:none;border-radius:0px;padding:6px}}"
            f"QMenu::item{{padding:6px 20px 6px 12px;border-radius:0px;"
            f"color:{_theme.popup_fg()};}}"
            f"QMenu::item:selected{{background:{_theme.popup_hover()};"
            f"color:{_theme.popup_fg()};}}"
            f"QStackedWidget{{background:transparent}}"
            f"QStackedWidget::pane{{background:transparent}}"
            f"* {{ outline: none; }}"
            f"*:focus {{ outline: none; }}"
        )

        self.setStyleSheet(f"QMainWindow{{background:{_theme.BG};color:{_theme.FG};}}")

        self.title_lbl.setStyleSheet(self._title_css(_theme))

        self.left.setStyleSheet(
            f"QFrame{{background:{_theme.panel_bg(245)};border-radius:12px}}"
        )
        self.instances_lbl.setStyleSheet(
            f"background:transparent;color:{_theme.FG};"
            f"font-size:14pt;font-weight:300;"
            f"font-family:'{theme.UI_FONT}'; letter-spacing: 0.5px;"
        )
        self.instances_sub.setStyleSheet(
            f"background:transparent;color:{_theme.GRAY};"
            f"font-size:9pt;font-family:'{theme.UI_FONT}'"
        )
        self.plist.setStyleSheet(
            f"QListWidget{{background:transparent;color:{_theme.FG};"
            f"padding:0;border:none;}}"
            f"QListWidget::item{{padding:0;padding-left:0;margin:0;"
            f"border:none;border-radius:8px;}}"
        )
        self.plist.viewport().setContentsMargins(0, 0, 0, 0)
        pal = self.plist.palette()
        accent_col = QColor(_theme.ACCENT)
        accent_col.setAlpha(60)
        pal.setColor(QPalette.ColorRole.Highlight, accent_col)
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(_theme.FG))
        self.plist.setPalette(pal)

        self.add_btn.setStyleSheet(s_plus_btn(36))
        self.add_btn.setFixedSize(36, 36)
        self.lang_frame.setStyleSheet(
            f"QFrame#langFrame{{background:{_theme.panel_glass(210)};"
            f"border-radius:0px}}"
        )
        self.lang_box.setStyleSheet(
            f"QComboBox{{background:transparent;color:{_theme.FG};"
            f"padding:4px 20px 4px 10px;"
            f"font-family:'{theme.UI_FONT}';font-size:9pt;"
            f"min-width:110px}}"
            f"QComboBox::drop-down{{width:18px;"
            f"background:transparent}}"
            f"QComboBox::down-arrow{{image:none;width:0;height:0;}}" + s_combo_popup()
        )

        self.inst_view.setStyleSheet("QWidget{background:transparent;}")
        self.card.setStyleSheet(
            f"QFrame{{background:{_theme.panel_bg(235)};border-radius:14px}}"
        )
        self.console_frame.setStyleSheet(
            f"QFrame{{background:{_theme.panel_dim(180)};border-radius:14px}}"
        )
        if hasattr(self.console, "restyle"):
            self.console.restyle()

        self._update_card()

        self.settings_btn.setStyleSheet(s_btn_set())
        self.settings_menu.setStyleSheet(s_popup_menu())

        if self._process is None:
            self.launch_btn.setStyleSheet(s_btn_launch())
        else:
            self.launch_btn.setStyleSheet(s_btn_stop())

        self.menu_view.tabs.setStyleSheet(s_tabs())
        if hasattr(self.menu_view, "restyle"):
            self.menu_view.restyle()
        if hasattr(self.account_view, "restyle"):
            self.account_view.restyle()

        for _lbl in self.findChildren(QLabel):
            _lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            _lbl.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        for _btn in self.findChildren(QPushButton):
            _btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for _cb in self.findChildren(QComboBox):
            _cb.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        if theme_name == "light":
            self.console.log(
                "ok",
                translate.t(
                    "console.theme_applied", theme=translate.t("menu.theme_light")
                ),
            )
        else:
            self.console.log(
                "ok",
                translate.t(
                    "console.theme_applied", theme=translate.t("menu.theme_dark")
                ),
            )
        self.console.log(
            "ok",
            translate.t(
                "console.accent_applied",
                accent=translate.t(f"menu.accent_{accent_name.lower()}"),
            ),
        )

        with contextlib.suppress(Exception):
            self.refresh_particles_accent()

        for child in self.findChildren(QDialog):
            if child.isVisible() and hasattr(child, "refresh_particles_accent"):
                with contextlib.suppress(Exception):
                    child.refresh_particles_accent()

    def _track(self, w):
        self._workers.append(w)
        w.finished.connect(
            lambda: self._workers.remove(w) if w in self._workers else None
        )

    def _startup(self):
        hw = hardware.get()
        self.console.log(
            "sys", f"Platform {platform.system()} Python {platform.python_version()}"
        )
        self.console.log(
            "sys",
            translate.t(
                "console.startup_hardware",
                tier=hw.tier_label(),
                ram=hardware._fmt_num(hw.ram_gb),
                cpus=hw.cpus,
                disk=hardware._fmt_num(hw.free_disk_gb),
            ),
        )
        gpu = detect_gpu()
        self.console.log("sys", f"GPU {hardware.gpu_label(gpu)}")
        self.console.log("sys", f"Minecraft root {MC_ROOT}")
        self.load_profiles()
        self.fetch_manifest()
        self._warm_modrinth()
        fetch_all_loaders(self._apply_loader_icon)
        self._schedule_auto_check()

    def _schedule_auto_check(self):
        try:
            interval = int(self.settings.get("auto_check_interval", 86400))
        except (TypeError, ValueError):
            interval = 86400
        if interval <= 0:
            self._auto_check_timer.stop()
            return
        try:
            last = float(self.settings.get("auto_check_last_run", 0))
        except (TypeError, ValueError):
            last = 0.0
        elapsed = time.time() - last if last > 0 else interval
        delay = max(30, int(interval - elapsed))
        self._auto_check_timer.start(delay * 1000)

    def _run_auto_check(self):
        with contextlib.suppress(Exception):
            self.settings.set("auto_check_last_run", time.time())
            self.settings.save()
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
                jars = [
                    f
                    for f in mods_dir.iterdir()
                    if f.is_file() and f.suffix.lower() == ".jar"
                ]
                if not jars:
                    continue
                mv = prof.version
                ld = (prof.loader or "vanilla").lower()
                paths = [str(j) for j in jars]

                def task(
                    log,
                    progress,
                    progress_end,
                    paths_=paths,
                    mv_=mv,
                    ld_=ld,
                    prof_=prof,
                ):
                    from integration import modrinth

                    result = modrinth.resolve_mods_parallel(
                        paths_, mv_, "mod", ld_, workers=3
                    )
                    try:
                        meta = getattr(prof_, "mods_meta", {}) or {}
                        meta.update(result)
                        prof_.mods_meta = meta
                        prof_.save()
                    except Exception:  # noqa: BLE001, S110
                        pass
                    return prof_, result

                w = Worker(task)
                w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
                w.done.connect(
                    self._on_auto_check_done, Qt.ConnectionType.QueuedConnection
                )
                self._track(w)
                w.start()
            except Exception as e:  # noqa: BLE001
                self.console.log("warn", str(e))
        self._schedule_auto_check()

    def _on_auto_check_done(self, payload):
        if not payload:
            return
        prof, result = payload
        hits = sum(1 for r in (result or {}).values() if r.get("project_id"))
        total = len(result or {})
        self.console.log(
            "ok",
            translate.t(
                "console.auto_check_done", hits=hits, total=total, name=prof.name
            ),
        )

    def _warm_modrinth(self):
        if not hasattr(self, "_warm_nam"):
            self._warm_nam = QNetworkAccessManager(self)
        req = QNetworkRequest(QUrl("https://api.modrinth.com/"))
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        req.setRawHeader(b"User-Agent", b"Xeria-Launcher/2.504")
        self._warm_nam.get(req)

    def load_profiles(self):
        versions_dir = MC_ROOT / "versions"

        if versions_dir.exists():
            installed_labymods = set()
            for d in versions_dir.iterdir():
                if d.is_dir() and "labymod" in d.name.lower():
                    parts = d.name.split("-")
                    if len(parts) >= 3:
                        installed_labymods.add(parts[-2])

            for v_base in installed_labymods:
                vanilla_json = PROFILES_DIR / f"{v_base}.json"
                if vanilla_json.exists():
                    with contextlib.suppress(Exception):
                        vanilla_json.unlink()

                for f in PROFILES_DIR.glob("LabyMod*.json"):
                    with contextlib.suppress(Exception):
                        f.unlink()

        self.plist.blockSignals(True)
        self.plist.clear()
        self.plist.setSpacing(self.ROW_GAP)

        self.plist.setStyleSheet(
            f"QListWidget{{background:transparent;color:{theme.FG};"
            f"padding:0;border:none;}}"
            f"QListWidget::item{{padding:0px;margin:0px;border:none;}}"
        )

        self._row_map = []
        self._row_widgets = {}

        self.profiles = Profile.load_all()
        existing_names = {p.name for p in self.profiles}

        parents = set()
        if versions_dir.exists():
            for v_dir in versions_dir.iterdir():
                if not v_dir.is_dir():
                    continue
                jp = v_dir / f"{v_dir.name}.json"
                if not jp.exists():
                    continue
                try:
                    with open(jp, "r", encoding="utf-8") as f:
                        d = json.load(f)
                except Exception:  # noqa: BLE001, S112
                    continue
                inh = d.get("inheritsFrom")
                if inh:
                    parents.add(inh)

        if versions_dir.exists():
            installed_labymods = set()
            for d in versions_dir.iterdir():
                if d.is_dir() and "labymod" in d.name.lower():
                    parts = d.name.split("-")
                    if len(parts) >= 3:
                        installed_labymods.add(parts[-2])

            for v_dir in versions_dir.iterdir():
                if not v_dir.is_dir():
                    continue

                name_lower = v_dir.name.lower()

                if (
                    "fabric" in name_lower
                    or "quilt" in name_lower
                    or "forge" in name_lower
                ):
                    continue

                if v_dir.name in parents:
                    continue

                if v_dir.name in installed_labymods and "labymod" not in name_lower:
                    continue

                if v_dir.name in existing_names:
                    continue

                json_path = v_dir / f"{v_dir.name}.json"
                if not json_path.exists():
                    continue

                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        v_data = json.load(f)
                except Exception:  # noqa: BLE001, S112
                    continue

                p = Profile(v_dir.name)
                p.version = v_data.get("inheritsFrom", v_dir.name)
                p.loader = "vanilla"
                p.ram = "4"
                p._external_dir = v_dir

                if "labymod" in name_lower:
                    p.name = "LabyMod"
                    p.version = v_data.get("inheritsFrom", v_dir.name)

                self.profiles.append(p)

        for p in self.profiles:
            it = QListWidgetItem()
            it.setSizeHint(QSize(0, self.ROW_HEIGHT))

            loader = (p.loader or "vanilla").lower()
            icon = loader_icon_sync(loader)
            if not icon:
                icon = QIcon.fromTheme("applications-games")

            folder_name = p._external_dir.name if p._external_dir else p.version
            row = _InstanceRow(p.name, p.version, folder_name, icon)

            self.plist.addItem(it)
            self.plist.setItemWidget(it, row)
            self._row_map.append(p)
            self._row_widgets[p.name] = row

        self.plist.blockSignals(False)

        for p in self.profiles:
            loader = (p.loader or "vanilla").lower()
            if loader_icon_sync(loader) is None:
                fetch_loader_icon(loader, self._apply_loader_icon)

        if self.profiles:
            self.plist.setCurrentRow(0)
        else:
            self.current_profile = None
            self._update_card()

    def _apply_loader_icon(self, loader_name, icon):
        for p in self.profiles:
            if (p.loader or "vanilla").lower() == loader_name:
                row = self._row_widgets.get(p.name)
                if row:
                    row.set_icon(icon)

    def _on_profile_row_changed(self, row):
        if row < 0 or row >= len(self._row_map):
            self.current_profile = None
            self._update_card()
            self._set_launch_state(
                self._running_profile is not None, self._running_profile
            )
            return
        self.current_profile = self._row_map[row]
        self._update_card()
        self._set_launch_state(self._running_profile is not None, self._running_profile)

    def _update_card(self):
        p = self.current_profile
        if p is None:
            self.card_label.setText(
                f'<span style="color:{theme.FG};font-size:14pt;'
                f"font-family:'{theme.UI_FONT}';font-weight:300\">"
                f"{translate.t('card.no_instance')}</span>"
                f"<br>"
                f'<span style="color:{theme.GRAY};font-size:9pt;'
                f"font-family:'{theme.UI_FONT}';\">"
                f"{translate.t('card.create_hint')}</span>"
            )
            return
        loader_label = translate.t(f"loader.{(p.loader or 'vanilla').lower()}")
        self.card_label.setText(
            f'<span style="color:{theme.FG};font-size:14pt;'
            f"font-family:'{theme.UI_FONT}';font-weight:300\">"
            f"{p.name}</span>"
            f"<br>"
            f'<span style="color:{theme.GRAY};font-size:9pt;'
            f"font-family:'{theme.UI_FONT}';\">"
            f"{loader_label} {p.version}</span>"
        )

    def add_new(self):
        ch = ChooseInstallDialog(self)
        if ch.exec() != QDialog.DialogCode.Accepted or not ch.choice:
            return

        if ch.choice == "blank":
            self._add_blank_profile()
        elif ch.choice == "local":
            self._add_local_modpack()
        elif ch.choice == "modrinth":
            self._add_modrinth_modpack()
        elif ch.choice == "migrate":
            self._migrate_from_existing()
        elif ch.choice == "preset":
            self._add_preset_profile(ch.preset_choice)
        elif ch.choice == "jar":
            self._add_jar_profile(ch.jar_path)

    def _add_preset_profile(self, preset):
        if preset == "labymod":
            import urllib.request

            cache_dir = XERIA_ROOT / "cache" / "downloads"
            cache_dir.mkdir(parents=True, exist_ok=True)
            installer_path = cache_dir / "labymod4-installer.jar"

            if not installer_path.exists():
                self.console.log(
                    "info", "Downloading LabyMod 4 Installer from official servers..."
                )
                url = "https://releases.labymod.net/api/v1/installer/production/java"

                def task(log, progress, progress_end):
                    try:
                        req = urllib.request.Request(
                            url, headers={"User-Agent": "Xeria-Launcher/2.504"}
                        )
                        with urllib.request.urlopen(req, timeout=60) as response:
                            total = int(response.headers.get("content-length", 0))
                            done = 0
                            with open(installer_path, "wb") as f:
                                while True:
                                    chunk = response.read(8192)
                                    if not chunk:
                                        break
                                    f.write(chunk)
                                    done += len(chunk)
                                    if total:
                                        progress("Downloading", done, total, "", "")
                        progress_end()
                        return True
                    except Exception as e:  # noqa: BLE001
                        log("error", f"Download failed: {e}")
                        return False

                w = Worker(task)
                w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
                w.progress.connect(
                    lambda *a: self.console.log("progress", a),
                    Qt.ConnectionType.QueuedConnection,
                )
                w.progress_end.connect(
                    lambda: self.console.log("progress_end", None),
                    Qt.ConnectionType.QueuedConnection,
                )
                w.done.connect(
                    lambda success: self._on_labymod_downloaded(
                        success, installer_path
                    ),
                    Qt.ConnectionType.QueuedConnection,
                )
                self._track(w)
                w.start()
            else:
                self._on_labymod_downloaded(True, installer_path)

    def _on_labymod_downloaded(self, success, path):
        if success:
            self.console.log("ok", f"LabyMod Installer ready at: {path}")
            self._add_jar_profile(str(path))
        else:
            self.console.log("error", "Failed to download LabyMod Installer.")

    def _add_jar_profile(self, jar_path):
        if not Path(jar_path).exists():
            QMessageBox.warning(self, "Error", "File not found.")
            return

        self.console.log("info", f"Launching installer GUI: {jar_path}")

        try:
            java_exe = best_java("26.3", log=self.console.log) or "java"

            env = os.environ.copy()
            if platform.system() == "Linux":
                st = os.environ.get("XDG_SESSION_TYPE", "").lower()
                wl = bool(os.environ.get("WAYLAND_DISPLAY")) or st == "wayland"
                if wl:
                    env["GDK_BACKEND"] = "x11"
                    env["_JAVA_AWT_WM_NONREPARENTING"] = "1"
                    self.console.log(
                        "sys",
                        "Wayland detected. Forcing installer to use X11 (XWayland).",
                    )

            cmd = [java_exe, "-jar", jar_path, "--installClient", str(MC_ROOT)]
            self.console.log("sys", " ".join(cmd))

            subprocess.Popen(
                cmd, cwd=str(Path(jar_path).parent), start_new_session=True, env=env
            )

            self._start_install_watcher()

        except Exception as e:  # noqa: BLE001
            self.console.log("error", f"Failed to launch installer: {e}")

    def _start_install_watcher(self):
        def get_snapshot():
            snap = set()
            if PROFILES_DIR.exists():
                snap.update(
                    f"xeria:{f.name}" for f in PROFILES_DIR.iterdir() if f.is_dir()
                )
            if MC_ROOT.exists():
                v_dir = MC_ROOT / "versions"
                if v_dir.exists():
                    snap.update(f"mc:{f.name}" for f in v_dir.iterdir() if f.is_dir())
            return snap

        initial_snap = get_snapshot()
        attempts = [0]

        def check():
            attempts[0] += 1
            current_snap = get_snapshot()

            if current_snap != initial_snap:
                self.console.log("ok", "New instance detected! Refreshing list...")
                self.load_profiles()
                return

            if attempts[0] < 120:
                QTimer.singleShot(1000, check)
            else:
                self.console.log("sys", "Install watcher timed out (2 mins).")

        QTimer.singleShot(1000, check)

    def _migrate_from_existing(self):
        from ui.migrate_dialogs import MigrateDialog

        if not self.profiles:
            QMessageBox.information(
                self, translate.t("migrate.title"), translate.t("migrate.warn_empty")
            )
            return
        if not self.releases:
            try:
                d = http.get(MANIFEST_URL).json()
                self.manifest = d
                self.releases = [v for v in d["versions"] if v["type"] == "release"]
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(
                    self,
                    translate.t("migrate.title"),
                    translate.t("migrate.warn_no_releases") + f"\n\n{e}",
                )
                return
        if not self.releases:
            QMessageBox.critical(
                self,
                translate.t("migrate.title"),
                translate.t("migrate.warn_no_releases"),
            )
            return
        dlg = MigrateDialog(self, self.profiles, self.releases, self.settings)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.result_profile is not None:
            self.console.log(
                "ok",
                translate.t("console.created_profile", name=dlg.result_profile.name),
            )
            self.load_profiles()

    def _add_blank_profile(self, forced_loader=None):
        if not self.releases:
            try:
                d = http.get(MANIFEST_URL).json()
                self.manifest = d
                self.releases = [v for v in d["versions"] if v["type"] == "release"]
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, translate.t("dialog.profile_new"), str(e))
                return
        dlg = ProfileDialog(self, self.releases, self.settings)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, ver, ram, loader = dlg.values()
        if forced_loader:
            loader = forced_loader
            if not name:
                name = f"{forced_loader.capitalize()} {ver}"

        if not name:
            QMessageBox.warning(
                self,
                translate.t("dialog.profile_new"),
                translate.t("dialog.name_required"),
            )
            return
        if any(c in name for c in r'/\:*?"<>|'):
            QMessageBox.warning(
                self,
                translate.t("dialog.profile_new"),
                translate.t("dialog.invalid_chars"),
            )
            return
        if (PROFILES_DIR / f"{name}.json").exists():
            QMessageBox.warning(
                self,
                translate.t("dialog.exists"),
                translate.t("dialog.exists_msg", name=name),
            )
            return
        p = Profile(name)
        p.version = ver
        p.ram = ram
        p.loader = loader
        dlg.apply(p)
        _ = p.dir
        p.save()
        self.console.log("ok", translate.t("console.created_profile", name=name))
        self.load_profiles()

    def _add_local_modpack(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            translate.t("dialog.local"),
            str(Path.home()),
            "Modpacks (*.xerpack *.zip *.mrpack);;All files (*)",
        )
        if not path:
            return
        w = Worker(self._install_local_modpack_task, path)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection,
        )
        w.done.connect(self._modpack_done, Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _install_local_modpack_task(self, path, log, progress, progress_end):
        return modpack.install(
            path, log=log, progress=progress, progress_end=progress_end
        )

    def _add_modrinth_modpack(self):
        dlg = ModpackSearchDialog(self, self.console.log)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result:
            return
        hit = dlg.result
        preferred_mc = dlg.selected_version() or None
        forced_loader = dlg.selected_loader() or "pack"
        if forced_loader == "pack":
            forced_loader = None
        w = Worker(self._download_and_install_modpack, hit, preferred_mc, forced_loader)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection,
        )
        w.done.connect(self._modpack_done, Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _download_and_install_modpack(
        self, hit, preferred_mc, forced_loader, log, progress, progress_end
    ):
        from integration import modrinth

        picked = modrinth.pick_modpack_file(hit["id"])
        if not picked:
            log("error", translate.t("console.no_compatible"))
            return None
        url, filename, ver = picked
        log("ok", f"{ver}: {filename}")
        import tempfile

        tmp = Path(tempfile.gettempdir()) / filename
        try:
            with http.stream("GET", url) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                done = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(65536):
                        f.write(chunk)
                        done += len(chunk)
                        if total and progress:
                            progress(filename, done, total, "", "")
            if progress_end:
                progress_end()
        except Exception as e:  # noqa: BLE001
            log("error", str(e))
            return None
        name = modpack.install(
            str(tmp),
            log=log,
            progress=progress,
            progress_end=progress_end,
            force_mc_version=preferred_mc,
            force_loader=forced_loader,
        )
        with contextlib.suppress(Exception):
            tmp.unlink()
        return name

    def _modpack_done(self, name):
        if name:
            self.console.log("ok", translate.t("console.modpack_installed", name=name))
            self.load_profiles()
        else:
            self.console.log("error", translate.t("console.modpack_failed"))

    def edit_profile(self):
        if not self.current_profile:
            return
        p = self.current_profile
        dlg = ProfileDialog(self, self.releases, self.settings, profile=p)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, ver, ram, loader = dlg.values()
        if not name:
            QMessageBox.warning(
                self,
                translate.t("dialog.profile_edit", name=p.name),
                translate.t("dialog.name_required"),
            )
            return
        old = p.name
        if name != old:
            if any(c in name for c in r'/\:*?"<>|'):
                QMessageBox.warning(
                    self,
                    translate.t("dialog.profile_edit", name=p.name),
                    translate.t("dialog.invalid_chars"),
                )
                return
            if (PROFILES_DIR / f"{name}.json").exists():
                QMessageBox.warning(
                    self,
                    translate.t("dialog.exists"),
                    translate.t("dialog.exists_msg", name=name),
                )
                return
            (PROFILES_DIR / f"{old}.json").rename(PROFILES_DIR / f"{name}.json")
            if (PROFILES_DIR / old).exists():
                (PROFILES_DIR / old).rename(PROFILES_DIR / name)
            p.name = name
        p.version = ver
        p.ram = ram
        p.loader = loader
        dlg.apply(p)
        p.save()
        self.load_profiles()

    def rename_profile(self):
        if not self.current_profile:
            return
        old = self.current_profile.name
        new, ok = QInputDialog.getText(
            self, translate.t("menu.rename"), "Name:", text=old
        )
        if not ok or not new.strip():
            return
        new = new.strip()
        if new == old:
            return
        if any(c in new for c in r'/\:*?"<>|'):
            QMessageBox.warning(
                self, translate.t("menu.rename"), translate.t("dialog.invalid_chars")
            )
            return
        if (PROFILES_DIR / f"{new}.json").exists():
            QMessageBox.warning(
                self,
                translate.t("dialog.exists"),
                translate.t("dialog.exists_msg", name=new),
            )
            return
        (PROFILES_DIR / f"{old}.json").rename(PROFILES_DIR / f"{new}.json")
        (PROFILES_DIR / old).rename(PROFILES_DIR / new)
        self.load_profiles()

    def duplicate_profile(self):
        if not self.current_profile:
            return
        src = self.current_profile
        new_name = f"{src.name} (copy)"
        n = 1
        while (PROFILES_DIR / f"{new_name}.json").exists():
            new_name = f"{src.name} (copy {n})"
            n += 1
        p = Profile(new_name)
        p.version = src.version
        p.ram = src.ram
        p.loader = src.loader
        p.loader_version = getattr(src, "loader_version", "")
        p.override_gc = src.override_gc
        p.override_jvm_flags = src.override_jvm_flags
        p.override_env_vars = src.override_env_vars
        p.override_java_path = src.override_java_path
        p.override_wrapper = src.override_wrapper
        p.mods_meta = dict(getattr(src, "mods_meta", {}) or {})
        _ = p.dir
        p.save()
        with contextlib.suppress(Exception):
            if src.dir.exists():
                shutil.copytree(str(src.dir), str(p.dir), dirs_exist_ok=True)
        self.load_profiles()

    def delete_profile(self):
        if not self.current_profile:
            return
        if (
            QMessageBox.question(
                self,
                translate.t("dialog.delete_title"),
                translate.t("dialog.delete_confirm", name=self.current_profile.name),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        n = self.current_profile.name
        p = self.current_profile

        if getattr(p, "_external_dir", None) is not None:
            try:
                shutil.rmtree(str(p._external_dir))
                self.console.log("warn", f"Deleted external folder: {p._external_dir}")
            except Exception as e:  # noqa: BLE001
                self.console.log("error", f"Failed to delete external folder: {e}")

        Profile.delete(n)
        self.console.log("warn", translate.t("console.deleted_profile", name=n))
        self.current_profile = None
        self.load_profiles()

    def open_folder(self):
        if not self.current_profile:
            return
        p = str(self.current_profile.dir)
        try:
            if IS_WIN:
                os.startfile(p)
            elif IS_MAC:
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
        except Exception as e:  # noqa: BLE001
            self.console.log("error", translate.t("console.open_folder_failed", err=e))

    def export_mrpack(self):
        if not self.current_profile:
            return
        p = self.current_profile
        default_name = f"{p.name}.mrpack"
        path, _ = QFileDialog.getSaveFileName(
            self,
            translate.t("menu.export_modrinth"),
            str(Path.home() / default_name),
            "Modrinth pack (*.mrpack);;Zip (*.zip)",
        )
        if not path:
            return
        self.console.log("info", translate.t("console.exporting", name=p.name))
        w = Worker(self._export_task, p, path)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection,
        )
        self._track(w)
        w.start()

    def _export_task(self, profile, path, log, progress, progress_end):
        return modpack.export_mrpack(
            profile, path, log=log, progress=progress, progress_end=progress_end
        )

    def export_xeriapack(self):
        if not self.current_profile:
            return
        p = self.current_profile
        path, _ = QFileDialog.getSaveFileName(
            self,
            translate.t("menu.export_xeria"),
            str(Path.home() / f"{p.name}.xeriapack"),
            "Xeria pack (*.xeriapack);;Zip (*.zip)",
        )
        if not path:
            return
        self.console.log("info", translate.t("console.exporting", name=p.name))
        w = Worker(self._export_xeria_task, p, path)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.done.connect(lambda _r: None, Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _export_xeria_task(self, profile, path, log, progress, progress_end):
        dest = Path(path)
        game_dir = profile.dir
        items = []
        for f in game_dir.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(game_dir)
            if rel.parts and rel.parts[0] in (".cache", "logs", "crash-reports"):
                continue
            items.append((f, str(rel)))
        total = max(1, len(items))
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("profile.json", profile.json_path.read_text(encoding="utf-8"))
            for i, (src, arc) in enumerate(items, 1):
                z.write(str(src), arc)
                if progress and i % 20 == 0:
                    progress("backup", i, total, "", "")
        if progress_end:
            progress_end()
        log("ok", translate.t("console.exporting", name=dest.name))
        return str(dest)

    def import_instance(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            translate.t("menu.import_instance"),
            str(Path.home()),
            "Xeria pack (*.xeriapack *.zip *.mrpack);;All files (*)",
        )
        if not path:
            return
        if path.lower().endswith(".mrpack"):
            w = Worker(self._install_local_modpack_task, path)
            w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
            w.progress.connect(
                lambda *a: self.console.log("progress", a),
                Qt.ConnectionType.QueuedConnection,
            )
            w.progress_end.connect(
                lambda: self.console.log("progress_end", None),
                Qt.ConnectionType.QueuedConnection,
            )
            w.done.connect(self._modpack_done, Qt.ConnectionType.QueuedConnection)
            self._track(w)
            w.start()
            return
        self.console.log("info", translate.t("console.importing", name=Path(path).name))

        def task(log, progress, progress_end):
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if "profile.json" not in names:
                    log("error", translate.t("console.import_no_json"))
                    return None
                data = json.loads(z.read("profile.json"))
                base = data.get("name") or Path(path).stem
                name = base
                n = 1
                while (PROFILES_DIR / f"{name}.json").exists():
                    name = f"{base} ({n})"
                    n += 1
                target_dir = PROFILES_DIR / name
                target_dir.mkdir(parents=True, exist_ok=True)
                total = max(1, len(names))
                for i, member in enumerate(names, 1):
                    if member == "profile.json":
                        continue
                    if member.endswith("/"):
                        (target_dir / member).mkdir(parents=True, exist_ok=True)
                        continue
                    out = target_dir / member
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    if progress and i % 20 == 0:
                        progress("import", i, total, "", "")
                (PROFILES_DIR / f"{name}.json").write_text(json.dumps(data, indent=2))
                if progress_end:
                    progress_end()
                log("ok", translate.t("console.imported", name=name))
                return name

        w = Worker(task)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection,
        )
        w.done.connect(
            lambda _: self.load_profiles(), Qt.ConnectionType.QueuedConnection
        )
        self._track(w)
        w.start()

    def backup_instance(self):
        if not self.current_profile:
            return
        import datetime

        p = self.current_profile
        backups = XERIA_ROOT / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        dest = backups / f"{p.name}-{ts}.zip"
        self.console.log("info", translate.t("console.backup", name=dest.name))

        def task(log, progress, progress_end):
            files = []
            game_dir = p.dir
            for sub in ("mods", "resourcepacks", "shaderpacks", "config", "saves"):
                d = game_dir / sub
                if not d.exists():
                    continue
                for f in d.rglob("*"):
                    if f.is_file():
                        files.append((f, str(f.relative_to(game_dir))))
            total = max(1, len(files))
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
                for i, (src, arc) in enumerate(files, 1):
                    z.write(src, arc)
                    if progress and i % 20 == 0:
                        progress("backup", i, total, "", "")
            if progress_end:
                progress_end()
            log(
                "ok", translate.t("console.backup_done", kb=dest.stat().st_size // 1024)
            )

        w = Worker(task)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection,
        )
        self._track(w)
        w.start()

    def copy_launch_command(self):
        if not self.current_profile:
            return
        p = self.current_profile
        try:
            from core.jvm import default_jvm_flags as _djf

            java_override = p.override_java_path or self.settings.get("java_path", "")
            java = best_java(p.version, log=None, override=java_override) or "java"
            gc = p.override_gc or self.settings.get("gc", "G1GC")
            combined = (
                (self.settings.get("default_jvm_flags", "") or "")
                + " "
                + (p.override_jvm_flags or "")
            ).strip()
            user_flags = shlex.split(combined) if combined else []
            jvm = user_flags if user_flags else _djf(p.ram, gc)
            cmd = (
                [java]
                + jvm
                + [
                    "-cp",
                    "<classpath>",
                    "net.minecraft.client.main.Main",
                    "--username",
                    self._get_username(),
                    "--version",
                    p.version,
                    "--gameDir",
                    str(p.dir),
                    "--assetsDir",
                    str(MC_ROOT / "assets"),
                    "--assetIndex",
                    "legacy",
                    "--uuid",
                    self._uuid(self._get_username()),
                    "--accessToken",
                    self.account.mc_access if self.account.signed_in else "0",
                    "--userType",
                    "msa" if self.account.signed_in else "legacy",
                    "--versionType",
                    "release",
                ]
            )
            wrapper = (
                p.override_wrapper or self.settings.get("wrapper_command", "").strip()
            )
            if wrapper:
                cmd = shlex.split(wrapper) + cmd
            text = " ".join(shlex.quote(c) for c in cmd)
            QGuiApplication.clipboard().setText(text)
            self.console.log("ok", translate.t("console.copied_cmd"))
        except Exception as e:  # noqa: BLE001
            self.console.log("error", translate.t("console.copy_failed", err=e))

    def open_logs(self):
        if not self.current_profile:
            return
        logs = self.current_profile.dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        try:
            if IS_WIN:
                os.startfile(str(logs))
            elif IS_MAC:
                subprocess.Popen(["open", str(logs)])
            else:
                subprocess.Popen(["xdg-open", str(logs)])
        except Exception as e:  # noqa: BLE001
            self.console.log("error", translate.t("console.open_logs_failed", err=e))

    def fetch_manifest(self):
        def task(log, progress, progress_end):
            log("net", f"GET {MANIFEST_URL}")
            t0 = time.time()
            r = http.get(MANIFEST_URL)
            r.raise_for_status()
            d = r.json()
            rel = [v for v in d["versions"] if v["type"] == "release"]
            return d, rel, time.time() - t0

        w = Worker(task)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.done.connect(self._manifest_done, Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _manifest_done(self, r):
        if not r:
            return
        d, rel, secs = r
        self.manifest, self.releases = d, rel
        self.console.log(
            "ok", translate.t("console.manifest_loaded", n=len(rel), secs=f"{secs:.2f}")
        )

    def _apply_mc_icon(self, ic):
        for i in range(self.plist.count()):
            self.plist.item(i).setIcon(ic)

    def _get_username(self):
        acc = self.settings.active_online_account()
        if acc.signed_in:
            return acc.name
        return self.settings.active_offline_name()

    def _uuid(self, u):
        acc = self.settings.active_online_account()
        if acc.signed_in:
            return acc.uuid
        active = self.settings.get_active_account()
        if active and active.get("type") == "offline":
            stored = (active.get("data") or {}).get("uuid")
            if stored:
                return stored
        h = hashlib.md5(f"OfflinePlayer:{u}".encode()).hexdigest()
        return f"{h[:8]}-{h[8:12]}-3{h[13:16]}-{h[16:20]}-{h[20:32]}"

    def launch_toggle(self):
        if self._process and self._process.poll() is None:
            self.stop_instance()
        else:
            self.launch()

    def _set_launch_state(self, running, profile=None):
        if running:
            self._running_profile = profile
        else:
            self._running_profile = None

        same = (
            running
            and profile is not None
            and self.current_profile is not None
            and getattr(profile, "name", None)
            == getattr(self.current_profile, "name", None)
        )

        if same:
            self.launch_btn.setText(translate.t("btn.stop"))
            self.launch_btn.setStyleSheet(s_btn_stop())
        else:
            self.launch_btn.setText(translate.t("btn.launch"))
            self.launch_btn.setStyleSheet(s_btn_launch())
        self.launch_btn.setMinimumWidth(140)

    def launch(self):
        if self._process and self._process.poll() is not None:
            self._process = None
        if self._process:
            return
        if not self.current_profile:
            QMessageBox.information(
                self, translate.t("warn.wait"), translate.t("console.no_instance")
            )
            return
        if not self.manifest:
            QMessageBox.warning(
                self, translate.t("warn.wait"), translate.t("console.wait_manifest")
            )
            return
        p = self.current_profile
        self._launching_profile = p
        self.console.log(
            "info", translate.t("console.starting", name=p.name, version=p.version)
        )
        w = Worker(self._do_launch, p)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection,
        )
        w.done.connect(self._launch_done, Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _launch_done(self, proc):
        if proc:
            self._process = proc
            self._set_launch_state(True, self._launching_profile)
            self.console.log("ok", translate.t("console.running_pid", pid=proc.pid))
            threading.Thread(
                target=self._watch_process, args=(proc,), daemon=True
            ).start()
            threading.Thread(target=self._tail_log, daemon=True).start()
        else:
            self.console.log("error", translate.t("console.launch_failed"))
            self._set_launch_state(False)

    def _tail_log(self):
        profile = self._running_profile or self.current_profile
        candidates = []
        if profile is not None:
            candidates.append(profile.dir / "logs" / "latest.log")
            ext = getattr(profile, "_external_dir", None)
            if ext is not None:
                candidates.append(ext / "logs" / "latest.log")
        candidates.append(MC_ROOT / "logs" / "latest.log")
        seen_lines = 0
        timeout = time.time() + 30

        while self._process and self._process.poll() is None:
            log_file = next((p for p in candidates if p.exists()), None)
            if log_file is not None:
                try:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                        if len(lines) > seen_lines:
                            for line in lines[seen_lines:]:
                                clean = line.strip()
                                if clean:
                                    self.mc_log.emit(clean)
                            seen_lines = len(lines)
                            timeout = time.time() + 30
                except Exception:  # noqa: BLE001, S110
                    pass

            if time.time() > timeout:
                break
            time.sleep(0.5)

    def _watch_process(self, proc):
        with contextlib.suppress(Exception):
            proc.wait()
        with contextlib.suppress(Exception):
            self.mc_log.emit(translate.t("console.mc_exited", code=proc.returncode))
        self._process = None
        with contextlib.suppress(Exception):
            self.mc_log.emit("__exit__")

    def stop_instance(self):
        p = self._process
        if not p or p.poll() is not None:
            self._set_launch_state(False)
            return
        self.console.log("warn", translate.t("console.stopping_pid", pid=p.pid))
        try:
            if IS_WIN:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                    capture_output=True,
                    creationflags=NO_WINDOW,
                    check=False,
                )
            else:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:  # noqa: BLE001
                    p.kill()
        except Exception as e:  # noqa: BLE001
            self.console.log("error", translate.t("console.stop_failed", err=e))
        finally:
            self._process = None
            self._set_launch_state(False)

    def _manifest_version(self, version_id):
        if not self.manifest:
            return None
        for v in self.manifest.get("versions", []):
            if v.get("id") == version_id:
                return v
        return None

    def _ensure_vanilla_json(self, version, log):
        path = MC_ROOT / "versions" / version / f"{version}.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:  # noqa: BLE001, S110
                pass

        entry = self._manifest_version(version)
        if not entry:
            log(
                "error",
                f"Mojang's manifest does not contain version '{version}'. "
                f"Refresh the manifest or pick a version that exists.",
            )
            return None

        log("sys", f"Downloading vanilla JSON for {version}...")
        try:
            r = http.get(entry["url"])
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
            return r.json()
        except Exception as e:  # noqa: BLE001
            log("error", f"Failed to download {version}.json: {e}")
            return None

    def _load_external_version_json(self, profile, log):
        ext = getattr(profile, "_external_dir", None)
        candidates = []
        if ext is not None:
            candidates.append(ext / f"{ext.name}.json")
        candidates.append(MC_ROOT / "versions" / profile.name / f"{profile.name}.json")
        if profile.version:
            candidates.append(
                MC_ROOT / "versions" / profile.version / f"{profile.version}.json"
            )
        for path in candidates:
            if path.exists():
                try:
                    return json.loads(path.read_text())
                except Exception as e:  # noqa: BLE001
                    log("warn", f"failed to parse {path}: {e}")
                    continue
        log(
            "error",
            f"Could not find an on-disk version JSON for "
            f"'{profile.name}'. Looked in: {[str(p) for p in candidates]}",
        )
        return None

    def _ensure_vanilla_jar(
        self, version, vjson, log, progress=None, progress_end=None
    ):
        jar_path = MC_ROOT / "versions" / version / f"{version}.jar"
        if jar_path.exists() and jar_path.stat().st_size > 1000000:
            self._ensure_client_mappings(version, vjson, log)
            return jar_path

        log("sys", f"Downloading vanilla client.jar for {version}...")
        try:
            if "downloads" in vjson and "client" in vjson["downloads"]:
                url = vjson["downloads"]["client"]["url"]
                jar_path.parent.mkdir(parents=True, exist_ok=True)
                with http.stream("GET", url) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("content-length", 0))
                    done = 0
                    with open(jar_path, "wb") as f:
                        for chunk in r.iter_bytes(65536):
                            f.write(chunk)
                            done += len(chunk)
                            if progress and total:
                                progress("client.jar", done, total, "", "")
                if progress_end:
                    progress_end()
                self._ensure_client_mappings(version, vjson, log)
                return jar_path
        except Exception as e:  # noqa: BLE001
            log("error", f"Failed to download vanilla jar: {e}")
            return None
        return None

    def _ensure_client_mappings(self, version, vjson, log):
        downloads = (vjson or {}).get("downloads", {}) or {}
        entry = downloads.get("client_mappings")
        if not entry or not entry.get("url"):
            return
        mp = MC_ROOT / "versions" / version / f"{version}-client-mappings.txt"
        if mp.exists() and mp.stat().st_size > 0:
            return
        try:
            mp.parent.mkdir(parents=True, exist_ok=True)
            with http.stream("GET", entry["url"]) as r:
                r.raise_for_status()
                tmp = mp.with_suffix(".part")
                with open(tmp, "wb") as f:
                    f.writelines(r.iter_bytes(65536))
                tmp.replace(mp)
            log("sys", f"Downloaded client mappings for {version}")
        except Exception as e:  # noqa: BLE001
            log("warn", f"client mappings download failed: {e}")

    def _version_tokens(self, s):
        if not s:
            return []
        out = []
        for tok in re.split(r"[-_ /:\\]+", str(s)):
            tok = tok.strip()
            if re.match(r"^\d+(?:\.\d+)+$", tok):
                out.append(tok)
        return out

    def _collect_labymod_candidates(self, profile, laby, ext_dir):
        raw = []

        if laby:
            for k in ("inheritsFrom", "clientVersion", "id"):
                v = laby.get(k)
                if isinstance(v, str) and v.strip():
                    raw.append(v.strip())

        if ext_dir is not None:
            raw.append(ext_dir.name)
        raw.append(profile.name or "")
        raw.append(profile.version or "")

        seen = set()
        ordered = []

        def push(v):
            if v and v not in seen:
                seen.add(v)
                ordered.append(v)

        for r in raw:
            if not r:
                continue
            push(r)
            for tok in self._version_tokens(r):
                push(tok)

        return ordered

    def _resolve_labymod_base(self, profile, log):
        ext = getattr(profile, "_external_dir", None)
        if ext is not None:
            json_path = ext / f"{ext.name}.json"
        else:
            json_path = MC_ROOT / "versions" / profile.name / f"{profile.name}.json"

        laby = None
        if json_path.exists():
            try:
                laby = json.loads(json_path.read_text())
            except Exception as e:  # noqa: BLE001
                log("error", f"failed to read {json_path}: {e}")
                return None

        candidates = self._collect_labymod_candidates(profile, laby, ext)
        known = {v["id"] for v in (self.manifest or {}).get("versions", [])}

        for c in candidates:
            if c in known:
                if laby is not None and laby.get("inheritsFrom") != c:
                    with contextlib.suppress(Exception):
                        laby["inheritsFrom"] = c
                        json_path.write_text(json.dumps(laby, indent=2))
                        log("ok", f"Patched {json_path.name}: inheritsFrom = {c}")
                return c

        log(
            "error",
            f"LabyMod profile '{profile.name}' could not resolve a base "
            f"Minecraft version. Tried: {candidates}. "
            f"None is in Mojang's manifest.",
        )
        return None

    def _do_launch(self, profile, log, progress, progress_end):
        acc = self.settings.active_online_account()
        if acc.signed_in:
            try:
                acc.ensure_valid()
                accs = self.settings.get_accounts()
                active = self.settings.get("active_account", 0)
                if 0 <= active < len(accs):
                    accs[active]["data"] = acc.to_dict()
                    self.settings.set_accounts(accs)
                log("ok", translate.t("console.account_ok", name=acc.name))
            except Exception as e:  # noqa: BLE001
                log("warn", translate.t("console.token_refresh_failed", err=e))
                log("warn", translate.t("console.offline_fallback"))

        is_labymod = "labymod" in profile.name.lower()

        if is_labymod:
            vanilla_id = self._resolve_labymod_base(profile, log)
            if not vanilla_id:
                return None
            effective_version = profile.name

            vj = self._load_external_version_json(profile, log)
            if not vj:
                log("error", f"Failed to load LabyMod JSON {effective_version}")
                return None

            vanilla_vjson = self._ensure_vanilla_json(vanilla_id, log)
            if not vanilla_vjson:
                log("error", f"Failed to load vanilla JSON {vanilla_id}")
                return None

            jar_path = self._ensure_vanilla_jar(
                vanilla_id, vanilla_vjson, log, progress, progress_end
            )
            if not jar_path:
                log("error", "Failed to obtain vanilla client.jar")
                return None

            log("sys", "Building LabyMod classpath (filtering Quilt/Fabric)...")
            cp = [str(jar_path)]

            def add_jars(base_dir):
                if not base_dir.exists():
                    return
                for jar in base_dir.rglob("*.jar"):
                    path_str = str(jar).lower()
                    if "quilt" in path_str or "fabric" in path_str:
                        continue
                    cp.append(str(jar))

            add_jars(MC_ROOT / "libraries")
            add_jars(MC_ROOT / "labymod-neo" / "libraries")
            ext = getattr(profile, "_external_dir", None)
            if ext is not None:
                add_jars(ext / "libraries")
                ext_jar = ext / f"{ext.name}.jar"
                if ext_jar.exists() and ext_jar.stat().st_size > 1000:
                    cp.append(str(ext_jar))

            patches_dir = MC_ROOT / "labymod-neo" / "patches"
            patches_dir.mkdir(parents=True, exist_ok=True)
            patch_file = patches_dir / "net.minecraft.json"
            release_time = vanilla_vjson.get("releaseTime", "2024-01-01T00:00:00+00:00")
            patch_data = {"id": vanilla_id, "releaseTime": release_time}
            with contextlib.suppress(Exception):
                patch_file.write_text(json.dumps(patch_data, indent=2))
                log("sys", f"Generated LabyMod patch (id={vanilla_id})")

            main_class = "net.minecraft.launchwrapper.Launch"
            tweak_class = (
                "net.labymod.core.loader.vanilla."
                "launchwrapper.LabyModLaunchWrapperTweaker"
            )
        else:
            vanilla_id = profile.version
            effective_version = profile.version

            is_external = getattr(profile, "_external_dir", None) is not None
            if is_external:
                effective_version = profile.name
                vanilla_id = profile.version
            else:
                effective_version = loaders.install(
                    profile.loader,
                    profile.version,
                    log=log,
                    progress=progress,
                    progress_end=progress_end,
                    force_version=getattr(profile, "loader_version", "") or "",
                )
                if not effective_version:
                    log("warn", translate.t("console.loader_fallback"))
                    effective_version = profile.version
                vanilla_id = profile.version

            vj = self._ensure_vanilla_json(effective_version, log)
            if not vj:
                log("error", f"Failed to load JSON for {effective_version}")
                return None

            vanilla_vjson = self._ensure_vanilla_json(vanilla_id, log)
            if not vanilla_vjson:
                log("error", f"Failed to load vanilla JSON for {vanilla_id}")
                return None

            jar_path = self._ensure_vanilla_jar(
                vanilla_id, vanilla_vjson, log, progress, progress_end
            )
            if not jar_path:
                log("error", "Failed to obtain vanilla client.jar")
                return None

            vj = self._resolve_inheritance(effective_version, vj, log)

            libs_dir = MC_ROOT / "libraries"
            cp = [str(jar_path)]

            libs = [
                x for x in vj.get("libraries", []) if self._rules_ok(x.get("rules"))
            ]
            for lib in libs:
                url, rel = self._resolve_library(lib)
                if not url or not rel:
                    continue
                p = libs_dir / rel
                if p.exists() and p.stat().st_size > 0 or self._dl_silent(url, p):
                    cp.append(str(p))

            main_class = vj.get("mainClass", "net.minecraft.client.main.Main")
            tweak_class = None

        java_override = profile.override_java_path or self.settings.get("java_path", "")
        if is_labymod and not java_override:
            log("java", "LabyMod requires Java 25 - installing")
            java = best_java(vanilla_id, log, override="", required_major=25)
        else:
            java = best_java(vanilla_id, log, override=java_override)
        if not java:
            log("error", translate.t("console.no_java"))
            return None

        native_dirs = []
        for lib in vj.get("libraries", []):
            if not self._rules_ok(lib.get("rules")):
                continue
            nat = self._native(lib)
            if nat:
                out = (
                    MC_ROOT
                    / "versions"
                    / vanilla_id
                    / "natives"
                    / lib["name"].replace(":", "_")
                )
                out.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(Exception):
                    with zipfile.ZipFile(nat) as z:
                        z.extractall(out)
                    native_dirs.append(str(out))

        self._download_assets(vanilla_vjson, progress, progress_end, log)
        assets = MC_ROOT / "assets"
        idx = vanilla_vjson.get("assetIndex")

        sep = ";" if IS_WIN else ":"
        jvm_flags = build_jvm_flags(profile, self.settings, native_dirs, sep)

        if is_labymod:
            jvm_flags.extend(
                [
                    f"-Dnet.labymod.running-version={vanilla_id}",
                    "-Dnet.labymod.launcher=multimc",
                    f"-Dnet.labymod.minecraft.version={vanilla_id}",
                ]
            )

        if getattr(profile, "_external_dir", None) is not None:
            game_dir = profile._external_dir
        else:
            game_dir = profile.dir
        game_dir.mkdir(parents=True, exist_ok=True)

        cmd = (
            [java]
            + jvm_flags
            + [
                "-cp",
                sep.join(cp),
                main_class,
                "--username",
                self._get_username(),
                "--version",
                vanilla_id,
                "--gameDir",
                str(game_dir),
                "--assetsDir",
                str(assets),
                "--assetIndex",
                idx["id"] if idx else "legacy",
                "--uuid",
                self._uuid(self._get_username()),
                "--accessToken",
                acc.mc_access if acc.signed_in else "0",
                "--userType",
                "msa" if acc.signed_in else "legacy",
                "--versionType",
                "release",
            ]
        )

        if tweak_class:
            cmd.extend(["--tweakClass", tweak_class])

        wrapper = (
            profile.override_wrapper or self.settings.get("wrapper_command", "").strip()
        )
        if wrapper:
            try:
                cmd = shlex.split(wrapper) + cmd
            except Exception as e:  # noqa: BLE001
                log("error", translate.t("console.invalid_wrapper", err=e))

        log_dir = game_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "latest.log"
        try:
            log_fp = open(  # noqa: SIM115
                log_file,
                "w",
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:  # noqa: BLE001
            log("error", f"could not open log: {e}")
            return None

        env = build_launch_env(profile, self.settings)
        if not IS_WIN and is_labymod:
            st = os.environ.get("XDG_SESSION_TYPE", "").lower()
            wl = bool(os.environ.get("WAYLAND_DISPLAY")) or st == "wayland"
            if wl:
                env["SDL_VIDEODRIVER"] = "x11"
                env["_JAVA_AWT_WM_NONREPARENTING"] = "1"
                log("sys", "Wayland detected. Forcing SDL to X11.")

        log("sys", translate.t("console.spawning", ram=profile.ram))
        popen_kwargs = {
            "cwd": str(game_dir),
            "stdin": subprocess.DEVNULL,
            "stdout": log_fp,
            "stderr": subprocess.STDOUT,
            "env": env,
            "close_fds": True,
        }
        if IS_WIN:
            popen_kwargs["creationflags"] = _detached_flags()
        else:
            popen_kwargs["start_new_session"] = True

        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
        except FileNotFoundError:
            log_fp.close()
            log("error", translate.t("console.java_not_found", path=java))
            return None
        except Exception as e:  # noqa: BLE001
            log_fp.close()
            log("error", translate.t("console.spawn_failed", err=e))
            return None

        time.sleep(0.6)
        if proc.poll() is not None:
            log_fp.close()
            try:
                tail = log_file.read_text(encoding="utf-8", errors="replace")
                for line in tail.splitlines()[-40:]:
                    if line.strip():
                        log("error", line)
            except Exception:  # noqa: BLE001, S110
                pass
            log(
                "error", translate.t("console.exited_immediately", code=proc.returncode)
            )
            return None

        log_fp.close()
        log("ok", translate.t("console.game_detached", path=log_file))
        return proc

    def _download_assets(self, vjson, progress, progress_end, log):
        idx = vjson.get("assetIndex")
        if not idx:
            return
        assets_root = MC_ROOT / "assets"
        idx_path = assets_root / "indexes" / f"{idx['id']}.json"
        if not idx_path.exists():
            idx_path.parent.mkdir(parents=True, exist_ok=True)
            r = http.get(idx["url"])
            r.raise_for_status()
            idx_path.write_bytes(r.content)
        try:
            index = json.loads(idx_path.read_text())
        except Exception as e:  # noqa: BLE001
            log("error", f"asset index parse failed: {e}")
            return
        objects = index.get("objects", {})
        to_get = []
        for meta in objects.values():
            h = meta["hash"]
            sub = h[:2]
            dest = assets_root / "objects" / sub / h
            if not dest.exists():
                to_get.append((h, dest))
        if not to_get:
            return
        log("sys", translate.t("console.assets_missing", n=len(to_get)))
        lock = threading.Lock()
        done = [0]
        workers = HW.asset_workers

        def fetch(item):
            h, dest = item
            url = f"https://resources.download.minecraft.net/{h[:2]}/{h}"
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with http.stream("GET", url) as r:
                    r.raise_for_status()
                    tmp = dest.with_suffix(".part")
                    with open(tmp, "wb") as f:
                        f.writelines(r.iter_bytes(65536))
                    tmp.replace(dest)
                ok = True
            except Exception:  # noqa: BLE001
                ok = False
            with lock:
                done[0] += 1
                if done[0] % 25 == 0 or done[0] == len(to_get):
                    progress("assets", done[0], len(to_get), "", "")
            return ok

        ok_count = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for ok in ex.map(fetch, to_get):
                if ok:
                    ok_count += 1
        progress_end()
        log("ok", translate.t("console.assets_done", n=ok_count, total=len(to_get)))

    def _resolve_inheritance(self, vid, vj, log):
        parent_id = vj.get("inheritsFrom")
        if not parent_id:
            return vj
        log("sys", f"{vid} inherits from {parent_id}")
        parent = self._get_vjson(parent_id)
        if not parent:
            log("error", f"could not load parent {parent_id}")
            return vj
        merged_libs = list(parent.get("libraries", []))
        merged_libs.extend(vj.get("libraries", []))
        merged = dict(parent)
        merged.update(vj)
        merged["libraries"] = merged_libs
        for k in ("downloads", "assetIndex", "assets", "javaVersion"):
            if k not in merged and k in parent:
                merged[k] = parent[k]
        return merged

    def _resolve_library(self, lib):
        art = lib.get("downloads", {}).get("artifact")
        if art:
            return art["url"], art["path"]
        name = lib.get("name")
        if not name:
            return None, None
        parts = name.split(":")
        if len(parts) < 3:
            return None, None
        group, artifact, version = parts[0], parts[1], parts[2]
        classifier = parts[3] if len(parts) > 3 else None
        group_path = group.replace(".", "/")
        fname = f"{artifact}-{version}"
        if classifier:
            fname += f"-{classifier}"
        fname += ".jar"
        rel = f"{group_path}/{artifact}/{version}/{fname}"
        base = (lib.get("url") or "https://libraries.minecraft.net/").rstrip("/")
        return f"{base}/{rel}", rel

    def _dl_silent(self, url, dest):
        dest = Path(dest)
        if dest.exists() and dest.stat().st_size > 0:
            return True
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with http.stream("GET", url) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as f:
                    f.writelines(r.iter_bytes(65536))
                tmp.replace(dest)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _get_vjson(self, vid):
        entry = self._manifest_version(vid)
        if entry:
            with contextlib.suppress(Exception):
                return http.get(entry["url"]).json()
        path = MC_ROOT / "versions" / vid / f"{vid}.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:  # noqa: BLE001
                return None
        return None

    def _rules_ok(self, rules):
        if not rules:
            return True
        o = {"windows": "windows", "darwin": "osx", "linux": "linux"}.get(
            platform.system().lower(), "linux"
        )
        a = False
        for r in rules:
            ro = r.get("os", {}).get("name")
            if ro is None or ro == o:
                a = r.get("action") == "allow"
        return a

    def _native(self, lib):
        cl = lib.get("downloads", {}).get("classifiers", {})
        if not cl:
            return None
        s = platform.system().lower()
        keys = {
            "windows": ["natives-windows", "natives-windows-64"],
            "darwin": ["natives-macos", "natives-osx"],
            "linux": ["natives-linux"],
        }.get(s, [])
        for k in keys:
            if k in cl:
                art = cl[k]
                p = MC_ROOT / "libraries" / art["path"]
                if p.exists():
                    return p
                try:
                    with http.stream("GET", art["url"]) as r:
                        r.raise_for_status()
                        p.parent.mkdir(parents=True, exist_ok=True)
                        with open(p, "wb") as f:
                            f.writelines(r.iter_bytes(16384))
                    return p
                except Exception:  # noqa: BLE001
                    return None
        return None

    def _ctx_menu(self, pos):
        it = self.plist.itemAt(pos)
        if not it:
            return
        self.plist.setCurrentItem(it)
        if not self.current_profile:
            return

        m = QMenu(self)
        m.setStyleSheet(s_menu())

        is_vanilla = (self.current_profile.loader or "vanilla").lower() == "vanilla"

        for label_key, kind in (
            ("title.mods", "mod"),
            ("title.resourcepacks", "resourcepack"),
            ("title.shaders", "shader"),
        ):
            label = translate.t(label_key)
            a = QAction(label, m)

            if is_vanilla and kind in ("mod", "shader"):
                a.setText(f"{label} (Vanilla)")
                a.setEnabled(False)
            else:
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
        ItemsDialog(self, self.current_profile, self.console.log, kind).exec()

    def closeEvent(self, event):
        _shutdown.set()
        with contextlib.suppress(Exception):
            self._auto_check_timer.stop()

        for w in list(self._workers):
            try:
                if w.isRunning():
                    with contextlib.suppress(Exception):
                        w.log.disconnect()
                        w.done.disconnect()
                        w.progress.disconnect()
                        w.progress_end.disconnect()
                    w.quit()
                    if not w.wait(3000):
                        _leaked_threads.append(w)
                        w.setParent(None)
            except Exception:  # noqa: BLE001, S110
                pass
        http.close()
        event.accept()
