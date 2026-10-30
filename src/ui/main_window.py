import contextlib

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
    QPainter,
    QPalette,
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from core import hardware, theme, translate
from core.paths import MC_ROOT
from core.settings import Settings
from ui.account import AccountView
from ui.console import Console
from ui.helpers import (
    s_btn_launch,
    s_btn_set,
    s_btn_stop,
    s_combo_popup,
    s_plus_btn,
    s_popup_menu,
    s_tabs,
)
from ui.launch_ops import LaunchOps
from ui.menu import MenuView
from ui.particles import ParticleOverlayMixin
from ui.profile_ops import ProfileOps

HW = hardware.get()


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


class MainWindow(ProfileOps, LaunchOps, ParticleOverlayMixin, QMainWindow):
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
            "sys",
            f"Platform {__import__('platform').system()} "
            f"Python {__import__('platform').python_version()}",
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
        self.console.log("sys", f"Minecraft root {MC_ROOT}")
        self.load_profiles()
        self.fetch_manifest()
        self._warm_modrinth()
        from ui.loader_icons import fetch_all_loaders

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
        import time

        try:
            last = float(self.settings.get("auto_check_last_run", 0))
        except (TypeError, ValueError):
            last = 0.0
        elapsed = time.time() - last if last > 0 else interval
        delay = max(30, int(interval - elapsed))
        self._auto_check_timer.start(delay * 1000)

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

    def closeEvent(self, event):
        from core.worker import _leaked_threads, _shutdown
        from integration import net as http

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
