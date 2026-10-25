from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QPlainTextEdit

from core import theme


class Console(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setFont(QFont(theme.MONO_FONT, 9))
        self.restyle()
        self.setMaximumBlockCount(3000)
        self._last_progress = False
        self._last_line = None

    def restyle(self):
        self.setStyleSheet(
            f"QPlainTextEdit{{background:{theme.BG2};color:{theme.FG};"
            f"border:none;border-radius:0;padding:6px}}")

    def _esc(self, s):
        return (str(s).replace("&", "&amp;")
                       .replace("<", "&lt;")
                       .replace(">", "&gt;"))

    def _write(self, html):
        self.appendHtml(html)
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

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

        color = theme.RED if tag == "error" else (
            theme.YELLOW if tag == "warn" else theme.FG)
        self._write(
            f'<span style="color:{color}">{self._esc(msg)}</span>')
        self._last_progress = False

    def _progress(self, label, cur, total, speed):
        total = max(total, 1)
        pct = cur * 100 / total
        text = f"{label} {pct:5.1f}%"
        if speed:
            text += f"  {speed}"
        html = (f'<span style="color:{theme.ACCENT};font-weight:bold">'
                f'{self._esc(label)}</span> '
                f'<span style="color:{theme.FG}">'
                f'{self._esc(text[len(label):])}</span>')
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
        self.setFont(QFont(theme.MONO_FONT, 8))
        self.restyle()
        self.setMaximumBlockCount(400)
        self._last_line = None

    def restyle(self):
        self.setStyleSheet(
            f"QPlainTextEdit{{background:{theme.BG2};color:{theme.FG};"
            f"border:none;border-radius:0;padding:4px}}")

    def log(self, tag, msg):
        if tag == "progress":
            label, cur, total, _extra, speed = msg
            pct = int(cur * 100 / max(total, 1))
            text = f"{label} {pct}%"
            if speed:
                text += f"  {speed}"
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
