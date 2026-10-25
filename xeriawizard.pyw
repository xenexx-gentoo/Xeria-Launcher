#!/usr/bin/env python3
import json
import locale
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import urllib.request
import venv
import webbrowser
import zipfile
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit, QProgressBar, QMessageBox,
    QDialog, QLineEdit,
)


_STRINGS = {
    "en": {
        "title": "Xeria Launcher",
        "subtitle": "Installation wizard",
        "install": "Install",
        "installing": "Installing...",
        "retry": "Retry",
        "done": "Done",
        "close": "Close",
        "quit_title": "Quit",
        "quit_msg": "Installation is still running. Quit anyway?",
        "fail_title": "Installation failed",
        "pass_title": "Authentication required",
        "pass_prompt": "Administrator privileges are needed to install system packages.\nEnter your password to continue (or Cancel to skip):",
        "pass_placeholder": "password",
        "cancel": "Cancel",
        "ok": "OK",
        "install_ok_title": "Xeria Launcher is installed.",
        "install_hint_win": "Launch from Start Menu or Desktop shortcut",
        "install_hint_launch": "Launch: {cmd}",
        "install_hint_apps": "Or open it from your application menu",
        "install_hint_close": "Feel free to close this window.",
        "install_info": "",
        "platform": "platform {os} {rel}",
        "python": "python {v}",
        "ssl": "ssl backend {m}",
        "install_dir": "install dir {d}",
        "start": "Click Install to begin",
        "ssl_unverified_warn": "using unverified SSL context for bootstrap",
        "ssl_fix_warn": "install 'truststore' or 'certifi' to fix this",
        "no_python": "no usable Python >= {a}.{b} found",
        "using_python": "using existing interpreter {p}",
        "python_still_missing": "Python still not available",
        "cancelled": "cancelled",
        "selected_python": "selected {p} ({a}.{b})",
        "python_too_old": "{p} -> {a}.{b} (too old)",
        "python_unusable": "{p} -> unusable, skipping",
        "python_store_stub": "{p} -> Microsoft Store stub, skipping",
        "python_no_venv": "{p} -> no venv/ensurepip, skipping",
        "python_found": "{p} -> {a}.{b}",
        "python_query": "querying python.org for latest stable release",
        "python_api_failed": "python.org API failed: {e}",
        "python_api_parse_failed": "python.org API parse failed: {e}",
        "python_latest": "latest stable: Python {a}.{b}.{c}",
        "python_no_stable": "no stable 3.x release found in API response",
        "python_installing": "no usable local Python found — installing new one",
        "python_downloading": "downloading Python {a}.{b}.{c}",
        "python_installed_at": "python installed at {p}",
        "python_path_missing": "python installed but not on PATH, restart shell",
        "python_installer_failed": "python installer failed: {e}",
        "python_no_pm": "no supported package manager for Python install",
        "python_no_installer": "no installer URL for {os}",
        "python_pm_ok": "python installed via package manager",
        "python_pm_fail": "python install failed: {e}",
        "python_pm_abort": "python install aborted: {e}",
        "python_unknown_version": "could not determine latest Python version",
        "python_no_auto": "no auto-install path for {os}",
        "pkgs_ok": "all system packages already installed",
        "pkgs_missing": "missing system packages: {list}",
        "pkgs_installed": "system packages installed",
        "pkgs_skipped": "system package install skipped (no sudo password)",
        "pkgs_hint": "install manually if QtWebEngine fails: {cmd}",
        "pkgs_failed": "system package install failed: {e}",
        "no_pm": "no supported package manager found",
        "repo_removing": "removing old install dir {d}",
        "repo_removed": "old install dir removed",
        "repo_downloading": "GET {url}  (ssl: {m})",
        "repo_downloaded": "download done, saved {p}",
        "repo_extracting": "extracting {p}",
        "repo_moving": "moving {src} -> {dst}",
        "repo_ready": "repository ready at {d}",
        "repo_verify": "layout verified (core/ui/instances/browse/integration)",
        "repo_download_failed": "download failed: {e}",
        "repo_fetch_failed": "could not fetch repository archive",
        "repo_no_dirs": "archive contained no directories",
        "repo_layout_bad": "repository layout unexpected — missing: {list}",
        "venv_removing": "removing old venv at {d}",
        "venv_removed": "old venv removed",
        "venv_creating": "creating new venv at {d}",
        "venv_system_site": "linux: system_site_packages=True (uses distro PyQt6)",
        "venv_created": "virtualenv created",
        "venv_create_failed": "venv.create failed: {e}",
        "venv_python_missing": "venv python missing: {p}",
        "pip_bootstrap": "upgrading pip / setuptools / wheel",
        "pip_bootstrap_failed": "pip bootstrap failed: {e}",
        "pip_skip_linux": "linux: skipping PyQt6/PyQt6-WebEngine/PyOpenGL (using system packages)",
        "pip_install": "install {pkg}",
        "pip_installed": "{pkg} installed",
        "pip_failed": "pip install failed for {pkg}: {e}",
        "pip_done": "python dependencies installed",
        "gl_probing": "probing OpenGL",
        "gl_vendor": "GL vendor:   {v}",
        "gl_renderer": "GL renderer: {v}",
        "gl_version": "GL version:  {v}",
        "gl_unknown": "(unknown)",
        "gl_probe_crashed": "GL probe crashed: {e}",
        "gl_cannot_query": "could not query OpenGL version",
        "gl_cannot_parse": "could not parse OpenGL version",
        "gl_below_min": "OpenGL {a}.{b} is below the minimum {c}.{d}",
        "gl_meets": "OpenGL {a}.{b} meets minimum {c}.{d}",
        "gl_win_hint": "Opening Microsoft Store — install your GPU vendor's companion app and let it update the driver, or run Windows Update.",
        "gl_win_store_fail": "could not open store: {e}",
        "gl_linux_hint": "install your distro's mesa/vulkan/opencl packages",
        "gl_other_hint": "update your GPU driver from your system settings",
        "desktop_entry": "desktop entry -> {p}",
        "desktop_shortcut": "desktop shortcut -> {p}",
        "desktop_failed": "desktop shortcut failed: {e}",
        "startmenu_shortcut": "start menu shortcut -> {p}",
        "shortcut_failed": "desktop shortcut failed: {e}",
        "no_shortcut": "unsupported platform, no shortcut created",
        "fatal": "fatal: {e}",
        "run": "run {cmd}",
        "install_complete": "Installation complete.",
        "python_install_ok": "python installed via package manager",
    },
    "ru": {
        "title": "Xeria Launcher",
        "subtitle": "Мастер установки",
        "install": "Установить",
        "installing": "Устанавливаю...",
        "retry": "Повторить",
        "done": "Готово",
        "close": "Закрыть",
        "quit_title": "Выход",
        "quit_msg": "Установка ещё идёт. Всё равно выйти?",
        "fail_title": "Установка не удалась",
        "pass_title": "Требуется авторизация",
        "pass_prompt": "Для установки системных пакетов нужны права администратора.\nВведите пароль для продолжения (или Отмена, чтобы пропустить):",
        "pass_placeholder": "пароль",
        "cancel": "Отмена",
        "ok": "ОК",
        "install_ok_title": "Xeria Launcher установлен.",
        "install_hint_win": "Запуск из меню Пуск или с ярлыка на рабочем столе",
        "install_hint_launch": "Запуск: {cmd}",
        "install_hint_apps": "Или откройте из меню приложений",
        "install_hint_close": "Можете закрыть это окно.",
        "install_info": "",
        "platform": "платформа {os} {rel}",
        "python": "python {v}",
        "ssl": "ssl backend {m}",
        "install_dir": "папка установки {d}",
        "start": "Нажмите Установить, чтобы начать",
        "ssl_unverified_warn": "используется непроверенный SSL-контекст",
        "ssl_fix_warn": "установите 'truststore' или 'certifi' для исправления",
        "no_python": "подходящий Python >= {a}.{b} не найден",
        "using_python": "использую существующий интерпретатор {p}",
        "python_still_missing": "Python всё ещё недоступен",
        "cancelled": "отменено",
        "selected_python": "выбран {p} ({a}.{b})",
        "python_too_old": "{p} -> {a}.{b} (слишком старый)",
        "python_unusable": "{p} -> непригоден, пропускаю",
        "python_store_stub": "{p} -> заглушка Microsoft Store, пропускаю",
        "python_no_venv": "{p} -> нет venv/ensurepip, пропускаю",
        "python_found": "{p} -> {a}.{b}",
        "python_query": "запрашиваю python.org о последней стабильной версии",
        "python_api_failed": "python.org API: {e}",
        "python_api_parse_failed": "разбор ответа python.org: {e}",
        "python_latest": "последняя стабильная: Python {a}.{b}.{c}",
        "python_no_stable": "в ответе API нет стабильного 3.x",
        "python_installing": "подходящий Python не найден — устанавливаю новый",
        "python_downloading": "скачиваю Python {a}.{b}.{c}",
        "python_installed_at": "python установлен в {p}",
        "python_path_missing": "python установлен, но не в PATH — перезапустите оболочку",
        "python_installer_failed": "установщик python: {e}",
        "python_no_pm": "нет поддерживаемого менеджера пакетов для Python",
        "python_no_installer": "нет URL установщика для {os}",
        "python_pm_ok": "python установлен менеджером пакетов",
        "python_pm_fail": "установка python: {e}",
        "python_pm_abort": "установка python прервана: {e}",
        "python_unknown_version": "не удалось определить последнюю версию Python",
        "python_no_auto": "для {os} нет авто-установки",
        "pkgs_ok": "все системные пакеты уже установлены",
        "pkgs_missing": "не хватает системных пакетов: {list}",
        "pkgs_installed": "системные пакеты установлены",
        "pkgs_skipped": "установка системных пакетов пропущена (нет пароля sudo)",
        "pkgs_hint": "установите вручную, если QtWebEngine не работает: {cmd}",
        "pkgs_failed": "установка системных пакетов: {e}",
        "no_pm": "менеджер пакетов не найден",
        "repo_removing": "удаляю старую папку установки {d}",
        "repo_removed": "старая папка удалена",
        "repo_downloading": "GET {url}  (ssl: {m})",
        "repo_downloaded": "скачивание готово, сохранено {p}",
        "repo_extracting": "распаковываю {p}",
        "repo_moving": "перемещаю {src} -> {dst}",
        "repo_ready": "репозиторий готов: {d}",
        "repo_verify": "структура проверена (core/ui/instances/browse/integration)",
        "repo_download_failed": "скачивание не удалось: {e}",
        "repo_fetch_failed": "не удалось получить архив репозитория",
        "repo_no_dirs": "в архиве нет папок",
        "repo_layout_bad": "неожиданная структура репозитория — нет: {list}",
        "venv_removing": "удаляю старое виртуальное окружение {d}",
        "venv_removed": "старое окружение удалено",
        "venv_creating": "создаю виртуальное окружение {d}",
        "venv_system_site": "linux: system_site_packages=True (использует системный PyQt6)",
        "venv_created": "виртуальное окружение создано",
        "venv_create_failed": "venv.create: {e}",
        "venv_python_missing": "python окружения отсутствует: {p}",
        "pip_bootstrap": "обновляю pip / setuptools / wheel",
        "pip_bootstrap_failed": "bootstrap pip: {e}",
        "pip_skip_linux": "linux: пропускаю PyQt6/PyQt6-WebEngine/PyOpenGL (системные пакеты)",
        "pip_install": "устанавливаю {pkg}",
        "pip_installed": "{pkg} установлен",
        "pip_failed": "pip install {pkg}: {e}",
        "pip_done": "зависимости Python установлены",
        "gl_probing": "проверяю OpenGL",
        "gl_vendor": "GL vendor:   {v}",
        "gl_renderer": "GL renderer: {v}",
        "gl_version": "GL version:  {v}",
        "gl_unknown": "(неизвестно)",
        "gl_probe_crashed": "сбой опроса GL: {e}",
        "gl_cannot_query": "не удалось получить версию OpenGL",
        "gl_cannot_parse": "не удалось разобрать версию OpenGL",
        "gl_below_min": "OpenGL {a}.{b} ниже минимума {c}.{d}",
        "gl_meets": "OpenGL {a}.{b} соответствует минимуму {c}.{d}",
        "gl_win_hint": "Открываю Microsoft Store — установите приложение производителя GPU и дайте ему обновить драйвер, либо запустите Windows Update.",
        "gl_win_store_fail": "не удалось открыть магазин: {e}",
        "gl_linux_hint": "установите mesa/vulkan/opencl из репозитория дистрибутива",
        "gl_other_hint": "обновите драйвер GPU в настройках системы",
        "desktop_entry": "desktop entry -> {p}",
        "desktop_shortcut": "ярлык на рабочем столе -> {p}",
        "desktop_failed": "ярлык не создан: {e}",
        "startmenu_shortcut": "ярлык в меню Пуск -> {p}",
        "shortcut_failed": "ярлык на рабочем столе не создан: {e}",
        "no_shortcut": "платформа не поддерживается, ярлык не создан",
        "fatal": "фатально: {e}",
        "run": "run {cmd}",
        "install_complete": "Установка завершена.",
        "python_install_ok": "python установлен менеджером пакетов",
    },
}


