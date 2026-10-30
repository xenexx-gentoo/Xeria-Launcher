import os
import platform
import shutil
from pathlib import Path

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"


def _total_ram_gb():
    try:
        if IS_LINUX:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb / 1024 / 1024
        if IS_MAC:
            import subprocess

            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return int(out.stdout.strip()) / 1024 / 1024 / 1024
        if IS_WIN:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / 1024 / 1024 / 1024
    except Exception:  # noqa: BLE001, S110
        pass
    return 0.0


def _cpu_count():
    try:
        return os.cpu_count() or 1
    except Exception:  # noqa: BLE001
        return 1


def _free_disk_gb(path):
    try:
        return shutil.disk_usage(str(path)).free / 1024 / 1024 / 1024
    except Exception:  # noqa: BLE001
        return 0.0


def gpu_label(name):
    if not name:
        return "UNKNOWN"
    return name.upper()


def _fmt_num(v):
    s = f"{v:.1f}"
    s = s.removesuffix(".0")
    return s


class HardwareProfile:
    def __init__(self):
        self.ram_gb = _total_ram_gb()
        self.cpus = _cpu_count()
        self.free_disk_gb = _free_disk_gb(Path.home())
        self.tier = self._classify()
        self._apply()

    def _classify(self):
        if self.ram_gb < 4 or self.cpus < 2:
            return "potato"
        if self.ram_gb < 8 or self.cpus < 4 or self.free_disk_gb < 1.0:
            return "low"
        return "capable"

    def _apply(self):
        t = self.tier
        if t == "potato":
            self.enable_icon_cache = False
            self.enable_body_cache = False
            self.enable_gallery_cache = False
            self.enable_disk_cache = False
            self.icon_decode_threads = 1
            self.gallery_decode_threads = 1
            self.icon_max_parallel = 2
            self.gallery_max_shots = 3
            self.library_workers = 2
            self.asset_workers = 4
            self.prefetch_icons = False
            self.icon_prefetch_ahead = 0
            self.animations = False
        elif t == "low":
            self.enable_icon_cache = True
            self.enable_body_cache = True
            self.enable_gallery_cache = True
            self.enable_disk_cache = True
            self.icon_decode_threads = 1
            self.gallery_decode_threads = 1
            self.icon_max_parallel = 3
            self.gallery_max_shots = 4
            self.library_workers = 4
            self.asset_workers = 8
            self.prefetch_icons = True
            self.icon_prefetch_ahead = 1
            self.animations = True
        else:
            self.enable_icon_cache = True
            self.enable_body_cache = True
            self.enable_gallery_cache = True
            self.enable_disk_cache = True
            self.icon_decode_threads = 2
            self.gallery_decode_threads = 2
            self.icon_max_parallel = 4
            self.gallery_max_shots = 6
            self.library_workers = 8
            self.asset_workers = 16
            self.prefetch_icons = True
            self.icon_prefetch_ahead = 2
            self.animations = True

    def tier_label(self):
        from core import translate

        return translate.t(f"tier.{self.tier}")

    def summary(self):
        return (
            f"tier={self.tier} ram={self.ram_gb:.1f}GB "
            f"cpus={self.cpus} disk={self.free_disk_gb:.1f}GB"
        )

    def summary_lines(self):
        from core import translate

        return [
            (translate.t("about.performance_tier"), self.tier_label()),
            (translate.t("about.ram"), f"{_fmt_num(self.ram_gb)} GB"),
            (translate.t("about.cpu_cores"), str(self.cpus)),
            (translate.t("about.disk"), f"{_fmt_num(self.free_disk_gb)} GB"),
        ]


_instance = None


def get():
    global _instance
    if _instance is None:
        _instance = HardwareProfile()
    return _instance
