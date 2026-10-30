import contextlib
import hashlib

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

from core import paths, theme

CACHE_DIR = paths.XERIA_ROOT / "cache" / "loader_icons"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

ICON_SIZE = 20

LOADER_URLS = {
    "vanilla": "https://upload.wikimedia.org/wikipedia/commons/f/fb/"
    "Minecraft-creeper-face.jpg",
    "fabric": "https://fabricmc.net/assets/logo.png",
    "forge": "https://raw.githubusercontent.com/FabricCompatibilityLayers/"
    "art/main/forge.png",
    "neoforge": "https://raw.githubusercontent.com/neoforged/.github/"
    "main/art/neoforged_icon_16x16.png",
    "quilt": "https://quiltmc.org/assets/img/logo.svg",
}

LOADER_LOCAL = {
    "forge": paths.XERIA_ROOT / "icons" / "forge.png",
}

_mem_cache = {}
_nam = None


def _cache_path(name):
    h = hashlib.sha1(name.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.png"


def _scale(pm):
    return pm.scaled(
        ICON_SIZE,
        ICON_SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _placeholder():
    pm = QPixmap(ICON_SIZE, ICON_SIZE)
    pm.fill(QColor(theme.BG3))
    p = QPainter(pm)
    p.setPen(QColor(theme.GRAY))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "?")
    p.end()
    return QIcon(pm)


def _render_svg(data):
    try:
        from PyQt6.QtSvg import QSvgRenderer
    except Exception:  # noqa: BLE001
        return None
    try:
        renderer = QSvgRenderer(bytes(data))
        if not renderer.isValid():
            return None
        pm = QPixmap(ICON_SIZE * 4, ICON_SIZE * 4)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        renderer.render(p)
        p.end()
        return pm
    except Exception:  # noqa: BLE001
        return None


def _decode(data):
    pm = QPixmap()
    if pm.loadFromData(data) and not pm.isNull():
        return pm
    return _render_svg(data)


def loader_icon_sync(name):
    if name in _mem_cache:
        return _mem_cache[name]

    local = LOADER_LOCAL.get(name)
    if local and local.exists():
        pm = QPixmap(str(local))
        if not pm.isNull():
            ic = QIcon(_scale(pm))
            _mem_cache[name] = ic
            return ic

    cp = _cache_path(name)
    if cp.exists():
        pm = QPixmap(str(cp))
        if not pm.isNull():
            ic = QIcon(_scale(pm))
            _mem_cache[name] = ic
            return ic

    return None


def fetch_loader_icon(name, callback):
    ic = loader_icon_sync(name)
    if ic is not None:
        callback(ic)
        return

    local = LOADER_LOCAL.get(name)
    if local and local.exists():
        pm = QPixmap(str(local))
        if not pm.isNull():
            ic = QIcon(_scale(pm))
            _mem_cache[name] = ic
            callback(ic)
            return

    url = LOADER_URLS.get(name)
    if not url:
        callback(_placeholder())
        return

    global _nam
    if _nam is None:
        _nam = QNetworkAccessManager()

    req = QNetworkRequest(QUrl(url))
    req.setAttribute(
        QNetworkRequest.Attribute.RedirectPolicyAttribute,
        QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
    )
    req.setRawHeader(b"User-Agent", b"Mozilla/5.0 (X11; Linux x86_64) Xeria/2.504")
    req.setRawHeader(b"Accept", b"image/*,*/*;q=0.8")
    reply = _nam.get(req)
    cp = _cache_path(name)

    def done(r=reply, nm=name, path=cp, src=url):
        if r.error() != QNetworkReply.NetworkError.NoError:
            r.deleteLater()
            callback(_placeholder())
            return

        data = r.readAll()
        r.deleteLater()

        if not data:
            callback(_placeholder())
            return

        pm = _decode(data)
        if pm is None or pm.isNull():
            callback(_placeholder())
            return

        scaled = _scale(pm)
        with contextlib.suppress(Exception):
            scaled.save(str(path), "PNG")
        ic = QIcon(scaled)
        _mem_cache[nm] = ic
        callback(ic)

    reply.finished.connect(done)


def fetch_all_loaders(callback):
    for name in LOADER_URLS:
        fetch_loader_icon(name, lambda ic, n=name: callback(n, ic))