def _detect_lang():
    try:
        lang, _enc = locale.getdefaultlocale()
    except Exception:
        lang = None
    if lang and lang.lower().startswith(("ru", "be", "uk", "kk")):
        return "ru"
    return "en"


_LANG = _detect_lang()


def T(key, **fmt):
    s = _STRINGS.get(_LANG, {}).get(key) or _STRINGS["en"].get(key) or key
    if fmt:
        try:
            return s.format(**fmt)
        except (KeyError, IndexError):
            return s
    return s


_SSL_CONTEXT = None
_SSL_MODE = "default"


def _bootstrap_ssl():
    global _SSL_CONTEXT, _SSL_MODE
    try:
        import truststore
        truststore.inject_into_ssl()
        _SSL_CONTEXT = ssl.create_default_context()
        _SSL_MODE = "truststore"
        return
    except Exception:
        pass
    try:
        import certifi
        _SSL_CONTEXT = ssl.create_default_context(
            cafile=certifi.where())
        _SSL_MODE = "certifi"
        return
    except Exception:
        pass
    try:
        _SSL_CONTEXT = ssl._create_unverified_context()
        _SSL_MODE = "unverified"
    except Exception:
        _SSL_CONTEXT = None
        _SSL_MODE = "none"


_bootstrap_ssl()

