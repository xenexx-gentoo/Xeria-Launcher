import contextlib
import json
import re

from PyQt6.QtCore import Qt, QUrl, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtNetwork import QNetworkRequest
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget,
    QSizePolicy, QTextBrowser, QScrollArea,
)

from core import theme
from core import hardware
from core import translate
from browse.common import DETAIL_WIDTH
from browse.utils import (
    ICON_SIZE_DETAIL, make_placeholder,
    square_icon, square_icon_pixmap, crop_alpha_bbox,
)


HW = hardware.get()

_BODY_CACHE = {}
_BODY_PENDING = set()

_BODY_MAX_LEN = 12000 if HW.tier == "potato" else 40000


def _md_to_html(md):
    if not md:
        return ""
    if len(md) > _BODY_MAX_LEN:
        md = md[:_BODY_MAX_LEN] + "\n\n(description truncated)"
    text = md.replace("\r\n", "\n")

    def _linked(m):
        alt, href = m.group(1), m.group(3)
        return f'<a href="{href}">{alt or href}</a>'
    text = re.sub(r"\[!\[([^\]]*)\]\(([^)]+)\)\]\(([^)]+)\)",
                  _linked, text)

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", "", text)
    text = re.sub(r"<img[^>]*>", "", text, flags=re.I)

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\[\s*\]\([^)]+\)", "", text)

    text = re.sub(r"</?center[^>]*>", "", text, flags=re.I)
    text = re.sub(r"</?div[^>]*>", "", text, flags=re.I)
    text = re.sub(r"</?p[^>]*>", "", text, flags=re.I)

    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)",
                  r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)",
                  r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    text = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", text, flags=re.M)
    text = re.sub(r"^\s*[-*]{3,}\s*$", "<hr>", text, flags=re.M)
    text = text.replace("\n", "<br>")
    return text


class _HScrollArea(QScrollArea):
    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - delta)
        event.accept()


