import contextlib
import json
import shutil
from pathlib import Path

from core.paths import PROFILES_DIR


class Profile:
    def __init__(self, name):
        self.name = name
        self.version = ""
        self.ram = "4"
        self.loader = "vanilla"
        self.loader_version = ""

        self.override_gc = ""
        self.override_jvm_flags = ""
        self.override_env_vars = ""
        self.override_java_path = ""
        self.override_wrapper = ""
        self.override_nvidia_fix = False

        self.mods_meta = {}
        self._external_dir = None

    @property
    def dir(self):
        if self._external_dir is not None:
            return self._external_dir
        d = PROFILES_DIR / self.name
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def json_path(self):
        return PROFILES_DIR / f"{self.name}.json"

    def to_dict(self):
        return {
            "name": self.name,
            "version": self.version,
            "ram": self.ram,
            "loader": self.loader,
            "loader_version": self.loader_version,
            "override_gc": self.override_gc,
            "override_jvm_flags": self.override_jvm_flags,
            "override_env_vars": self.override_env_vars,
            "override_java_path": self.override_java_path,
            "override_wrapper": self.override_wrapper,
            "override_nvidia_fix": self.override_nvidia_fix,
            "mods_meta": self.mods_meta,
            "_external_dir": (str(self._external_dir) if self._external_dir else None),
        }

    def load(self, data):
        self.version = data.get("version", self.version)
        self.ram = str(data.get("ram", self.ram))
        self.loader = data.get("loader", self.loader)
        self.loader_version = data.get("loader_version", "")
        self.override_gc = data.get("override_gc", "")
        self.override_jvm_flags = data.get("override_jvm_flags", "")
        self.override_env_vars = data.get("override_env_vars", "")
        self.override_java_path = data.get("override_java_path", "")
        self.override_wrapper = data.get("override_wrapper", "")
        self.override_nvidia_fix = bool(data.get("override_nvidia_fix", False))
        mm = data.get("mods_meta", {})
        if isinstance(mm, dict):
            self.mods_meta = mm
        else:
            self.mods_meta = {}
        ext = data.get("_external_dir")
        if ext:
            self._external_dir = Path(ext)

    def save(self):
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        self.json_path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load_all(cls):
        if not PROFILES_DIR.exists():
            return []
        profiles = []
        for p in sorted(PROFILES_DIR.glob("*.json")):
            try:
                data = json.loads(p.read_text())
                prof = cls(p.stem)
                prof.load(data)
                profiles.append(prof)
            except Exception:  # noqa: BLE001, S112
                continue
        return profiles

    @classmethod
    def delete(cls, name):
        json_path = PROFILES_DIR / f"{name}.json"
        instance_dir = PROFILES_DIR / name
        with contextlib.suppress(Exception):
            if json_path.exists():
                json_path.unlink()
        with contextlib.suppress(Exception):
            if instance_dir.exists() and instance_dir.is_dir():
                shutil.rmtree(instance_dir)
