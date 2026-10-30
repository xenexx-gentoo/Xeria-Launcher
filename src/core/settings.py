import contextlib
import json
import platform

from core.paths import XERIA_ROOT

SETTINGS_FILE = XERIA_ROOT / "settings.json"

DEFAULTS = {
    "username": "Player",
    "language": "",
    "java_path": "",
    "wrapper_command": "",
    "jvm_flags": "",
    "default_jvm_flags": "",
    "env_vars": "",
    "gc": "G1GC",
    "auto_nvidia_fix": False,
    "theme": "dark",
    "accent": "White",
    "account": {},
    "accounts": [],
    "active_account": 0,
    "auto_check_interval": 86400,
    "auto_check_last_run": 0,
}


class Settings:
    def __init__(self):
        self._data = dict(DEFAULTS)
        if SETTINGS_FILE.exists():
            with contextlib.suppress(Exception):
                self._data.update(json.loads(SETTINGS_FILE.read_text()))

    def get(self, key, default=None):
        return self._data.get(
            key, default if default is not None else DEFAULTS.get(key)
        )

    def set(self, key, value):
        self._data[key] = value

    def save(self):
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(self._data, indent=2))

    def get_language(self):
        return self.get("language", "") or ""

    def set_language(self, code):
        self.set("language", code)
        self.save()

    def get_account(self):
        from core import auth

        return auth.Account(self.get("account", {}))

    def set_account(self, acc):
        self.set("account", acc.to_dict())
        self.save()

    def get_accounts(self):
        accs = self.get("accounts", None)
        if accs is None or not isinstance(accs, list) or len(accs) == 0:
            accs = []
            legacy = self.get("account", {})
            if legacy and legacy.get("name"):
                accs.append(
                    {
                        "type": "online",
                        "name": legacy.get("name", ""),
                        "data": legacy,
                    }
                )
            self.set("accounts", accs)
        return accs

    def set_accounts(self, accs):
        self.set("accounts", accs)
        self.save()

    def get_active_account(self):
        accs = self.get_accounts()
        idx = self.get("active_account", 0)
        if isinstance(idx, int) and 0 <= idx < len(accs):
            return accs[idx]
        return None

    def set_active_account(self, idx):
        self.set("active_account", idx)
        self.save()

    def active_online_account(self):
        from core import auth

        a = self.get_active_account()
        if not a or a.get("type") != "online":
            return auth.Account()
        return auth.Account(a.get("data", {}))

    def active_offline_name(self):
        a = self.get_active_account()
        if a and a.get("type") == "offline":
            return a.get("name") or "Player"
        return (self.get("username") or "Player").strip() or "Player"


def detect_gpu():
    if platform.system() == "Windows":
        return "unknown"
    import glob
    import os

    if glob.glob("/proc/driver/nvidia/version"):
        return "nvidia"
    if os.path.exists("/usr/bin/nvidia-smi"):
        return "nvidia"
    for v in glob.glob("/sys/class/drm/card*/device/vendor"):
        with contextlib.suppress(Exception):
            with open(v) as f:
                vid = f.read().strip()
            if vid == "0x1002":
                return "amd"
            if vid == "0x10de":
                return "nvidia"
            if vid == "0x8086":
                return "intel"
    return "unknown"