REPO_ZIP = ("https://github.com/xenexx-arch/Xeria-Launcher/"
            "archive/refs/heads/main.zip")
REPO_ZIP_ALT = ("https://github.com/xenexx-arch/Xeria-Launcher/"
                "archive/refs/heads/master.zip")
APP_NAME = "Xeria Launcher"
APP_EXEC = "xeria.pyw"

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

HOME = Path.home()

if IS_WIN:
    INSTALL_DIR = Path(os.getenv("LOCALAPPDATA", HOME)) / "Xeria Launcher"
    VENV_DIR = INSTALL_DIR / ".venv"
    APPS_DIR = (Path(os.getenv("APPDATA", HOME))
                / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    DESKTOP_DIR = HOME / "Desktop"
elif IS_MAC:
    INSTALL_DIR = HOME / "Applications" / "Xeria Launcher"
    VENV_DIR = INSTALL_DIR / ".venv"
    APPS_DIR = HOME / "Applications"
    DESKTOP_DIR = HOME / "Desktop"
else:
    INSTALL_DIR = HOME / ".local" / "share" / "xeria-launcher"
    VENV_DIR = INSTALL_DIR / ".venv"
    APPS_DIR = HOME / ".local" / "share" / "applications"
    DESKTOP_DIR = HOME / ".local" / "share" / "applications"

PIP_REQUIREMENTS = [
    "PyQt6",
    "PyQt6-WebEngine",
    "PyOpenGL",
    "httpx[http2]",
    "pillow",
    "truststore",
]

PIP_REQUIREMENTS_LINUX = [
    "httpx[http2]",
    "pillow",
    "truststore",
]

LINUX_SYS_PACKAGES = {
    "apt": ["python3", "python3-venv", "python3-pip",
            "python3-pyqt6", "python3-pyqt6.qtwebengine",
            "python3-pyqt6.qtsvg", "python3-pyqt6.qtwayland",
            "python3-opengl",
            "libgl1-mesa-dri", "mesa-vulkan-drivers",
            "mesa-opencl-icd", "libglx-mesa0", "libopencl1"],
    "dnf": ["python3", "python3-pip", "python3-qt6",
            "python3-qt6-webengine", "python3-qt6-svg",
            "qt6-qtwayland", "python3-pyopengl",
            "mesa-dri-drivers", "mesa-vulkan-drivers",
            "mesa-libOpenCL", "ocl-icd"],
    "pacman": ["python", "python-pip",
               "python-pyqt6", "python-pyqt6-webengine",
               "python-pyqt6-svg", "qt6-wayland", "python-opengl",
               "mesa", "vulkan-icd-loader", "ocl-icd"],
    "zypper": ["python3", "python3-pip", "python3-qt6",
               "python3-qt6-webengine", "libQt6Svg",
               "libqt6-qtwayland", "python3-opengl",
               "Mesa", "Mesa-libGL1",
               "libvulkan1", "libOpenCL1", "ocl-icd"],
    "apk": ["python3", "py3-pip", "py3-pyqt6",
            "py3-pyqt6-webengine", "py3-pyqt6-svg",
            "qt6-qtwayland", "py3-opengl",
            "mesa-dri-gallium", "vulkan-loader", "opencl-icd-loader"],
}

MIN_PYTHON = (3, 9)
PYTHON_RELEASES_JSON = ("https://www.python.org/api/v2/downloads/release/"
                        "?is_published=true&pre_release=false")
MIN_GL = (3, 3)

BG = "#1a1a1a"
BG2 = "#232323"
BG3 = "#2e2e2e"
BORDER = "#3d3d3d"
FG = "#e6e6e6"
GRAY = "#8a8a8a"
ACCENT = "#ffffff"
ACCENT2 = "#d0d0d0"
GREEN = "#5eb87d"
RED = "#e05c5c"
YELLOW = "#e0b85c"
CYAN = "#5cb8d8"

UI_FONT = "Segoe UI" if IS_WIN else "DejaVu Sans"
MONO_FONT = "Consolas" if IS_WIN else "DejaVu Sans Mono"

CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0


def _detect_opengl():
    try:
        from PyQt6.QtGui import (
            QOpenGLContext, QOffscreenSurface, QSurfaceFormat,
        )
    except Exception as e:
        return None, None, f"PyQt GL imports failed: {e}", None
    try:
        ctx = QOpenGLContext()
        fmt = QSurfaceFormat()
        fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
        ctx.setFormat(fmt)
        if not ctx.create():
            return None, None, "failed to create GL context", None
        surface = QOffscreenSurface()
        surface.setFormat(ctx.format())
        surface.create()
        if not surface.isValid():
            return None, None, "offscreen surface invalid", None
        if not ctx.makeCurrent(surface):
            return None, None, "could not make context current", None
        try:
            from OpenGL import GL
        except Exception as e:
            ctx.doneCurrent()
            return None, None, f"PyOpenGL missing: {e}", None

        def _s(enum):
            v = GL.glGetString(enum)
            if v is None:
                return ""
            try:
                return v.decode("utf-8", "replace")
            except Exception:
                return str(v)

        vendor = _s(GL.GL_VENDOR)
        renderer = _s(GL.GL_RENDERER)
        version = _s(GL.GL_VERSION)
        ctx.doneCurrent()
        surface.destroy()
        m = re.match(r"(\d+)\.(\d+)", version or "")
        parsed = (int(m.group(1)), int(m.group(2))) if m else None
        return vendor, renderer, version, parsed
    except Exception as e:
        return None, None, f"GL probe failed: {e}", None


def _open_ms_store_home():
    if not IS_WIN:
        return False
    try:
        webbrowser.open("ms-windows-store://home")
        return True
    except Exception:
        return False


def _print_linux_hint(pm):
    if pm == "apt":
        return ("sudo apt install libgl1-mesa-dri "
                "mesa-vulkan-drivers mesa-opencl-icd")
    if pm == "dnf":
        return ("sudo dnf install mesa-dri-drivers "
                "mesa-vulkan-drivers mesa-libOpenCL")
    if pm == "pacman":
        return "sudo pacman -S mesa vulkan-icd-loader ocl-icd"
    if pm == "zypper":
        return "sudo zypper install Mesa Mesa-libGL1 libvulkan1 libOpenCL1"
    if pm == "apk":
        return "sudo apk add mesa-dri-gallium vulkan-loader opencl-icd-loader"
    return T("gl_linux_hint")


def _force_rmtree(path):
    path = Path(path)
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
        return
    except Exception:
        pass
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            try:
                os.chmod(os.path.join(root, name), 0o777)
            except Exception:
                pass
            try:
                os.unlink(os.path.join(root, name))
            except Exception:
                pass
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except Exception:
                pass
    try:
        os.rmdir(path)
    except Exception:
        pass
    if path.exists():
        raise RuntimeError(f"could not fully remove {path}")


class PasswordDialog(QDialog):
    def __init__(self, parent=None, prompt=None):
        super().__init__(parent)
        self.setWindowTitle(T("pass_title"))
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setStyleSheet(
            f"QDialog{{background:{BG};color:{FG}}}"
            f"QLabel{{background:transparent;color:{FG};"
            f"font-family:'{UI_FONT}';font-size:10pt}}"
            f"QLineEdit{{background:{BG3};color:{FG};border:none;"
            f"padding:8px;font-family:'{UI_FONT}';font-size:11pt}}"
            f"QPushButton{{background:{BG3};color:{FG};border:none;"
            f"padding:8px 18px;font-family:'{UI_FONT}'}}"
            f"QPushButton:hover{{background:{BORDER}}}")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(10)
        lbl = QLabel(prompt or T("pass_prompt"))
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        self.field = QLineEdit()
        self.field.setEchoMode(QLineEdit.EchoMode.Password)
        self.field.setPlaceholderText(T("pass_placeholder"))
        v.addWidget(self.field)
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton(T("cancel"))
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        ok = QPushButton(T("ok"))
        ok.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:#000000;"
            f"border:none;padding:8px 20px;font-weight:bold;"
            f"font-family:'{UI_FONT}'}}"
            f"QPushButton:hover{{background:{ACCENT2}}}")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btns.addWidget(ok)
        v.addLayout(btns)
        self.field.setFocus()

    def value(self):
        return self.field.text()


