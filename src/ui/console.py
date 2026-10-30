from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPalette,
    QTextCharFormat,
)
from PyQt6.QtWidgets import QPlainTextEdit

from core import theme

_MONO_CANDIDATES = (
    "JetBrains Mono",
    "Fira Code",
    "Cascadia Code",
    "Cascadia Mono",
    "SF Mono",
    "Menlo",
    "Consolas",
    "Source Code Pro",
    "IBM Plex Mono",
    "Ubuntu Mono",
    "DejaVu Sans Mono",
)


def _pick_mono(size, weight=QFont.Weight.Normal):
    try:
        families = set(QFontDatabase.families())
    except Exception:  # noqa: BLE001
        families = set()
    for name in _MONO_CANDIDATES:
        if name in families:
            f = QFont(name, size)
            f.setWeight(weight)
            f.setStyleHint(QFont.StyleHint.Monospace)
            f.setFixedPitch(True)
            return f
    f = QFont(theme.MONO_FONT, size)
    f.setWeight(weight)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFixedPitch(True)
    return f


class Console(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setFont(_pick_mono(9))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.document().setDocumentMargin(0)
        self.restyle()
        self.setMaximumBlockCount(3000)
        self._last_progress = False
        self._last_line = None

    def restyle(self):
        fg = QColor(theme.FG)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.Text, fg)
        pal.setColor(QPalette.ColorRole.WindowText, fg)
        self.setPalette(pal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFont(_pick_mono(9))
        self.setStyleSheet(
            f"QPlainTextEdit{{background:transparent;color:{theme.FG};"
            f"border:none;border-radius:0;padding:0;"
            f"selection-background-color:{theme.ACCENT};"
            f"selection-color:{theme.accent_text()};"
            f"letter-spacing:0.2px}}"
        )
        self.document().setDefaultStyleSheet(
            f"body{{color:{theme.FG};background:transparent}}"
        )
        self.document().setDocumentMargin(0)
        self.viewport().setAutoFillBackground(False)
        fmt = QTextCharFormat()
        fmt.setForeground(fg)
        cursor = self.textCursor()
        cursor.select(cursor.SelectionType.Document)
        cursor.mergeCharFormat(fmt)
        cursor.clearSelection()
        cursor.movePosition(cursor.MoveOperation.End)
        self.setTextCursor(cursor)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        c = self.textCursor()
        if c.hasSelection():
            c.clearSelection()
            c.movePosition(c.MoveOperation.End)
            self.setTextCursor(c)

    def _esc(self, s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _write(self, html):
        self.appendHtml(html)
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())
        c = self.textCursor()
        if c.hasSelection():
            c.clearSelection()
            c.movePosition(c.MoveOperation.End)
            self.setTextCursor(c)

    def log(self, tag, msg):
        if tag == "progress":
            label, cur, total, _extra, speed = msg
            self._progress(label, cur, total, speed)
            return
        if tag == "progress_end":
            self._last_progress = False
            return

        key = (tag, str(msg))
        if key == self._last_line:
            return
        self._last_line = key

        color = (
            theme.RED
            if tag == "error"
            else (theme.YELLOW if tag == "warn" else theme.FG)
        )

        prefix = ""
        if tag in (
            "ok",
            "error",
            "warn",
            "sys",
            "net",
            "java",
            "mc",
            "py",
            "pip",
            "fs",
            "venv",
        ):
            tag_color = theme.ACCENT if tag in ("ok", "sys", "net") else color
            prefix = (
                f'<span style="color:{tag_color};'
                f'font-weight:400;letter-spacing:0.5px">'
                f"[{self._esc(tag)}] </span>"
            )

        self._write(f'{prefix}<span style="color:{color}">{self._esc(msg)}</span>')
        self._last_progress = False

    def _progress(self, label, cur, total, speed):
        total = max(total, 1)
        pct = cur * 100 / total
        text = f"{pct:5.1f}%"
        if speed:
            text += f"  ·  {speed}"
        html = (
            f'<span style="color:{theme.ACCENT};font-weight:400;'
            f'letter-spacing:0.5px">{self._esc(label)}</span>  '
            f'<span style="color:{theme.FG};opacity:0.8">'
            f"{self._esc(text)}</span>"
        )
        if self._last_progress:
            c = self.textCursor()
            c.movePosition(c.MoveOperation.End)
            c.select(c.SelectionType.BlockUnderCursor)
            c.removeSelectedText()
            c.deletePreviousChar()
        self._write(html)
        self._last_progress = True


class MiniConsole(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(_pick_mono(8))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.document().setDocumentMargin(0)
        self.restyle()
        self.setMaximumBlockCount(400)
        self._last_line = None

    def restyle(self):
        fg = QColor(theme.FG)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.Text, fg)
        pal.setColor(QPalette.ColorRole.WindowText, fg)
        self.setPalette(pal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFont(_pick_mono(8))
        self.setStyleSheet(
            f"QPlainTextEdit{{background:transparent;color:{theme.FG};"
            f"border:none;border-radius:0;padding:0;"
            f"letter-spacing:0.2px}}"
        )
        self.document().setDocumentMargin(0)
        self.viewport().setAutoFillBackground(False)
        fmt = QTextCharFormat()
        fmt.setForeground(fg)
        cursor = self.textCursor()
        cursor.select(cursor.SelectionType.Document)
        cursor.mergeCharFormat(fmt)
        cursor.clearSelection()
        cursor.movePosition(cursor.MoveOperation.End)
        self.setTextCursor(cursor)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        c = self.textCursor()
        if c.hasSelection():
            c.clearSelection()
            c.movePosition(c.MoveOperation.End)
            self.setTextCursor(c)

    def log(self, tag, msg):
        if tag == "progress":
            label, cur, total, _extra, speed = msg
            pct = int(cur * 100 / max(total, 1))
            text = f"{label} {pct}%"
            if speed:
                text += f"  ·  {speed}"
            self.appendPlainText(text)
        elif tag == "progress_end":
            return
        else:
            key = (tag, str(msg))
            if key == self._last_line:
                return
            self._last_line = key
            self.appendPlainText(str(msg))
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())
        c = self.textCursor()
        if c.hasSelection():
            c.clearSelection()
            c.movePosition(c.MoveOperation.End)
            self.setTextCursor(c)
