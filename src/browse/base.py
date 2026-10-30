import json
import time
import os
from pathlib import Path
from urllib.parse import urlencode

from PyQt6.QtCore import Qt, QTimer, QSize, QUrl, pyqtSignal
from PyQt6.QtGui import QIcon, QColor, QPalette
from PyQt6.QtNetwork import (
    QNetworkAccessManager, QNetworkRequest, QNetworkReply,
)
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QLineEdit, QListWidget, QListWidgetItem, QWidget,
    QPushButton, QMessageBox, QStyle, QSizePolicy,
    QStyledItemDelegate,
)

from core import theme
from core import hardware
from core import translate
from core.worker import Worker
from ui.console import MiniConsole
from integration import net as http
from ui.helpers import (
    TranslucentDialog, dialog_shell_style,
    s_glass_btn_neutral, glass_soft, glass_accent,
    glass_border, _is_wayland,
)

from browse.common import _ICON_CACHE, IconLoader, GalleryLoader
from browse.utils import (
    ICON_SIZE_ROW, make_placeholder,
    square_icon, square_icon_pixmap,
)
from browse.detail import DetailPanel


HW = hardware.get()


class _NoDimDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        option.state |= QStyle.StateFlag.State_Active
        option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, index)


def _apply_no_dim_palette(widget):
    pal = widget.palette()
    base = QColor(0, 0, 0, 0)
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        pal.setColor(group, QPalette.ColorRole.Base, base)
        pal.setColor(group, QPalette.ColorRole.Window, base)
        pal.setColor(group, QPalette.ColorRole.Text, QColor(theme.FG))
        pal.setColor(group, QPalette.ColorRole.WindowText, QColor(theme.FG))
        pal.setColor(group, QPalette.ColorRole.Highlight, QColor(theme.ACCENT))
        pal.setColor(group, QPalette.ColorRole.HighlightedText, QColor(theme.FG))
    widget.setPalette(pal)


