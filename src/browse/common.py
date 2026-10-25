import io
import json
import hashlib
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QTimer, QUrl, QObject, pyqtSignal, QRunnable, QThreadPool, pyqtSlot,
)
from PyQt6.QtGui import (
    QColor, QIcon, QPixmap, QPainter, QPainterPath, QImage,
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from core import theme
from core import hardware

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


ICON_SIZE = 32
ICON_SIZE_ROW = 48
ICON_SIZE_DETAIL = 96
SHOT_W = 200
SHOT_H = 112
DETAIL_WIDTH = 400

HW = hardware.get()

CACHE_DIR = Path.home() / ".cache" / "mc_launcher" / "icons"
if HW.enable_disk_cache:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

CDN_BASE = "https://cdn.modrinth.com/data/{id}/icon.png"
API_BASE = "https://api.modrinth.com/v2/project/{id}"

_ICON_CACHE = {}
_HASH_CACHE = {}


def _pid_hash(pid):
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
        except Exception:
            pass
    return None


def _crop_alpha_bbox(pm):
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
    src = _crop_alpha_bbox(src)
    return square_icon_pixmap(src, side)


# ---- Icon decoding (square, for list rows / detail header) ----------------

class _DecodeTask(QRunnable):
    def __init__(self, loader, project_id, path, data):
        super().__init__()
        self.loader = loader
        self.project_id = project_id
        self.path = path
        self.data = bytes(data)
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        pm = decode_image(self.data)
        if pm is None or pm.isNull():
            self.loader._decode_done.emit(self.project_id, None, self.path)
            return
        cropped = _crop_alpha_bbox(pm)
        out = square_icon_pixmap(cropped, ICON_SIZE_DETAIL)
        self.loader._decode_done.emit(self.project_id, out, self.path)


class IconLoader(QObject):
    icon_ready = pyqtSignal(str, QIcon)
    _decode_done = pyqtSignal(str, object, object)

    MAX_PARALLEL = HW.icon_max_parallel
    MAX_ATTEMPTS = 2

    def __init__(self, parent=None, nam=None):
        super().__init__(parent)
        self.nam = nam or QNetworkAccessManager(self)
        self._queue = []
        self._active = {}
        self._inflight = set()
        self._cache = _ICON_CACHE if HW.enable_icon_cache else {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(HW.icon_decode_threads)
        self._decode_done.connect(self._on_decode_done)
        self._destroyed = False

    def request(self, project_id):
        if self._destroyed:
            return
        if not project_id:
            return
        if HW.enable_icon_cache and project_id in self._cache:
            try:
                self.icon_ready.emit(project_id, self._cache[project_id])
            except RuntimeError:
                pass
            return
        if project_id in self._inflight:
            return
        if HW.enable_disk_cache:
            h = _pid_hash(project_id)
            path = CACHE_DIR / f"{h}.png"
            if path.exists():
                pm = QPixmap(str(path))
                if not pm.isNull():
                    ic = QIcon(pm)
                    if HW.enable_icon_cache:
                        self._cache[project_id] = ic
                    try:
                        self.icon_ready.emit(project_id, ic)
                    except RuntimeError:
                        pass
                    return
        else:
            path = None
        self._inflight.add(project_id)
        self._queue.append((project_id, path, 0))
        self._pump()

    def _pump(self):
        if self._destroyed:
            return
        while len(self._active) < self.MAX_PARALLEL and self._queue:
            project_id, path, attempt = self._queue.pop(0)
            url = CDN_BASE.format(id=project_id)
            req = QNetworkRequest(QUrl(url))
            req.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
            if HW.enable_disk_cache:
                req.setAttribute(
                    QNetworkRequest.Attribute.CacheLoadControlAttribute,
                    QNetworkRequest.CacheLoadControl.PreferCache)
            req.setRawHeader(b"User-Agent", b"Xeria-Launcher/2.504")
            reply = self.nam.get(req)
            self._active[reply] = [project_id, path, attempt, False]
            reply.finished.connect(lambda r=reply: self._on_cdn_finished(r))

    def _consume(self, reply):
        if self._destroyed:
            try:
                reply.deleteLater()
            except Exception:
                pass
            return None, None, None
        meta = self._active.pop(reply, None)
        if meta is None:
            try:
                reply.deleteLater()
            except Exception:
                pass
            return None, None, None
        status = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        err = reply.error()
        data = reply.readAll()
        reply.deleteLater()
        return meta, status, (err, data)

    def _dispatch_decode(self, project_id, path, data):
        if self._destroyed:
            return
        self._pool.start(_DecodeTask(self, project_id, path, data))

    def _on_decode_done(self, project_id, pm, path):
        if self._destroyed:
            return
        self._inflight.discard(project_id)
        if pm is None or pm.isNull():
            ph = make_placeholder(ICON_SIZE_DETAIL)
            if HW.enable_icon_cache:
                self._cache[project_id] = ph
            try:
                self.icon_ready.emit(project_id, ph)
            except RuntimeError:
                pass
            return
        ic = QIcon(pm)
        if HW.enable_icon_cache:
            self._cache[project_id] = ic
        if HW.enable_disk_cache and path is not None:
            try:
                pm.save(str(path), "PNG")
            except Exception:
                pass
        try:
            self.icon_ready.emit(project_id, ic)
        except RuntimeError:
            pass

    def _backoff(self, project_id, path, attempt):
        if self._destroyed:
            return False
        if attempt >= self.MAX_ATTEMPTS:
            return False
        delay = 800 * (2 ** attempt)
        QTimer.singleShot(
            delay,
            lambda pid=project_id, p=path, a=attempt + 1:
                self._retry(pid, p, a))
        return True

    def _retry(self, project_id, path, attempt):
        if self._destroyed:
            return
        self._queue.append((project_id, path, attempt))
        self._pump()

    def _emit_placeholder(self, project_id):
        if self._destroyed:
            return
        self._inflight.discard(project_id)
        ph = make_placeholder(ICON_SIZE_DETAIL)
        if HW.enable_icon_cache:
            self._cache[project_id] = ph
        try:
            self.icon_ready.emit(project_id, ph)
        except RuntimeError:
            pass

    def _on_cdn_finished(self, reply):
        if self._destroyed:
            try:
                reply.deleteLater()
            except Exception:
                pass
            return
        meta, status, payload = self._consume(reply)
        if meta is None:
            self._pump()
            return
        project_id, path, attempt, tried_api = meta
        err, data = payload
        if err == QNetworkReply.NetworkError.NoError and status == 200:
            self._dispatch_decode(project_id, path, data)
            self._pump()
            return
        if status in (429, 503) or (status and 500 <= status < 600):
            if self._backoff(project_id, path, attempt):
                self._pump()
                return
            self._emit_placeholder(project_id)
            self._pump()
            return
        if not tried_api:
            self._fetch_via_api(project_id, path, attempt)
            return
        self._emit_placeholder(project_id)
        self._pump()

    def _fetch_via_api(self, project_id, path, attempt):
        if self._destroyed:
            return
        api = API_BASE.format(id=project_id)
        req = QNetworkRequest(QUrl(api))
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        req.setRawHeader(b"User-Agent", b"Xeria-Launcher/2.504")
        reply = self.nam.get(req)
        self._active[reply] = [project_id, path, attempt, True]
        reply.finished.connect(lambda r=reply: self._on_api_finished(r))

    def _on_api_finished(self, reply):
        if self._destroyed:
            try:
                reply.deleteLater()
            except Exception:
                pass
            return
        meta, status, payload = self._consume(reply)
        if meta is None:
            self._pump()
            return
        project_id, path, attempt, _ = meta
        err, data = payload
        if status in (429, 503) or (status and 500 <= status < 600):
            if self._backoff(project_id, path, attempt):
                self._pump()
                return
            self._emit_placeholder(project_id)
            self._pump()
            return
        if err != QNetworkReply.NetworkError.NoError:
            self._emit_placeholder(project_id)
            self._pump()
            return
        try:
            info = json.loads(bytes(data).decode("utf-8"))
            icon_url = info.get("icon_url")
        except Exception:
            icon_url = None
        if not icon_url:
            self._emit_placeholder(project_id)
            self._pump()
            return
        req = QNetworkRequest(QUrl(icon_url))
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        req.setRawHeader(b"User-Agent", b"Xeria-Launcher/2.504")
        rep = self.nam.get(req)
        self._active[rep] = [project_id, path, attempt, True]
        rep.finished.connect(lambda r=rep: self._on_icon_finished(r))

    def _on_icon_finished(self, reply):
        if self._destroyed:
            try:
                reply.deleteLater()
            except Exception:
                pass
            return
        meta, status, payload = self._consume(reply)
        if meta is None:
            self._pump()
            return
        project_id, path, attempt, _ = meta
        err, data = payload
        if err == QNetworkReply.NetworkError.NoError and status == 200:
            self._dispatch_decode(project_id, path, data)
            self._pump()
            return
        self._emit_placeholder(project_id)
        self._pump()


# ---- Gallery (screenshots) ------------------------------------------------

def decode_screenshot(data):
    """Decode a screenshot at full colour, no cropping, no squaring."""
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
        except Exception:
            pass
    return None


class _ShotDecodeFull(QRunnable):
    def __init__(self, loader, pid, idx, data):
        super().__init__()
        self.loader = loader
        self.pid = pid
        self.idx = idx
        self.data = bytes(data)
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        pm = decode_screenshot(self.data)
        self.loader._decode_done.emit(self.pid, self.idx, pm)


class GalleryLoader(QObject):
    shot_ready = pyqtSignal(str, int, object)
    _decode_done = pyqtSignal(str, int, object)

    MAX_SHOTS = HW.gallery_max_shots

    def __init__(self, parent=None, nam=None):
        super().__init__(parent)
        self.nam = nam or QNetworkAccessManager(self)
        self._requested = set()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(HW.gallery_decode_threads)
        self._decode_done.connect(self._on_decode_done)
        self._destroyed = False

    def request(self, project_id):
        if self._destroyed:
            return
        if not project_id or project_id in self._requested:
            return
        self._requested.add(project_id)
        req = QNetworkRequest(QUrl(API_BASE.format(id=project_id)))
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        req.setRawHeader(b"User-Agent", b"Xeria-Launcher/2.504")
        reply = self.nam.get(req)
        reply.finished.connect(
            lambda r=reply, pid=project_id: self._on_meta(r, pid))

    def _on_meta(self, reply, pid):
        if self._destroyed:
            try:
                reply.deleteLater()
            except Exception:
                pass
            return
        status = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        err = reply.error()
        data = reply.readAll()
        reply.deleteLater()
        if err != QNetworkReply.NetworkError.NoError or status != 200:
            return
        try:
            info = json.loads(bytes(data).decode("utf-8"))
        except Exception:
            return
        gallery = info.get("gallery") or []
        urls = []
        for g in gallery:
            u = g.get("url") or g.get("raw_url")
            if u:
                urls.append(u)
            if len(urls) >= self.MAX_SHOTS:
                break
        for i, url in enumerate(urls):
            if self._destroyed:
                return
            req = QNetworkRequest(QUrl(url))
            req.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
            req.setRawHeader(b"User-Agent", b"Xeria-Launcher/2.504")
            rep = self.nam.get(req)
            rep.finished.connect(
                lambda r=rep, p=pid, idx=i: self._on_image(r, p, idx))

    def _on_image(self, reply, pid, idx):
        if self._destroyed:
            try:
                reply.deleteLater()
            except Exception:
                pass
            return
        status = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        err = reply.error()
        data = reply.readAll()
        reply.deleteLater()
        if err != QNetworkReply.NetworkError.NoError or status != 200:
            try:
                self.shot_ready.emit(pid, idx, None)
            except RuntimeError:
                pass
            return
        if self._destroyed:
            return
        self._pool.start(_ShotDecodeFull(self, pid, idx, data))

    def _on_decode_done(self, pid, idx, pm):
        if self._destroyed:
            return
        try:
            self.shot_ready.emit(pid, idx, pm)
        except RuntimeError:
            pass
