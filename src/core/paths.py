import os
import platform
import subprocess
from pathlib import Path

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

if IS_WIN:
    MC_ROOT = Path(os.getenv("APPDATA", str(Path.home()))) / ".minecraft"
    XERIA_ROOT = Path(os.getenv("APPDATA", str(Path.home()))) / "Xeria"
elif IS_MAC:
    MC_ROOT = Path.home() / "Library" / "Application Support" / "minecraft"
    XERIA_ROOT = Path.home() / "Library" / "Application Support" / "Xeria"
else:
    MC_ROOT = Path.home() / ".minecraft"
    XERIA_ROOT = Path.home() / ".xeria"

PROFILES_DIR = XERIA_ROOT / "profiles"
JAVA_DIR = XERIA_ROOT / "java"
USERNAME_FILE = XERIA_ROOT / "username.txt"
SETTINGS_FILE = XERIA_ROOT / "settings.json"

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ADOPTIUM_API = "https://api.adoptium.net/v3"
MODRINTH_API = "https://api.modrinth.com/v2"

for d in (MC_ROOT, PROFILES_DIR, JAVA_DIR):
    d.mkdir(parents=True, exist_ok=True)

NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0

if IS_WIN:
    _orig_popen_init = subprocess.Popen.__init__

    def _patched_popen_init(self, *args, **kwargs):
        if "creationflags" not in kwargs:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return _orig_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_popen_init