class BrowseBase(TranslucentDialog):
    install_finished = pyqtSignal(str)

    ROW_PAD = 4
    ROW_GAP = 6
    PAGE_SIZE = 30

    def __init__(self, parent, profile, log_fn):
        super().__init__(parent)
        self.profile = profile
        self.log_fn = log_fn
        self.results_data = []
        self._req_id = 0
        self._w = None
        self._last_query = ""
        self._rows = {}
        self._selected_row = -1
        self._search_reply = None
        self._last_silent = False
        self._deleted = False
        self._page = 1
        self._max_page_seen = 1
        self._has_next = False
        self._page_cache = {}

        self.setWindowTitle(f"{self.window_title()} - {profile.name}")
        self.resize(1180, 720)
        self.setMinimumSize(920, 580)
        self.setStyleSheet(dialog_shell_style())

        self.BLUR_RADIUS = 12
        self.TINT_ALPHA = 70
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Base, Qt.GlobalColor.transparent)
        pal.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.transparent)
        self.setPalette(pal)

        win_ic = QIcon.fromTheme("applications-games")
        if not win_ic.isNull():
            self.setWindowIcon(win_ic)

        self._nam = QNetworkAccessManager(self)

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)

        self.main_layout = v

        head_row = QHBoxLayout()
        head_row.setSpacing(6)
        head_ic = QLabel()
        head_ic.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        head_ic.setAttribute(
            Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        hi = QIcon.fromTheme(self.header_icon())
        if hi.isNull():
            hi = QIcon.fromTheme("package-x-generic")
        if not hi.isNull():
            head_ic.setPixmap(hi.pixmap(20, 20))
        head = QLabel(
            f"{self.window_title()}  ->  {profile.name}")
        head.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        head.setAttribute(
            Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        head.setStyleSheet(
            f"color:{theme.FG};font-size:13pt;font-weight:400;"
            f"background:transparent;outline:none;")
        head_row.addWidget(head_ic)
        head_row.addWidget(head)

        self.head_row = head_row
        v.addLayout(head_row)

        row = QHBoxLayout()
        row.setSpacing(0)
        self.search = QLineEdit()
        self.search.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.search.setPlaceholderText(self.search_placeholder())

        self.search.setStyleSheet(
            f"QLineEdit{{background:transparent;color:{theme.FG};"
            f"border:none;"
            f"border-radius:8px;padding:8px 10px;"
            f"font-family:'{theme.UI_FONT}';font-size:10pt}}"
            f"QLineEdit:focus{{outline:none;}}")

        search_ic = QIcon.fromTheme("edit-find")
        if not search_ic.isNull():
            self.search.addAction(
                search_ic, QLineEdit.ActionPosition.LeadingPosition)
        row.addWidget(self.search, 1)
        v.addLayout(row)

        self.search_row = row

        self.search_body = self._build_search_body()

        self.bottom_widget = QWidget()
        self.bottom_widget.setStyleSheet("background:transparent;")
        btns = QHBoxLayout(self.bottom_widget)
        btns.setContentsMargins(0, 0, 0, 0)
        btns.setSpacing(6)
        btns.addStretch(1)

        self.install_btn = QPushButton(
            translate.t("btn.install_selected"))
        self.install_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.install_btn.setStyleSheet(
            f"QPushButton{{background:{glass_accent(160)};"
            f"color:{theme.accent_text()};"
            f"padding:8px 20px;font-weight:400;border-radius:8px;"
            f"border:none;outline:none;text-align:center;}}"
            f"QPushButton:hover{{background:{glass_accent(210)};}}"
            f"QPushButton:disabled{{background:{glass_soft(80)};"
            f"color:{theme.GRAY};}}")
        self.install_btn.setMinimumWidth(180)
        self.install_btn.setMinimumHeight(34)
        self.install_btn.setSizePolicy(QSizePolicy.Policy.Preferred,
                                       QSizePolicy.Policy.Fixed)
        self.install_btn.setAutoDefault(False)
        self.install_btn.setDefault(False)
        self.install_btn.clicked.connect(self.install_selected)
        btns.addWidget(self.install_btn)

        v.addWidget(self.bottom_widget)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(700)
        self._debounce.timeout.connect(self.search_now)

        self.icon_loader = IconLoader(self, nam=self._nam)
        self.icon_loader.icon_ready.connect(self._on_icon_ready)

        self.gallery_loader = GalleryLoader(self, nam=self._nam)
        self.gallery_loader.shot_ready.connect(self._on_shot_ready)

        self.search.textChanged.connect(self._schedule_search)
        self.search.returnPressed.connect(self.search_now)

        for _lbl in self.findChildren(QLabel):
            _lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            _lbl.setAttribute(
                Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        for _btn in self.findChildren(QPushButton):
            _btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.search.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for _le in self.findChildren(QLineEdit):
            _le.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._log("info", translate.t(
            "console.ready",
            title=self.window_title(), name=profile.name))

    def _build_search_body(self):
        body = QWidget()
        body.setStyleSheet("background:transparent;outline:none;")
        body.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(6)

        left = QWidget()
        left.setStyleSheet("background:transparent;outline:none;")
        left.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        left.setMinimumWidth(360)
        left.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        self.left_widget = left

        self.list = QListWidget()
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.list.viewport().setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.list.viewport().setAutoFillBackground(False)
        self.list.setAttribute(
            Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection)
        self.list.setIconSize(QSize(ICON_SIZE_ROW, ICON_SIZE_ROW))
        self.list.setVerticalScrollMode(
            QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setStyleSheet(
            f"QListWidget{{background:transparent;color:{theme.FG};"
            f"padding:0;border:none;border-radius:8px;outline:0}}"
            f"QListWidget:focus{{outline:none;}}"
            f"QListWidget::item{{padding:0;outline:none;"
            f"border-radius:6px;background:transparent;}}"
            f"QListWidget::item:focus{{outline:none;"
            f"background:{glass_accent(160)};}}"
            f"QListWidget::item:selected{{background:{glass_accent(160)};"
            f"outline:none;}}"
            f"QListWidget::item:hover{{background:{glass_soft(140)};"
            f"outline:none;}}"
            f"QScrollBar:vertical{{background:transparent;width:6px;margin:0;}}"
            f"QScrollBar::handle:vertical{{background:{glass_border(30)};"
            f"min-height:20px;border-radius:3px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
            f"QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{{background:transparent;}}"
        )
        self.list.viewport().setStyleSheet("background: transparent;")
        self.list.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.list.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.list.setItemDelegate(_NoDimDelegate(self.list))
        _apply_no_dim_palette(self.list)

        self.list.currentRowChanged.connect(self._on_row_changed)
        self.list.verticalScrollBar().valueChanged.connect(
            self._request_visible_icons)

        ll.addWidget(self.list, 1)

        self.pager = QWidget()
        self.pager.setStyleSheet("background:transparent;outline:none;")
        self.pager_row = QHBoxLayout(self.pager)
        self.pager_row.setContentsMargins(0, 4, 0, 0)
        self.pager_row.setSpacing(4)
        self.pager_row.addStretch(1)
        self.pager.setVisible(False)
        ll.addWidget(self.pager, 0)

        self.log_frame = QFrame()
        self.log_frame.setFrameShape(QFrame.Shape.NoFrame)
        self.log_frame.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.log_frame.setStyleSheet(
            "QFrame{background:transparent;border:none;}")
        self.log_frame.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        lfl = QVBoxLayout(self.log_frame)
        lfl.setContentsMargins(0, 0, 0, 0)
        lfl.setSpacing(0)
        lh_row = QHBoxLayout()
        lh_row.setContentsMargins(6, 4, 6, 4)
        lh_row.setSpacing(6)
        lh_ic = QLabel()
        lh_ic.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        li = QIcon.fromTheme("utilities-terminal")
        if not li.isNull():
            lh_ic.setPixmap(li.pixmap(16, 16))
        lh_row.addWidget(lh_ic)
        lh = QLabel(translate.t("header.activity"))
        lh.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lh.setStyleSheet(
            f"color:{theme.GRAY};font-size:8pt;"
            f"background:transparent;outline:none;")
        lh_row.addWidget(lh)
        lh_row.addStretch(1)
        lfl.addLayout(lh_row)

        self.log_view = MiniConsole()
        self.log_view.setStyleSheet("background:transparent;border:none;")
        self.log_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.log_view.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.log_view.setMaximumHeight(90)
        lfl.addWidget(self.log_view, 1)

        self.log_frame.setMinimumHeight(100)
        self.log_frame.setMaximumHeight(120)

        ll.addWidget(self.log_frame, 0)

        body_layout.addWidget(left, 1)

        self.detail = DetailPanel(nam=self._nam)
        body_layout.addWidget(self.detail, 1)

        return body

    def add_header_widget(self, widget):
        self.head_row.insertWidget(2, widget)

    def finalize_header(self):
        self.head_row.addStretch()

    def window_title(self):
        return translate.t("app.title")

    def search_placeholder(self):
        return ""

    def header_icon(self):
        return "package-x-generic"

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.search.text():
                self.search.blockSignals(True)
                self.search.clear()
                self.search.blockSignals(False)
                self._last_query = ""
                self.list.clear()
                self.results_data = []
                self._page_cache.clear()
                self._rows.clear()
                self._page = 1
                self._max_page_seen = 1
                self._has_next = False
                self._rebuild_pager()
                self.detail.pid = None
                self.detail.force_close()
                event.accept()
                return
            self.reject()
            event.accept()
            return
        super().keyPressEvent(event)

    def _focus_search(self):
        if self._deleted:
            return
        if not _is_wayland():
            self.raise_()
            self.activateWindow()
        self.search.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.search.selectAll()

    def showEvent(self, event):
        super().showEvent(event)
        if _is_wayland():
            self.search.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            QTimer.singleShot(100, self._focus_search)

    def _row_height(self):
        return ICON_SIZE_ROW + self.ROW_PAD * 2 + self.ROW_GAP

    def pick_download(self, hit):
        raise NotImplementedError

    def _search_url(self, query, offset=0):
        raise NotImplementedError

    def _parse_search_response(self, obj):
        return [{"id": h["project_id"], "title": h["title"],
                 "author": h["author"], "desc": h.get("description", ""),
                 "dl": h.get("downloads", 0),
                 "categories": h.get("categories", [])}
                for h in obj.get("hits", [])]

    def row_title(self, hit):
        return hit["title"]

    def row_subtitle(self, hit):
        return translate.t("browse.meta", author=hit["author"])

    def _btn_style(self):
        return s_glass_btn_neutral()

    def _icon(self, name, fallback):
        ic = QIcon.fromTheme(name)
        return ic if not ic.isNull() else self.style().standardIcon(fallback)

    def _log(self, tag, msg):
        if self._deleted:
            return
        try:
            self.log_view.log(tag, msg)
        except RuntimeError:  # noqa: BLE001, S110
            pass
        self.log_fn(tag, msg)

    def _schedule_search(self, _):
        q = self.search.text().strip()
        if q == self._last_query:
            return
        self._debounce.stop()
        self._debounce.start()

    def search_now(self, silent=False):
        if self._deleted:
            return
        self._debounce.stop()
        q = self.search.text().strip()
        if not q:
            self.list.clear()
            self.results_data = []
            self._page_cache.clear()
            self._rows.clear()
            self._page = 1
            self._max_page_seen = 1
            self._has_next = False
            self._rebuild_pager()
            self.detail.pid = None
            self.detail.force_close()
            return
        if q == self._last_query and not silent and self._page == 1:
            return
        self._last_query = q
        self._last_silent = silent
        self._page = 1
        self._max_page_seen = 1
        self._has_next = False
        self._page_cache.clear()
        self._fetch_page(1, silent)

    def _fetch_page(self, page, silent=False):
        if self._deleted:
            return
        if page in self._page_cache:
            self._render_page_from_cache(page)
            return

        q = self._last_query
        if not q:
            return

        offset = (page - 1) * self.PAGE_SIZE
        self._req_id += 1
        rid = self._req_id

        if self._search_reply is not None:
            try:
                self._search_reply.abort()
                self._search_reply.deleteLater()
            except Exception:  # noqa: BLE001, S110
                pass
            self._search_reply = None

        if not silent:
            self.list.clear()
            self._rows.clear()
            self.detail.pid = None
            self.detail.force_close()

        url, params = self._search_url(q, offset)
        full = f"{url}?{urlencode(params)}"
        req = QNetworkRequest(QUrl(full))
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        req.setRawHeader(b"User-Agent", b"Xeria-Launcher/2.504")
        self._log("net", translate.t(
            "console.query", q=q, kind=self.window_title()))
        reply = self._nam.get(req)
        self._search_reply = reply
        reply.finished.connect(
            lambda r=reply, r_=rid, p=page, s=silent:
                self._on_search(r, r_, p, s))

    def _on_search(self, reply, rid, page, silent):
        if self._deleted:
            try:
                reply.deleteLater()
            except Exception:  # noqa: BLE001, S110
                pass
            return
        if rid != self._req_id:
            try:
                reply.deleteLater()
            except Exception:  # noqa: BLE001, S110
                pass
            return
        status = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        data = reply.readAll()
        err = reply.error()
        reply.deleteLater()
        self._search_reply = None
        if err != QNetworkReply.NetworkError.NoError or status != 200:
            self._log("error", translate.t(
                "console.search_failed", status=status))
            return
        try:
            obj = json.loads(bytes(data).decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            self._log("error", translate.t(
                "console.search_parse_failed", err=e))
            return
        hits = self._parse_search_response(obj)
        self._page_cache[page] = list(hits)
        if len(hits) < self.PAGE_SIZE:
            self._has_next = False
        else:
            self._has_next = True
        self._max_page_seen = max(self._max_page_seen, page)
        if not silent:
            self._log("ok", translate.t(
                "console.results_count", n=len(hits)))
        self._page = page
        self._render_page_from_cache(page)

    def _installed_keys(self):
        d = self.profile.dir / self.folder_name()
        if not d.exists():
            return set()
        keys = set()
        for f in d.iterdir():
            try:
                if not f.is_file():
                    continue
            except Exception:  # noqa: BLE001, S112
                continue
            stem = f.stem.lower()
            keys.add(stem)
            base = stem.split("-")[0]
            keys.add(base)
            keys.add(base.replace("_", ""))
            keys.add(stem.replace("-", "").replace("_", ""))
        return keys

    def folder_name(self):
        return ""

    def _render_page_from_cache(self, page):
        if self._deleted:
            return
        if page not in self._page_cache:
            self._fetch_page(page)
            return
        self._page = page
        self.results_data = list(self._page_cache[page])

        self.list.blockSignals(True)
        self.list.clear()
        self._rows.clear()
        installed = self._installed_keys()

        for h in self.results_data:
            key = h["title"].lower().replace(" ", "")
            is_installed = (key in installed
                            or key.replace("_", "") in installed
                            or key.replace(" ", "").replace("_", "")
                                 in installed)

            it = QListWidgetItem()
            it.setSizeHint(QSize(0, self._row_height()))
            it.setData(Qt.ItemDataRole.UserRole + 1,
                       h.get("id") or h.get("project_id"))
            it.setData(Qt.ItemDataRole.UserRole + 2, is_installed)
            self.list.addItem(it)

            row = self._make_row(h, is_installed)
            self.list.setItemWidget(it, row)
            self._rows[h.get("id") or h.get("project_id")] = row
        self.list.blockSignals(False)

        if self.results_data:
            self.list.setCurrentRow(0)
            QTimer.singleShot(50, self._request_visible_icons)
            if not _is_wayland():
                QTimer.singleShot(0, self._focus_search)
        else:
            self.detail.pid = None
            self.detail.force_close()

        self.list.scrollToTop()
        self._rebuild_pager()

    def _rebuild_pager(self):
        if self._deleted:
            return
        while self.pager_row.count():
            item = self.pager_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.pager_row.addStretch(1)
        if self._max_page_seen <= 1 and not self._has_next:
            self.pager.setVisible(False)
            return
        self.pager.setVisible(True)

        def _btn(text, page, enabled=True, current=False):
            b = QPushButton(text)
            b.setFixedHeight(28)
            b.setMinimumWidth(32)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setAutoDefault(False)
            b.setDefault(False)
            b.setEnabled(enabled)
            if current:
                bg = glass_accent(200)
                fg = theme.accent_text()
                b.setStyleSheet(
                    f"QPushButton{{background:{bg};color:{fg};"
                    f"padding:0 10px;font-weight:400;border-radius:6px;"
                    f"border:none;outline:none;}}"
                    f"QPushButton:focus{{outline:none;}}")
            else:
                b.setStyleSheet(
                    f"QPushButton{{background:{glass_soft(120)};"
                    f"color:{theme.FG};padding:0 10px;border-radius:6px;"
                    f"border:none;outline:none;}}"
                    f"QPushButton:focus{{outline:none;}}"
                    f"QPushButton:hover{{background:{glass_soft(180)};}}"
                    f"QPushButton:disabled{{color:{theme.GRAY};}}")
            if enabled and not current:
                b.clicked.connect(
                    lambda _=False, p=page: self._go_page(p))
            return b

        cur = self._page
        total = self._max_page_seen + (1 if self._has_next else 0)

        self.pager_row.insertWidget(
            self.pager_row.count() - 1,
            _btn("<", max(1, cur - 1), enabled=cur > 1))

        window = 2
        pages = []
        for p in range(1, total + 1):
            if (p == 1 or p == total
                    or abs(p - cur) <= window):
                pages.append(p)
            else:
                pages.append(None)

        last = None
        for p in pages:
            if p is None:
                if last is not None:
                    lbl = QLabel("...")
                    lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                    lbl.setStyleSheet(
                        f"color:{theme.GRAY};background:transparent;"
                        f"outline:none;")
                    self.pager_row.insertWidget(
                        self.pager_row.count() - 1, lbl)
                last = None
                continue
            self.pager_row.insertWidget(
                self.pager_row.count() - 1,
                _btn(str(p), p, enabled=(p != cur), current=(p == cur)))
            last = p

        self.pager_row.insertWidget(
            self.pager_row.count() - 1,
            _btn(">", cur + 1,
                 enabled=self._has_next and cur + 1 <= total))

    def _go_page(self, page):
        if self._deleted:
            return
        if page < 1:
            return
        if page > self._max_page_seen + (1 if self._has_next else 0):
            return
        if page == self._page:
            return
        self.detail.pid = None
        self.detail.force_close()
        if page in self._page_cache:
            self._render_page_from_cache(page)
        else:
            self._fetch_page(page)

    def _request_visible_icons(self, *args):
        if self._deleted:
            return
        if not self.results_data:
            return
        if not HW.prefetch_icons:
            first = self.list.currentRow()
            if first < 0:
                first = 0
            last = first
        else:
            first = self.list.indexAt(self.list.rect().topLeft()).row()
            last = self.list.indexAt(self.list.rect().bottomLeft()).row()
            if first < 0:
                first = 0
            if last < 0:
                last = len(self.results_data) - 1
            first = max(0, first - HW.icon_prefetch_ahead)
            last = min(len(self.results_data),
                       last + HW.icon_prefetch_ahead + 1)
        for i in range(first, last):
            if i < 0 or i >= len(self.results_data):
                continue
            pid = (self.results_data[i].get("id")
                   or self.results_data[i].get("project_id"))
            if pid:
                try:
                    self.icon_loader.request(pid)
                except RuntimeError:  # noqa: BLE001
                    return

    def _make_row(self, hit, is_installed):
        row = QWidget()
        row.setMinimumHeight(self._row_height())
        row.setSizePolicy(QSizePolicy.Policy.Expanding,
                          QSizePolicy.Policy.Fixed)
        row.setObjectName("modRow")
        row.setStyleSheet(
            f"QWidget#modRow{{background:transparent;"
            f"outline:none;"
            f"}}")
        h = QHBoxLayout(row)
        h.setContentsMargins(self.ROW_PAD, self.ROW_PAD,
                             self.ROW_PAD, self.ROW_PAD)
        h.setSpacing(12)

        ic = QLabel()
        ic.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ic.setAttribute(
            Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        ic.setFixedSize(ICON_SIZE_ROW, ICON_SIZE_ROW)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph = make_placeholder(ICON_SIZE_ROW).pixmap(
            ICON_SIZE_ROW, ICON_SIZE_ROW)
        ic.setPixmap(square_icon_pixmap(ph, ICON_SIZE_ROW))

        ic_host = QWidget()
        ic_host.setStyleSheet("background:transparent;")
        ic_host.setFixedWidth(ICON_SIZE_ROW)
        ic_col = QVBoxLayout(ic_host)
        ic_col.setContentsMargins(0, 0, 0, 0)
        ic_col.setSpacing(0)
        ic_col.addStretch(1)
        ic_col.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)
        ic_col.addStretch(1)
        h.addWidget(ic_host, 0)

        col = QVBoxLayout()
        col.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)

        title = QLabel(self.row_title(hit))
        title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        title.setAttribute(
            Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        title.setStyleSheet(
            f"color:{theme.FG};font-weight:400;font-size:11pt;"
            f"font-family:'{theme.UI_FONT}';background:transparent;"
            f"outline:none;")
        title.setWordWrap(False)
        title.setTextInteractionFlags(
            Qt.TextInteractionFlag.NoTextInteraction)
        title_row.addWidget(title, 1)

        badge = QLabel(translate.t("browse.installed_badge"))
        badge.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        badge.setAttribute(
            Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        badge.setStyleSheet(
            f"color:{theme.ACCENT};font-family:'{theme.UI_FONT}';"
            f"font-size:8pt;font-weight:400;background:transparent;"
            f"outline:none;")
        badge.setVisible(is_installed)
        title_row.addWidget(badge)

        title_row.addStretch(0)
        col.addLayout(title_row)

        meta = QLabel(self.row_subtitle(hit))
        meta.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        meta.setAttribute(
            Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        meta.setStyleSheet(
            f"color:{theme.GRAY};font-size:9pt;"
            f"font-family:'{theme.UI_FONT}';background:transparent;"
            f"outline:none;")
        meta.setWordWrap(False)
        col.addWidget(meta)

        h.addLayout(col, 1)
        row._icon = ic
        row._badge = badge
        return row

    def _on_row_changed(self, row):
        if self._deleted:
            return
        if row < 0 or row >= len(self.results_data):
            return
        self._selected_row = row
        hit = self.results_data[row]
        pid = hit.get("id") or hit.get("project_id")

        key = hit["title"].lower().replace(" ", "")
        installed_keys = self._installed_keys()
        installed = (key in installed_keys
                     or key.replace("_", "") in installed_keys)
        if installed:
            self.install_btn.setEnabled(False)
            self.install_btn.setText(
                translate.t("browse.installed_badge"))
        else:
            self.install_btn.setEnabled(True)
            self.install_btn.setText(
                translate.t("btn.install_selected"))

        if pid:
            try:
                self.icon_loader.request(pid)
            except RuntimeError:  # noqa: BLE001
                return

        self.detail.open_for(hit)
        if pid and HW.enable_icon_cache and pid in _ICON_CACHE:
            self.detail.set_icon(_ICON_CACHE[pid])

        if pid:
            try:
                self.gallery_loader.request(pid)
            except RuntimeError:  # noqa: BLE001
                return

    def _on_icon_ready(self, project_id, icon):
        if self._deleted:
            return
        row = self._rows.get(project_id)
        if row is not None and hasattr(row, "_icon"):
            pm = square_icon(icon, ICON_SIZE_ROW)
            if pm is not None:
                row._icon.setPixmap(pm)
        if self.detail.pid == project_id:
            self.detail.set_icon(icon)

    def _on_shot_ready(self, project_id, idx, pm):
        if self._deleted:
            return
        if self.detail.pid == project_id:
            self.detail.add_screenshot(idx, pm)

    def _selected_hit(self):
        row = self.list.currentRow()
        if row < 0 or row >= len(self.results_data):
            return None
        return self.results_data[row]

    def install_selected(self):
        if self._deleted:
            return
        hit = self._selected_hit()
        if hit is None:
            QMessageBox.information(
                self, translate.t("warn.wait"),
                translate.t("warn.select_row"))
            return
        self.install_btn.setEnabled(False)
        self._log("info", translate.t(
            "console.installing", title=hit["title"]))
        w = Worker(lambda log, progress, progress_end:
                   self._install(hit, progress, progress_end))
        w.log.connect(self._log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self._log("progress", a),
            Qt.ConnectionType.QueuedConnection)
        w.progress_end.connect(
            lambda: None, Qt.ConnectionType.QueuedConnection)
        w.done.connect(
            lambda p: self._install_done(hit, p),
            Qt.ConnectionType.QueuedConnection)
        self._w = w
        w.start()

    def _install(self, hit, progress, progress_end):
        picked = self.pick_download(hit)
        if not picked:
            self._log("warn", translate.t("console.no_compatible"))
            return None
        url, filename = picked
        dest = self.profile.dir / self.folder_name() / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        with http.stream("GET", url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            done = 0
            b0 = 0
            tl = time.time()
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(65536):
                    f.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    if now - tl >= 0.2 or done == total:
                        spd = (done - b0) / (now - tl) if now > tl else 0
                        progress(filename, done, total, "",
                                 self._speed(spd))
                        tl = now
                        b0 = done
        progress_end()
        return str(dest)

    @staticmethod
    def _speed(bps):
        if bps > 1024 * 1024:
            return f"{bps / 1024 / 1024:.1f} MB/s"
        if bps > 1024:
            return f"{bps / 1024:.0f} KB/s"
        return f"{bps:.0f} B/s"

    def _install_done(self, hit, path):
        if self._deleted:
            return
        try:
            self.install_btn.setEnabled(True)
        except RuntimeError:  # noqa: BLE001
            return
        if not path:
            self._log("error", translate.t(
                "console.install_failed", title=hit["title"]))
            return

        self._log("ok", translate.t(
            "console.installed", name=Path(path).name))
        pid = hit.get("id") or hit.get("project_id")
        if pid:
            try:
                self.icon_loader.request(pid)
            except RuntimeError:  # noqa: BLE001, S110
                pass

        row_index = -1
        for i, h in enumerate(self.results_data):
            if (h.get("id") or h.get("project_id")) == pid:
                row_index = i
                break
        if row_index >= 0:
            it = self.list.item(row_index)
            if it is not None:
                it.setData(Qt.ItemDataRole.UserRole + 2, True)
            widget = self._rows.get(pid)
            if widget is not None and hasattr(widget, "_badge"):
                widget._badge.setVisible(True)

        if row_index == self._selected_row:
            self.install_btn.setEnabled(False)
            self.install_btn.setText(
                translate.t("browse.installed_badge"))

        try:
            self.install_finished.emit(path)
        except RuntimeError:  # noqa: BLE001, S110
            pass

    def closeEvent(self, event):
        self._deleted = True
        w = getattr(self, "_w", None)
        if w and w.isRunning():
            try:
                w.log.disconnect()
                w.done.disconnect()
                w.progress.disconnect()
                w.progress_end.disconnect()
            except Exception:  # noqa: BLE001, S110
                pass
            try:
                w.quit()
                w.wait(2000)
            except Exception:  # noqa: BLE001, S110
                pass
            self._w = None
        if self._search_reply is not None:
            try:
                self._search_reply.abort()
                self._search_reply.deleteLater()
            except Exception:  # noqa: BLE001, S110
                pass
            self._search_reply = None
        for loader in (getattr(self, "icon_loader", None),
                       getattr(self, "gallery_loader", None)):
            if loader is None:
                continue
            try:
                if hasattr(loader, "icon_ready"):
                    loader.icon_ready.disconnect()
                if hasattr(loader, "shot_ready"):
                    loader.shot_ready.disconnect()
            except Exception:  # noqa: BLE001, S110
                pass
            try:
                loader._destroyed = True
            except Exception:  # noqa: BLE001, S110
                pass
            try:
                loader.setParent(None)
                loader.deleteLater()
            except Exception:  # noqa: BLE001, S110
                pass
        super().closeEvent(event)
