import hashlib
import io

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QColor, QIcon, QPixmap, QPainter, QPainterPath, QImage,
)

from core import theme


ICON_SIZE = 32
ICON_SIZE_ROW = 48
ICON_SIZE_DETAIL = 96

_HASH_CACHE = {}

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:  # noqa: BLE001
    _HAS_PIL = False


def pid_hash(pid):
    h = _HASH_CACHE.get(pid)
    if h is None:
        h = hashlib.sha1(pid.encode()).hexdigest()[:16]
        _HASH_CACHE[pid] = h
    return h


def make_placeholder(size=ICON_SIZE):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, 4, 4)
    p.fillPath(path, QColor(theme.BG3))
    p.setPen(QColor(theme.GRAY))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "?")
    p.end()
    return QIcon(pm)


def decode_image(data):
    if not data:
        return None
    pm = QPixmap()
    if pm.loadFromData(data) and not pm.isNull():
        return pm
    if _HAS_PIL:
        try:
            img = Image.open(io.BytesIO(bytes(data))).convert("RGBA")
            qimg = QImage(img.tobytes(), img.width, img.height,
                          QImage.Format.Format_RGBA8888).copy()
            pm2 = QPixmap.fromImage(qimg)
            if not pm2.isNull():
                return pm2
        except Exception:  # noqa: BLE001, S110
            pass
    return None


def decode_screenshot(data):
    if not data:
        return None
    pm = QPixmap()
    if pm.loadFromData(data) and not pm.isNull():
        return pm
    if _HAS_PIL:
        try:
            img = Image.open(io.BytesIO(bytes(data))).convert("RGBA")
            qimg = QImage(img.tobytes(), img.width, img.height,
                          QImage.Format.Format_RGBA8888).copy()
            pm2 = QPixmap.fromImage(qimg)
            if not pm2.isNull():
                return pm2
        except Exception:  # noqa: BLE001, S110
            pass
    return None


def crop_alpha_bbox(pm):
    if pm is None or pm.isNull():
        return pm
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    if w == 0 or h == 0:
        return pm
    ptr = img.bits()
    ptr.setsize(img.sizeInBytes())
    buf = bytes(ptr)
    bpl = img.bytesPerLine()
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        row = y * bpl
        for x in range(w):
            if buf[row + x * 4 + 3] > 8:
                if x < minx: minx = x
                if y < miny: miny = y
                if x > maxx: maxx = x
                if y > maxy: maxy = y
    if maxx < 0:
        return pm
    return pm.copy(minx, miny, maxx - minx + 1, maxy - miny + 1)


def square_icon_pixmap(src, side):
    if src is None or src.isNull():
        return None
    w, h = src.width(), src.height()
    if w <= 0 or h <= 0:
        return None
    if w != h:
        s = min(w, h)
        x = (w - s) // 2
        y = (h - s) // 2
        src = src.copy(x, y, s, s)
    canvas = QPixmap(side, side)
    canvas.fill(Qt.GlobalColor.transparent)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scaled = src.scaled(side, side,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
    p.drawPixmap(0, 0, scaled)
    p.end()
    return canvas


def square_icon(icon, side):
    if icon is None or icon.isNull():
        return None
    sizes = icon.availableSizes()
    if sizes:
        biggest = max(sizes, key=lambda s: s.width() * s.height())
        src = icon.pixmap(biggest)
    else:
        src = icon.pixmap(side, side)
    if src.isNull():
        return None
    src = crop_alpha_bbox(src)
    return square_icon_pixmap(src, side)