class InstallWorker(QThread):
    log_line = pyqtSignal(str, str)
    progress = pyqtSignal(int)
    finished_ok = pyqtSignal(bool, str)
    request_password = pyqtSignal(str)

    def __init__(self, log_fn):
        super().__init__()
        self._log = log_fn
        self._cancelled = False
        self._password = None
        self._sudo_skipped = False

    def _L(self, tag, msg):
        self._log(tag, msg)
        self.log_line.emit(tag, msg)

    def cancel(self):
        self._cancelled = True

    def skip_sudo(self):
        self._sudo_skipped = True

    def supply_password(self, password):
        self._password = password

    def run(self):
        try:
            ok, msg = self._run_install()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._L("err", T("fatal", e=e))
            ok, msg = False, str(e)
        self.finished_ok.emit(ok, msg)

    def _run_install(self):
        self._L("sys", T("platform",
                        os=platform.system(),
                        rel=platform.release()))
        self._L("sys", T("python", v=platform.python_version()))
        self._L("sys", T("ssl", m=_SSL_MODE))
        self._L("sys", T("install_dir", d=INSTALL_DIR))
        if _SSL_MODE == "unverified":
            self._L("warn", T("ssl_unverified_warn"))
            self._L("warn", T("ssl_fix_warn"))

        self.progress.emit(5)
        py = self._find_python()
        if py is None:
            self._L("py", T("no_python",
                           a=MIN_PYTHON[0], b=MIN_PYTHON[1]))
            py = self._install_new_python()
            if py is None:
                return False, T("python_still_missing")
        else:
            self._L("ok", T("using_python", p=py))

        if self._cancelled:
            return False, T("cancelled")

        self.progress.emit(15)
        if IS_LINUX:
            self._install_system_packages()

        if self._cancelled:
            return False, T("cancelled")

        self.progress.emit(30)
        self._download_repo()

        if self._cancelled:
            return False, T("cancelled")

        self.progress.emit(45)
        self._L("sys", T("using_python", p=py))
        self._create_venv(py)

        if self._cancelled:
            return False, T("cancelled")

        self.progress.emit(60)
        self._install_pip_packages()

        if self._cancelled:
            return False, T("cancelled")

        self.progress.emit(90)
        self._check_gpu_stack()

        if self._cancelled:
            return False, T("cancelled")

        self.progress.emit(95)
        if IS_WIN:
            self._make_windows_shortcut()
        elif IS_LINUX or IS_MAC:
            self._make_linux_desktop()
        else:
            self._L("warn", T("no_shortcut"))

        self.progress.emit(100)
        return True, T("install_complete")

    def _which(self, program):
        return shutil.which(program)

    def _needs_sudo(self):
        if IS_WIN:
            return False
        try:
            return os.geteuid() != 0
        except AttributeError:
            return True

    def _ensure_password(self):
        if self._password is not None:
            return True
        self.request_password.emit(T("pass_prompt"))
        return False

    def _run(self, cmd, cwd=None, check=True, use_sudo=False):
        self._L("run", T("run",
                        cmd=" ".join(str(c) for c in cmd)))
        if use_sudo and self._needs_sudo():
            if self._password is None:
                self._ensure_password()
                for _ in range(3000):
                    if (self._password is not None
                            or self._cancelled
                            or self._sudo_skipped):
                        break
                    QThread.msleep(100)
                if self._cancelled:
                    raise RuntimeError(T("cancelled"))
                if self._sudo_skipped or self._password is None:
                    raise RuntimeError("no password supplied")
            full = ["sudo", "-S", "-p", ""] + [str(c) for c in cmd]
            proc = subprocess.Popen(
                full,
                cwd=str(cwd) if cwd else None,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            out, _ = proc.communicate(self._password + "\n")
            for line in (out or "").splitlines():
                if line.strip():
                    self._L("sys", line)
            if check and proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode, full)
            return proc.returncode
        return subprocess.run(
            [str(c) for c in cmd],
            cwd=str(cwd) if cwd else None,
            check=check,
            creationflags=CREATE_NO_WINDOW).returncode

    def _http_get(self, url, timeout=30):
        req = urllib.request.Request(
            url, headers={"User-Agent": "Xeria Launcher/2.504"})
        if _SSL_CONTEXT is not None:
            return urllib.request.urlopen(
                req, context=_SSL_CONTEXT, timeout=timeout)
        return urllib.request.urlopen(req, timeout=timeout)

    def _download(self, url, dest):
        self._L("net", T("repo_downloading", url=url, m=_SSL_MODE))
        r = self._http_get(url, timeout=120)
        with r:
            total = int(r.headers.get("Content-Length", 0))
            got = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        pct = got * 100 // total
                        self.progress.emit(30 + pct * 15 // 100)
        self._L("net", T("repo_downloaded", p=dest))

    def _python_version_of(self, exe):
        try:
            out = subprocess.run(
                [exe, "-c",
                 "import sys;print('%d.%d' % sys.version_info[:2]);"
                 "print(sys.executable)"],
                capture_output=True, text=True, timeout=10,
                creationflags=CREATE_NO_WINDOW)
            if out.returncode != 0:
                return None
            lines = out.stdout.strip().splitlines()
            if len(lines) < 2:
                return None
            ver_line = lines[0].strip()
            exe_line = lines[1].strip()
            if not exe_line or not os.path.isfile(exe_line):
                return None
            return tuple(int(x) for x in ver_line.split("."))
        except Exception:
            return None

    def _can_make_venv(self, exe):
        try:
            out = subprocess.run(
                [exe, "-c", "import venv,ensurepip;print('ok')"],
                capture_output=True, text=True, timeout=15,
                creationflags=CREATE_NO_WINDOW)
            return out.returncode == 0 and "ok" in out.stdout
        except Exception:
            return False

    def _find_python(self):
        seen = set()
        candidates = []
        for name in ("python3.15", "python3.14", "python3.13",
                     "python3.12", "python3.11", "python3.10",
                     "python3.9", "python3", "python"):
            p = self._which(name)
            if p and p not in seen:
                seen.add(p)
                candidates.append(p)
        best, best_ver = None, None
        for c in candidates:
            if IS_WIN and "WindowsApps" in c.replace("/", "\\"):
                self._L("py", T("python_store_stub", p=c))
                continue
            v = self._python_version_of(c)
            if not v:
                self._L("py", T("python_unusable", p=c))
                continue
            if v < MIN_PYTHON:
                self._L("py", T("python_too_old", p=c, a=v[0], b=v[1]))
                continue
            if not self._can_make_venv(c):
                self._L("py", T("python_no_venv", p=c))
                continue
            self._L("py", T("python_found", p=c, a=v[0], b=v[1]))
            if best_ver is None or v > best_ver:
                best, best_ver = c, v
        if best is None:
            return None
        self._L("ok", T("selected_python",
                       p=best, a=best_ver[0], b=best_ver[1]))
        return best

    def _fetch_latest_stable_python(self):
        self._L("net", T("python_query"))
        try:
            r = self._http_get(PYTHON_RELEASES_JSON, timeout=20)
            data = r.read()
        except Exception as e:
            self._L("warn", T("python_api_failed", e=e))
            return None
        try:
            releases = json.loads(data.decode("utf-8"))
        except Exception as e:
            self._L("warn", T("python_api_parse_failed", e=e))
            return None
        best_key = None
        for rel in releases:
            name = rel.get("name") or ""
            m = re.match(r"Python (\d+)\.(\d+)\.(\d+)$", name)
            if not m:
                continue
            key = (int(m.group(1)), int(m.group(2)),
                   int(m.group(3)))
            if best_key is None or key > best_key:
                best_key = key
        if best_key is None:
            self._L("warn", T("python_no_stable"))
            return None
        self._L("ok", T("python_latest",
                       a=best_key[0], b=best_key[1], c=best_key[2]))
        return best_key

    def _python_installer_url(self, ver):
        v = f"{ver[0]}.{ver[1]}.{ver[2]}"
        if IS_WIN:
            return (f"https://www.python.org/ftp/python/{v}/"
                    f"python-{v}-amd64.exe")
        if IS_MAC:
            return (f"https://www.python.org/ftp/python/{v}/"
                    f"python-{v}-macos11.pkg")
        return None

    def _install_new_python(self):
        self._L("py", T("python_installing"))
        if IS_LINUX:
            return self._install_python_linux()
        if IS_WIN or IS_MAC:
            return self._install_python_desktop()
        self._L("err", T("python_no_auto", os=platform.system()))
        return None

    def _install_python_linux(self):
        pm = None
        for name in ("apt", "dnf", "pacman", "zypper", "apk"):
            if self._which(name):
                pm = name
                break
        if not pm:
            self._L("err", T("python_no_pm"))
            return None
        pkg_map = {
            "apt": ["python3", "python3-venv", "python3-pip"],
            "dnf": ["python3", "python3-pip"],
            "pacman": ["python", "python-pip"],
            "zypper": ["python3", "python3-pip"],
            "apk": ["python3", "py3-pip"],
        }
        pkgs = pkg_map[pm]
        try:
            if pm == "apt":
                self._run(["apt-get", "update"],
                          check=False, use_sudo=True)
                self._run(["apt-get", "install", "-y"] + pkgs,
                          use_sudo=True)
            elif pm == "dnf":
                self._run(["dnf", "install", "-y"] + pkgs,
                          use_sudo=True)
            elif pm == "pacman":
                self._run(
                    ["pacman", "-S", "--needed", "--noconfirm"] + pkgs,
                    use_sudo=True)
            elif pm == "zypper":
                self._run(
                    ["zypper", "--non-interactive", "install"] + pkgs,
                    use_sudo=True)
            elif pm == "apk":
                self._run(["apk", "add"] + pkgs, use_sudo=True)
            self._L("ok", T("python_pm_ok"))
        except subprocess.CalledProcessError as e:
            self._L("err", T("python_pm_fail", e=e))
            return None
        except RuntimeError as e:
            self._L("err", T("python_pm_abort", e=e))
            return None
        return self._find_python()

    def _install_python_desktop(self):
        ver = self._fetch_latest_stable_python()
        if ver is None:
            self._L("err", T("python_unknown_version"))
            return None
        url = self._python_installer_url(ver)
        if not url:
            self._L("err", T("python_no_installer",
                            os=platform.system()))
            return None
        self._L("py", T("python_downloading",
                       a=ver[0], b=ver[1], c=ver[2]))
        if IS_WIN:
            tmp = Path(os.getenv("TEMP", ".")) / "python-installer.exe"
            self._download(url, tmp)
            try:
                subprocess.run(
                    [str(tmp), "/quiet",
                     "InstallAllUsers=0",
                     "PrependPath=1",
                     "Include_test=0",
                     "Include_launcher=1"],
                    check=True,
                    creationflags=CREATE_NO_WINDOW)
            except subprocess.CalledProcessError as e:
                self._L("err", T("python_installer_failed", e=e))
                return None
            finally:
                try:
                    tmp.unlink()
                except Exception:
                    pass
            tag = f"Python{ver[0]}{ver[1]}"
            candidates = [
                HOME / "AppData" / "Local" / "Programs" / "Python"
                / tag / "python.exe",
                Path(os.getenv("LOCALAPPDATA", "")) / "Programs"
                / "Python" / tag / "python.exe",
                Path(f"C:\\{tag}\\python.exe"),
            ]
            for c in candidates:
                if c.exists():
                    self._L("ok", T("python_installed_at", p=c))
                    return str(c)
            py = self._which("python")
            if py and "WindowsApps" not in py.replace("/", "\\"):
                return py
            self._L("err", T("python_path_missing"))
            return None
        if IS_MAC:
            tmp = Path("/tmp") / "python-installer.pkg"
            self._download(url, tmp)
            try:
                self._run(
                    ["installer", "-pkg", str(tmp), "-target", "/"],
                    use_sudo=True)
            except subprocess.CalledProcessError as e:
                self._L("err", T("python_installer_failed", e=e))
                return None
            except RuntimeError as e:
                self._L("err", T("python_pm_abort", e=e))
                return None
            finally:
                try:
                    tmp.unlink()
                except Exception:
                    pass
            return self._find_python()
        return None

    def _download_repo(self):
        INSTALL_DIR.parent.mkdir(parents=True, exist_ok=True)
        if INSTALL_DIR.exists():
            self._L("fs", T("repo_removing", d=INSTALL_DIR))
            _force_rmtree(INSTALL_DIR)
            self._L("ok", T("repo_removed"))
        tmp_zip = INSTALL_DIR.parent / "xeria-main.zip"
        last_err = None
        for url in (REPO_ZIP, REPO_ZIP_ALT):
            try:
                self._download(url, tmp_zip)
                last_err = None
                break
            except Exception as e:
                self._L("err", T("repo_download_failed", e=e))
                last_err = e
        if last_err:
            raise RuntimeError(T("repo_fetch_failed"))
        self._L("fs", T("repo_extracting", p=tmp_zip))
        extract_root = INSTALL_DIR.parent / "_xeria_extract"
        if extract_root.exists():
            _force_rmtree(extract_root)
        with zipfile.ZipFile(tmp_zip) as z:
            z.extractall(extract_root)
        try:
            tmp_zip.unlink()
        except Exception:
            pass
        entries = [p for p in extract_root.iterdir() if p.is_dir()]
        if not entries:
            raise RuntimeError(T("repo_no_dirs"))
        src = entries[0]
        self._L("fs", T("repo_moving", src=src, dst=INSTALL_DIR))
        src.rename(INSTALL_DIR)
        try:
            extract_root.rmdir()
        except Exception:
            pass
        self._L("ok", T("repo_ready", d=INSTALL_DIR))
        expected = [
            INSTALL_DIR / "xeria.pyw",
            INSTALL_DIR / "src",
            INSTALL_DIR / "src" / "core",
            INSTALL_DIR / "src" / "ui",
            INSTALL_DIR / "src" / "instances",
            INSTALL_DIR / "src" / "browse",
            INSTALL_DIR / "src" / "integration",
        ]
        missing = [p for p in expected if not p.exists()]
        if missing:
            raise RuntimeError(T(
                "repo_layout_bad",
                list=", ".join(str(p.relative_to(INSTALL_DIR))
                               for p in missing)))
        self._L("ok", T("repo_verify"))

    def _create_venv(self, py):
        if VENV_DIR.exists():
            self._L("venv", T("venv_removing", d=VENV_DIR))
            _force_rmtree(VENV_DIR)
            self._L("ok", T("venv_removed"))
        self._L("venv", T("venv_creating", d=VENV_DIR))
        kwargs = dict(with_pip=True, clear=False)
        if IS_LINUX:
            kwargs["system_site_packages"] = True
            self._L("venv", T("venv_system_site"))
        try:
            venv.create(str(VENV_DIR), **kwargs)
        except Exception as e:
            raise RuntimeError(T("venv_create_failed", e=e))
        self._L("ok", T("venv_created"))

    def _venv_python(self):
        if IS_WIN:
            return VENV_DIR / "Scripts" / "python.exe"
        return VENV_DIR / "bin" / "python"

    def _venv_pythonw(self):
        if IS_WIN:
            return VENV_DIR / "Scripts" / "pythonw.exe"
        return VENV_DIR / "bin" / "python"

    def _install_pip_packages(self):
        py = self._venv_python()
        if not py.exists():
            raise RuntimeError(T("venv_python_missing", p=py))
        self._L("pip", T("pip_bootstrap"))
        try:
            self._run([py, "-m", "pip", "install", "--upgrade",
                       "pip", "setuptools", "wheel"])
        except subprocess.CalledProcessError as e:
            self._L("warn", T("pip_bootstrap_failed", e=e))
        pkgs = (PIP_REQUIREMENTS_LINUX if IS_LINUX
                else PIP_REQUIREMENTS)
        if IS_LINUX:
            self._L("pip", T("pip_skip_linux"))
        for i, pkg in enumerate(pkgs, 1):
            self._L("pip", T("pip_install", pkg=pkg))
            try:
                self._run([py, "-m", "pip", "install",
                           "--upgrade", pkg])
                self._L("ok", T("pip_installed", pkg=pkg))
            except subprocess.CalledProcessError as e:
                self._L("warn", T("pip_failed", pkg=pkg, e=e))
            self.progress.emit(60 + i * 30 // len(pkgs))
        self._L("ok", T("pip_done"))

    def _missing_packages(self, pm, pkgs):
        try:
            if pm == "pacman":
                out = subprocess.run(
                    ["pacman", "-Qq"] + pkgs,
                    capture_output=True, text=True, timeout=10,
                    creationflags=CREATE_NO_WINDOW)
                installed = set(out.stdout.split())
                return [p for p in pkgs if p not in installed]
            if pm == "apt":
                out = subprocess.run(
                    ["dpkg", "-s"] + pkgs,
                    capture_output=True, text=True, timeout=10,
                    creationflags=CREATE_NO_WINDOW)
                installed = set()
                for line in out.stdout.splitlines():
                    if line.startswith("Package:"):
                        installed.add(
                            line.split(":", 1)[1].strip())
                return [p for p in pkgs if p not in installed]
            if pm == "dnf":
                out = subprocess.run(
                    ["rpm", "-q"] + pkgs,
                    capture_output=True, text=True, timeout=10,
                    creationflags=CREATE_NO_WINDOW)
                installed = set()
                for line in out.stdout.splitlines():
                    if "is not installed" in line:
                        continue
                    if ".x86_64" in line or ".noarch" in line:
                        installed.add(line.split("-")[0])
                return [p for p in pkgs if p not in installed]
        except Exception:
            pass
        return pkgs

    def _install_system_packages(self):
        if not IS_LINUX:
            return
        pm = None
        for name in ("apt", "dnf", "pacman", "zypper", "apk"):
            if self._which(name):
                pm = name
                break
        if not pm:
            self._L("warn", T("no_pm"))
            return
        pkgs = LINUX_SYS_PACKAGES.get(pm, [])
        if not pkgs:
            return
        missing = self._missing_packages(pm, pkgs)
        if not missing:
            self._L("ok", T("pkgs_ok"))
            return
        self._L("sys", T("pkgs_missing",
                        list=", ".join(missing)))
        try:
            if pm == "apt":
                self._run(["apt-get", "update"],
                          check=False, use_sudo=True)
                self._run(["apt-get", "install", "-y"] + missing,
                          use_sudo=True)
            elif pm == "dnf":
                self._run(["dnf", "install", "-y"] + missing,
                          use_sudo=True)
            elif pm == "pacman":
                self._run(
                    ["pacman", "-S", "--needed", "--noconfirm"]
                    + missing,
                    use_sudo=True)
            elif pm == "zypper":
                self._run(
                    ["zypper", "--non-interactive", "install"]
                    + missing,
                    use_sudo=True)
            elif pm == "apk":
                self._run(["apk", "add"] + missing, use_sudo=True)
            self._L("ok", T("pkgs_installed"))
        except RuntimeError as e:
            msg = str(e).lower()
            if "no password" in msg:
                self._L("warn", T("pkgs_skipped"))
                self._L("hint", T(
                    "pkgs_hint", cmd=_print_linux_hint(pm)))
                self._password = None
                self._sudo_skipped = False
                return
            if "cancelled" in msg:
                raise
            self._L("warn", T("pkgs_failed", e=e))
        except subprocess.CalledProcessError as e:
            self._L("warn", T("pkgs_failed", e=e))

    def _check_gpu_stack(self):
        self._L("sys", T("gl_probing"))
        try:
            vendor, renderer, version, parsed = _detect_opengl()
        except Exception as e:
            self._L("warn", T("gl_probe_crashed", e=e))
            return
        if version is None:
            self._L("warn", T("gl_cannot_query"))
            return
        self._L("sys", T("gl_vendor",
                        v=vendor or T("gl_unknown")))
        self._L("sys", T("gl_renderer",
                        v=renderer or T("gl_unknown")))
        self._L("sys", T("gl_version", v=version))
        if parsed is None:
            self._L("warn", T("gl_cannot_parse"))
            return
        if parsed < MIN_GL:
            self._L("warn", T(
                "gl_below_min",
                a=parsed[0], b=parsed[1],
                c=MIN_GL[0], d=MIN_GL[1]))
            if IS_WIN:
                self._L("hint", T("gl_win_hint"))
                try:
                    _open_ms_store_home()
                except Exception as e:
                    self._L("warn", T("gl_win_store_fail", e=e))
            elif IS_LINUX:
                pm = None
                for name in ("apt", "dnf", "pacman",
                             "zypper", "apk"):
                    if self._which(name):
                        pm = name
                        break
                hint = (_print_linux_hint(pm) if pm
                        else T("gl_linux_hint"))
                self._L("hint", hint)
            else:
                self._L("hint", T("gl_other_hint"))
        else:
            self._L("ok", T(
                "gl_meets",
                a=parsed[0], b=parsed[1],
                c=MIN_GL[0], d=MIN_GL[1]))

    def _make_icon(self):
        for candidate in (
            INSTALL_DIR / "icon.png",
            INSTALL_DIR / "assets" / "icon.png",
            INSTALL_DIR / "src" / "icon.png",
        ):
            if candidate.exists():
                return candidate
        return None

    def _make_linux_desktop(self):
        APPS_DIR.mkdir(parents=True, exist_ok=True)
        desktop_path = APPS_DIR / "xeria-launcher.desktop"
        if desktop_path.exists():
            try:
                desktop_path.unlink()
            except Exception:
                pass
        icon = self._make_icon()
        icon_line = (f"Icon={icon}" if icon
                     else "Icon=applications-games")
        py = self._venv_python()
        exec_cmd = f'"{py}" "{INSTALL_DIR / APP_EXEC}"'
        content = f"""[Desktop Entry]
Type=Application
Name=Xeria Launcher
Comment=Lightweight Minecraft launcher
Exec={exec_cmd}
Path={INSTALL_DIR}
{icon_line}
Terminal=false
Categories=Game;
StartupNotify=true
StartupWMClass=Xeria
"""
        desktop_path.write_text(content)
        desktop_path.chmod(0o755)
        self._L("ok", T("desktop_entry", p=desktop_path))
        if DESKTOP_DIR.exists() and DESKTOP_DIR != APPS_DIR:
            try:
                desk_copy = DESKTOP_DIR / "xeria-launcher.desktop"
                if desk_copy.exists():
                    try:
                        desk_copy.unlink()
                    except Exception:
                        pass
                desk_copy.write_text(content)
                desk_copy.chmod(0o755)
                if self._which("gio"):
                    subprocess.run(
                        ["gio", "set", str(desk_copy),
                         "metadata::trusted", "true"],
                        check=False)
                self._L("ok", T("desktop_shortcut", p=desk_copy))
            except Exception as e:
                self._L("warn", T("desktop_failed", e=e))
        if self._which("update-desktop-database"):
            subprocess.run(
                ["update-desktop-database", str(APPS_DIR)],
                check=False)

    def _make_windows_shortcut(self):
        APPS_DIR.mkdir(parents=True, exist_ok=True)
        py = self._venv_pythonw()
        target = INSTALL_DIR / APP_EXEC
        icon = self._make_icon()
        icon_line = f"$s.IconLocation = '{icon}'; " if icon else ""

        def _ps(link_path):
            if link_path.exists():
                try:
                    link_path.unlink()
                except Exception:
                    pass
            ps = (
                "$ws = New-Object -ComObject WScript.Shell; "
                f"$s = $ws.CreateShortcut('{link_path}'); "
                f"$s.TargetPath = '{py}'; "
                f"$s.Arguments = '\"{target}\"'; "
                f"$s.WorkingDirectory = '{INSTALL_DIR}'; "
                "$s.WindowStyle = 1; "
                "$s.Description = 'Xeria Launcher'; "
                f"{icon_line}"
                "$s.Save();"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                check=True, creationflags=CREATE_NO_WINDOW)

        start_link = APPS_DIR / "Xeria Launcher.lnk"
        _ps(start_link)
        self._L("ok", T("startmenu_shortcut", p=start_link))
        if DESKTOP_DIR.exists():
            try:
                desk_link = DESKTOP_DIR / "Xeria Launcher.lnk"
                _ps(desk_link)
                self._L("ok", T("desktop_shortcut", p=desk_link))
            except Exception as e:
                self._L("warn", T("shortcut_failed", e=e))


class InstallerWindow(QWidget):
    def __init__(self):
        super().__init__()
        self._worker = None
        self._done = False
        self._pending_logs = []
        self.setWindowTitle(T("title"))
        self.resize(720, 520)
        self.setMinimumSize(560, 380)
        self.setStyleSheet(f"QWidget{{background:{BG};color:{FG}}}")

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)

        head = QLabel(T("title"))
        head.setStyleSheet(
            f"background:transparent;color:{ACCENT};"
            f"font-size:18pt;font-weight:bold;"
            f"font-family:'{UI_FONT}'")
        v.addWidget(head)

        sub = QLabel(T("subtitle"))
        sub.setStyleSheet(
            f"background:transparent;color:{GRAY};"
            f"font-size:10pt;font-family:'{UI_FONT}'")
        v.addWidget(sub)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont(MONO_FONT, 9))
        self.log.setStyleSheet(
            f"QPlainTextEdit{{background:{BG2};color:{FG};"
            f"border:none;padding:8px}}")
        v.addWidget(self.log, 1)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet(
            f"QProgressBar{{background:{BG3};border:none}}"
            f"QProgressBar::chunk{{background:{ACCENT}}}")
        v.addWidget(self.bar)

        btns = QHBoxLayout()
        btns.addStretch()
        self.install_btn = QPushButton(T("install"))
        self.install_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:#000000;"
            f"border:none;padding:10px 24px;font-weight:bold;"
            f"font-family:'{UI_FONT}';font-size:11pt}}"
            f"QPushButton:hover{{background:{ACCENT2}}}"
            f"QPushButton:disabled{{background:{BG3};color:{GRAY}}}")
        self.install_btn.clicked.connect(self.start_install)
        btns.addWidget(self.install_btn)

        self.close_btn = QPushButton(T("close"))
        self.close_btn.setStyleSheet(
            f"QPushButton{{background:{BG3};color:{FG};border:none;"
            f"padding:10px 20px;font-family:'{UI_FONT}'}}"
            f"QPushButton:hover{{background:{BORDER}}}")
        self.close_btn.clicked.connect(self.close)
        btns.addWidget(self.close_btn)
        v.addLayout(btns)

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(50)
        self._flush_timer.timeout.connect(self._flush_logs)
        self._flush_timer.start()

        self._log("sys", T("platform",
                          os=platform.system(),
                          rel=platform.release()))
        self._log("sys", T("python", v=platform.python_version()))
        self._log("sys", T("ssl", m=_SSL_MODE))
        self._log("sys", T("install_dir", d=INSTALL_DIR))
        self._log("info", T("start"))

    def _log(self, tag, msg):
        self._pending_logs.append((tag, msg))

    def _flush_logs(self):
        if not self._pending_logs:
            return
        batch, self._pending_logs = self._pending_logs, []
        for tag, msg in batch:
            color = {
                "ok": GREEN, "warn": YELLOW, "err": RED,
                "net": CYAN, "pip": CYAN, "py": CYAN,
                "sys": GRAY, "fs": GRAY, "venv": CYAN,
                "run": GRAY, "info": FG, "hint": CYAN,
                "win": CYAN,
            }.get(tag, FG)
            safe = (str(msg).replace("&", "&amp;")
                           .replace("<", "&lt;")
                           .replace(">", "&gt;"))
            self.log.appendHtml(
                f'<span style="color:{FG}">{safe}</span>')
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _ask_password(self, prompt):
        dlg = PasswordDialog(self, prompt)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.value()
        return None

    def start_install(self):
        if self._worker is not None:
            return
        self.install_btn.setEnabled(False)
        self.install_btn.setText(T("installing"))
        self.bar.setValue(0)
        self._worker = InstallWorker(self._log)
        self._worker.log_line.connect(
            self._log, Qt.ConnectionType.QueuedConnection)
        self._worker.progress.connect(
            self.bar.setValue, Qt.ConnectionType.QueuedConnection)
        self._worker.finished_ok.connect(
            self._on_done, Qt.ConnectionType.QueuedConnection)
        self._worker.request_password.connect(
            self._on_password_request,
            Qt.ConnectionType.QueuedConnection)
        self._worker.start()

    def _on_password_request(self, prompt):
        pwd = self._ask_password(prompt)
        if pwd is None:
            self._worker.skip_sudo()
        else:
            self._worker.supply_password(pwd)

    def _on_done(self, ok, msg):
        self._done = True
        self._worker = None
        if ok:
            self._log("ok", "=" * 44)
            self._log("ok", T("install_ok_title"))
            self._log("ok", "=" * 44)
            if IS_WIN:
                self._log("hint", T("install_hint_win"))
            else:
                py = VENV_DIR / "bin" / "python"
                cmd = f'"{py}" "{INSTALL_DIR / APP_EXEC}"'
                self._log("hint", T("install_hint_launch",
                                    cmd=cmd))
                self._log("hint", T("install_hint_apps"))
            self._log("info", "")
            self._log("info", T("install_hint_close"))
            self.bar.setValue(100)
            self.install_btn.setText(T("done"))
            self.install_btn.setEnabled(False)
            self.close_btn.setStyleSheet(
                f"QPushButton{{background:{ACCENT};"
                f"color:#000000;border:none;padding:10px 20px;"
                f"font-weight:bold;font-family:'{UI_FONT}'}}"
                f"QPushButton:hover{{background:{ACCENT2}}}")
        else:
            self._log("err", msg)
            self.bar.setValue(0)
            self.install_btn.setEnabled(True)
            self.install_btn.setText(T("retry"))
            QMessageBox.critical(self, T("fail_title"), msg)

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            if QMessageBox.question(
                    self, T("quit_title"), T("quit_msg"),
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
            ) != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.cancel()
            self._worker.wait(2000)
        event.accept()


def main():
    os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    ic = QIcon.fromTheme("applications-games")
    if not ic.isNull():
        app.setWindowIcon(ic)
    w = InstallerWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
