import platform

IS_WIN = platform.system() == "Windows"
UI_FONT = "Segoe UI" if IS_WIN else "DejaVu Sans"
MONO_FONT = "Consolas" if IS_WIN else "DejaVu Sans Mono"

DARK_PALETTE = {
    "BG": "#1a1a1a",
    "BG2": "#232323",
    "BG3": "#2e2e2e",
    "BORDER": "#3d3d3d",
    "FG": "#e6e6e6",
    "GRAY": "#8a8a8a",
    "ACCENT": "#4a90e2",
    "ACCENT2": "#3a7bc8",
    "GREEN": "#5eb87d",
    "RED": "#e05c5c",
    "YELLOW": "#e0b85c",
    "CYAN": "#5cb8d8",
    "PURPLE": "#8a8a8a",
    "PINK": "#d88aa8",
    "ORANGE": "#e0895c",
    "BLUE": "#5c8ae0",
    "TEXT_ON_ACCENT": "#ffffff",
    "WHITE": "#ffffff",
    "BLACK": "#000000",
}

LIGHT_PALETTE = {
    "BG": "#f5f5f5",
    "BG2": "#e8e8e8",
    "BG3": "#dcdcdc",
    "BORDER": "#c4c4c4",
    "FG": "#202020",
    "GRAY": "#6a6a6a",
    "ACCENT": "#4a90e2",
    "ACCENT2": "#3a7bc8",
    "GREEN": "#3f9a5a",
    "RED": "#c94a5a",
    "YELLOW": "#b88a2a",
    "CYAN": "#3d8ca8",
    "PURPLE": "#6a6a6a",
    "PINK": "#c476a8",
    "ORANGE": "#c47a3f",
    "BLUE": "#5a7bd6",
    "TEXT_ON_ACCENT": "#ffffff",
    "WHITE": "#ffffff",
    "BLACK": "#000000",
}

ACCENTS = {
    "White": {"ACCENT": "#c8c8c8", "ACCENT2": "#a0a0a0"},
    "Blue": {"ACCENT": "#4a90e2", "ACCENT2": "#3a7bc8"},
    "Purple": {"ACCENT": "#9a6ce0", "ACCENT2": "#7a52c0"},
    "Green": {"ACCENT": "#5eb87d", "ACCENT2": "#4a9668"},
    "Orange": {"ACCENT": "#e0895c", "ACCENT2": "#c07048"},
    "Red": {"ACCENT": "#e05c5c", "ACCENT2": "#c04848"},
    "Pink": {"ACCENT": "#d88aa8", "ACCENT2": "#b86e8c"},
    "Cyan": {"ACCENT": "#5cb8d8", "ACCENT2": "#4a9ab8"},
}

BG = DARK_PALETTE["BG"]
BG2 = DARK_PALETTE["BG2"]
BG3 = DARK_PALETTE["BG3"]
BORDER = DARK_PALETTE["BORDER"]
FG = DARK_PALETTE["FG"]
GRAY = DARK_PALETTE["GRAY"]
ACCENT = DARK_PALETTE["ACCENT"]
ACCENT2 = DARK_PALETTE["ACCENT2"]
GREEN = DARK_PALETTE["GREEN"]
RED = DARK_PALETTE["RED"]
YELLOW = DARK_PALETTE["YELLOW"]
CYAN = DARK_PALETTE["CYAN"]
PURPLE = DARK_PALETTE["PURPLE"]
PINK = DARK_PALETTE["PINK"]
ORANGE = DARK_PALETTE["ORANGE"]
BLUE = DARK_PALETTE["BLUE"]
DARK = DARK_PALETTE["TEXT_ON_ACCENT"]
WHITE = "#ffffff"
BLACK = "#000000"

current_name = "dark"

_WHITE_TEXT_ACCENTS = {
    "White",
    "Blue",
    "Purple",
    "Green",
    "Orange",
    "Red",
    "Pink",
    "Cyan",
}
_DARK_TEXT_ACCENTS = set()

_current_accent_name = "White"

SOFT_BORDER_DARK = "#2b2b2b"
SOFT_BORDER_LIGHT = "#d4d4d4"


def theme_display_name(code=None):
    code = code or current_name
    if code == "light":
        return "Light"
    return "Dark"


def apply(name):
    global current_name
    current_name = "light" if name == "light" else "dark"
    palette = LIGHT_PALETTE if current_name == "light" else DARK_PALETTE
    g = globals()
    for k in (
        "BG",
        "BG2",
        "BG3",
        "BORDER",
        "FG",
        "GRAY",
        "ACCENT",
        "ACCENT2",
        "GREEN",
        "RED",
        "YELLOW",
        "CYAN",
        "PURPLE",
        "PINK",
        "ORANGE",
        "BLUE",
        "WHITE",
        "BLACK",
    ):
        g[k] = palette[k]
    g["DARK"] = palette["TEXT_ON_ACCENT"]


def apply_accent(name):
    global _current_accent_name
    g = globals()
    a = ACCENTS.get(name, ACCENTS["White"])
    g["ACCENT"] = a["ACCENT"]
    g["ACCENT2"] = a["ACCENT2"]
    _current_accent_name = name if name in ACCENTS else "White"


def accent_text():
    if _current_accent_name in _DARK_TEXT_ACCENTS:
        return "#000000"
    if _current_accent_name in _WHITE_TEXT_ACCENTS:
        return "#ffffff"
    a = (ACCENT or "#ffffff").lstrip("#")
    try:
        r, g, b = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
    except Exception:  # noqa: BLE001
        return WHITE
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if lum > 0.6 else "#ffffff"


on_accent = accent_text


def _rgba(hex_color, alpha):
    s = (hex_color or "#000000").lstrip("#")
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except Exception:  # noqa: BLE001
        r = g = b = 0
    return f"rgba({r},{g},{b},{max(0, min(255, int(alpha)))})"


def _hex_rgb(h):
    s = (h or "#000000").lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except Exception:  # noqa: BLE001
        return (0, 0, 0)


def is_light_accent():
    r, g, b = _hex_rgb(ACCENT)
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return lum > 0.6


def accent_fill(alpha=200):
    if is_light_accent():
        return ACCENT
    return _rgba(ACCENT, alpha)


def accent_fill_hover(alpha=170):
    if is_light_accent():
        return ACCENT2
    return _rgba(ACCENT2, alpha)


def panel_bg(alpha=235):
    return _rgba(BG2, alpha)


def panel_soft(alpha=200):
    return _rgba(BG3, alpha)


def panel_glass(alpha=176):
    return _rgba(BG2, alpha)


def panel_dim(alpha=150):
    return _rgba(BG2, alpha)


def glass_accent(alpha=120):
    return _rgba(ACCENT, alpha)


def glass_accent_hover(alpha=170):
    return _rgba(ACCENT2, alpha)


def soft_border():
    return SOFT_BORDER_LIGHT if current_name == "light" else SOFT_BORDER_DARK


def _is_light_bg():
    return current_name == "light"


def popup_bg():
    accent_light = is_light_accent()
    if _is_light_bg():
        return _rgba(BG2, 245)
    if accent_light:
        return _rgba(BG2, 245)
    return _rgba(BG2, 240)


def popup_hover():
    if _is_light_bg():
        return _rgba(ACCENT, 60)
    if is_light_accent():
        return _rgba(ACCENT, 90)
    return _rgba(ACCENT2, 140)


def popup_fg():
    return FG


def popup_border():
    return _rgba(ACCENT, 60)
