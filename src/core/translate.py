import json
import locale
from pathlib import Path

_STRINGS = {}
_LANG = "en"
_DIR = Path(__file__).parent.parent / "lang"


def _load():
    global _STRINGS
    _STRINGS = {}
    if not _DIR.exists():
        return
    for f in _DIR.glob("*.json"):
        try:
            _STRINGS[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass


def _detect():
    try:
        lang, _ = locale.getdefaultlocale()
    except Exception:
        lang = None
    if lang and lang.lower().startswith(("ru", "be", "uk", "kk")):
        return "ru" if "ru" in _STRINGS else "en"
    return "en"


def init(preferred=None):
    global _LANG
    _load()
    if preferred and preferred in _STRINGS:
        _LANG = preferred
    else:
        _LANG = _detect() if _STRINGS else "en"


def get_language():
    return _LANG


def available_languages():
    return [("en", "English (US)"), ("ru", "Русский")]


def set_language(code):
    global _LANG
    if code in _STRINGS:
        _LANG = code


def t(key, **fmt):
    s = (_STRINGS.get(_LANG) or {}).get(key)
    if s is None:
        s = (_STRINGS.get("en") or {}).get(key, key)
    if fmt:
        try:
            return s.format(**fmt)
        except (KeyError, IndexError):
            return s
    return s