class DetailPanel(QFrame):
    ANIM_MS = 160
    SHOTS_HEIGHT = 180
    THUMB_H = 130

    def __init__(self, parent=None, nam=None):
        super().__init__(parent)
        self.pid = None
        self._anim = None
        self._nam = nam
        self._body_html = ""

        self.setStyleSheet(
            f"QFrame{{background:transparent;outline:none;}}"
            f"QFrame:focus{{outline:none;}}"
            f"QLabel{{background:transparent;color:{theme.FG};"
            f"outline:none;"
            f"font-family:'{theme.UI_FONT}'}}"
            f"QLabel:focus{{outline:none;}}")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header.setStyleSheet(
            "QFrame{background:transparent;outline:none;}")
        header.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        hh = QHBoxLayout(header)
        hh.setContentsMargins(14, 12, 14, 12)
        hh.setSpacing(12)

        self.icon_lbl = QLabel()
        self.icon_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.icon_lbl.setAttribute(
            Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.icon_lbl.setFixedSize(ICON_SIZE_DETAIL, ICON_SIZE_DETAIL)
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_lbl.setStyleSheet(
            "background:transparent;outline:none;")

        ic_host = QWidget()
        ic_host.setStyleSheet("background:transparent;")
        ic_host.setFixedWidth(ICON_SIZE_DETAIL)
        ic_col = QVBoxLayout(ic_host)
        ic_col.setContentsMargins(0, 0, 0, 0)
        ic_col.setSpacing(0)
        ic_col.addStretch(1)
        ic_col.addWidget(self.icon_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        ic_col.addStretch(1)
        hh.addWidget(ic_host, 0)

        text_host = QWidget()
        text_host.setStyleSheet("background:transparent;")
        text_host.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Preferred)
        tcol = QVBoxLayout(text_host)
        tcol.setContentsMargins(0, 0, 0, 0)
        tcol.setSpacing(4)
        tcol.addStretch(1)

        self.title_lbl = QLabel("")
        self.title_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.title_lbl.setAttribute(
            Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setStyleSheet(
            f"color:{theme.FG};font-weight:bold;font-size:14pt;"
            f"background:transparent;outline:none;")
        tcol.addWidget(self.title_lbl)

        self.meta_lbl = QLabel("")
        self.meta_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.meta_lbl.setAttribute(
            Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.meta_lbl.setStyleSheet(
            f"color:{theme.GRAY};font-size:9pt;"
            f"background:transparent;outline:none;")
        tcol.addWidget(self.meta_lbl)
        tcol.addStretch(1)
        hh.addWidget(text_host, 1)
        outer.addWidget(header)

        self.desc_view = QTextBrowser()
        self.desc_view.setOpenExternalLinks(False)
        self.desc_view.setOpenLinks(False)
        self.desc_view.anchorClicked.connect(self._open_link)
        self.desc_view.setFrameShape(QFrame.Shape.NoFrame)
        self.desc_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.desc_view.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.desc_view.viewport().setAutoFillBackground(False)
        self.desc_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.desc_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.desc_view.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Expanding)
        self.desc_view.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.desc_view.setStyleSheet(
            f"QTextBrowser{{background:transparent;color:{theme.FG};"
            f"padding:14px;outline:none;"
            f"font-family:'{theme.UI_FONT}';font-size:10pt}}"
            f"QTextBrowser:focus{{outline:none;}}")
        self.desc_view.document().setDefaultStyleSheet(
            f"a {{ color: {theme.ACCENT}; text-decoration: underline; }}")
        outer.addWidget(self.desc_view, 1)

        self.shots_frame = QFrame()
        self.shots_frame.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.shots_frame.setStyleSheet(
            f"QFrame{{background:transparent;outline:none;"
            f"border:none;}}")
        self.shots_frame.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.shots_frame.setFixedHeight(self.SHOTS_HEIGHT)
        self.shots_frame.setVisible(False)

        sf = QVBoxLayout(self.shots_frame)
        sf.setContentsMargins(0, 0, 0, 0)
        sf.setSpacing(0)

        self.shots_header = QLabel(
            "  " + translate.t("header.screenshots"))
        self.shots_header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.shots_header.setAttribute(
            Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.shots_header.setFixedHeight(22)
        self.shots_header.setStyleSheet(
            f"color:{theme.ACCENT};"
            f"font-family:'{theme.UI_FONT}';font-size:8pt;"
            f"font-weight:bold;letter-spacing:1px;outline:none;"
            f"background:transparent;border:none")
        sf.addWidget(self.shots_header)

        self.shots_scroll = _HScrollArea()
        self.shots_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.shots_scroll.viewport().setFocusPolicy(
            Qt.FocusPolicy.NoFocus)
        self.shots_scroll.setWidgetResizable(True)
        self.shots_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.shots_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.shots_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.shots_scroll.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.shots_scroll.viewport().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.shots_scroll.setStyleSheet(
            "QScrollArea{background:transparent;outline:none;}")

        self.shots_host = QWidget()
        self.shots_host.setStyleSheet(
            "background:transparent;outline:none;")
        self.shots_host.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.shots_row = QHBoxLayout(self.shots_host)
        self.shots_row.setContentsMargins(8, 4, 8, 8)
        self.shots_row.setSpacing(8)
        self.shots_row.addStretch(1)
        self.shots_scroll.setWidget(self.shots_host)
        sf.addWidget(self.shots_scroll, 1)

        outer.addWidget(self.shots_frame)

        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self.setVisible(False)

        for _lbl in self.findChildren(QLabel):
            _lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            _lbl.setAttribute(
                Qt.WidgetAttribute.WA_MacShowFocusRect, False)

    def _open_link(self, url):
        QDesktopServices.openUrl(url)

    def open_for(self, hit):
        self.show_project(hit)
        if not self.isVisible():
            self.setVisible(True)
        self._animate_width(self.maximumWidth(), DETAIL_WIDTH)
        self.desc_view.verticalScrollBar().setValue(0)
        self.shots_scroll.horizontalScrollBar().setValue(0)

    def force_close(self):
        if self._anim is not None:
            with contextlib.suppress(Exception):
                self._anim.stop()
            self._anim = None
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self.setVisible(False)

    def close_panel(self):
        if not self.isVisible():
            return
        self._animate_width(self.maximumWidth(), 0,
                            on_done=self.force_close)

    def _animate_width(self, start, end, on_done=None):
        if self._anim is not None:
            with contextlib.suppress(Exception):
                self._anim.stop()
            self._anim = None
        end = int(end)
        if not getattr(HW, "animations", True):
            if end == 0:
                self.force_close()
            else:
                self.setMinimumWidth(0)
                self.setMaximumWidth(end)
                if on_done:
                    on_done()
            return
        self.setMinimumWidth(0)
        a = QPropertyAnimation(self, b"maximumWidth", self)
        a.setDuration(self.ANIM_MS)
        a.setStartValue(int(start))
        a.setEndValue(end)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        if on_done:
            a.finished.connect(on_done)
        self._anim = a
        a.start()

    def show_project(self, hit):
        self.pid = hit.get("id") or hit.get("project_id")
        self.title_lbl.setText(hit["title"])
        self.meta_lbl.setText(
            translate.t("browse.meta", author=hit["author"]))

        while self.shots_row.count() > 1:
            item = self.shots_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.shots_frame.setVisible(False)

        cached = (_BODY_CACHE.get(self.pid)
                  if HW.enable_body_cache else None)
        if cached is not None:
            self._body_html = cached
        else:
            self._body_html = (
                f'<span style="color:{theme.GRAY}">'
                f'{translate.t("browse.loading_desc")}</span>')

        self._set_icon_pixmap(
            make_placeholder(ICON_SIZE_DETAIL).pixmap(
                ICON_SIZE_DETAIL, ICON_SIZE_DETAIL))

        self.desc_view.setHtml(self._body_html)

        if self.pid and cached is None:
            self._fetch_body(self.pid)

    def _fetch_body(self, pid):
        if HW.enable_body_cache and pid in _BODY_CACHE:
            self._body_html = _BODY_CACHE[pid]
            self.desc_view.setHtml(self._body_html)
            return
        if pid in _BODY_PENDING:
            return
        if self._nam is None:
            return
        _BODY_PENDING.add(pid)

        req = QNetworkRequest(
            QUrl(f"https://api.modrinth.com/v2/project/{pid}"))
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        req.setRawHeader(b"User-Agent", b"Xeria-Launcher/2.504")
        reply = self._nam.get(req)

        def _done():
            status = reply.attribute(
                QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            data = reply.readAll()
            reply.deleteLater()
            _BODY_PENDING.discard(pid)
            if status != 200:
                return
            try:
                body = json.loads(
                    bytes(data).decode("utf-8")).get("body") or ""
            except Exception:  # noqa: BLE001
                return
            html = _md_to_html(body)
            if HW.enable_body_cache:
                _BODY_CACHE[pid] = html
            if self.pid == pid:
                self._body_html = html
                self.desc_view.setHtml(html)

        reply.finished.connect(_done)

    def _set_icon_pixmap(self, pm):
        if pm is None or pm.isNull():
            self.icon_lbl.clear()
            return
        cropped = crop_alpha_bbox(pm)
        canvas = square_icon_pixmap(cropped, ICON_SIZE_DETAIL)
        if canvas is None:
            self.icon_lbl.clear()
            return
        self.icon_lbl.setPixmap(canvas)

    def set_icon(self, icon):
        pm = square_icon(icon, ICON_SIZE_DETAIL)
        if pm is None:
            return
        self.icon_lbl.setPixmap(pm)

    def add_screenshot(self, idx, pm):
        if pm is None:
            return
        th = self.THUMB_H
        tw = int(pm.width() * th / max(1, pm.height()))
        if tw < 60:
            tw = 60
        scaled = pm.scaled(tw, th,
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)

        lbl = QLabel()
        lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lbl.setAttribute(
            Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        lbl.setFixedSize(scaled.width(), scaled.height())
        lbl.setPixmap(scaled)
        lbl.setStyleSheet(
            "background:transparent;outline:none;")

        self.shots_row.insertWidget(self.shots_row.count() - 1, lbl)
        if not self.shots_frame.isVisible():
            self.shots_frame.setVisible(True)
