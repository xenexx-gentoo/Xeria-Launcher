#!/usr/bin/env python3
import argparse
import os
import shutil
import sys
from pathlib import Path

PY_CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
PY_CACHE_SUFFIXES = {".pyc", ".pyo"}


HERE = Path(__file__).parent.resolve()
ROOT = HERE.parent


def _looks_like_xeria(root: Path) -> tuple:
    reasons = []
    matches = 0

    entry = root / "xeria.pyw"
    if entry.is_file():
        matches += 1
        reasons.append(f"found {entry.name}")
    else:
        reasons.append(f"missing {entry.name}")

    src = root / "src"
    if (src / "ui" / "launcher.py").is_file():
        matches += 1
        reasons.append("found src/ui/launcher.py")
    else:
        reasons.append("missing src/ui/launcher.py")

    if (src / "core" / "paths.py").is_file():
        matches += 1
        reasons.append("found src/core/paths.py")
    else:
        reasons.append("missing src/core/paths.py")

    if (src / "browse" / "base.py").is_file():
        matches += 1
        reasons.append("found src/browse/base.py")
    else:
        reasons.append("missing src/browse/base.py")

    lang = root / "lang"
    if lang.is_dir() and any(lang.glob("*.json")):
        matches += 1
        reasons.append("found lang/*.json")
    else:
        reasons.append("missing lang/*.json")

    return matches >= 2, reasons


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _fmt(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def _walk_remove_py_cache(dry_run: bool):
    removed = 0
    freed = 0
    for current, dirs, files in os.walk(ROOT, topdown=True):
        cur = Path(current)
        for d in list(dirs):
            if d in PY_CACHE_DIRS:
                target = cur / d
                size = _dir_size(target)
                if dry_run:
                    print(f"  would remove {target}  ({_fmt(size)})")
                else:
                    shutil.rmtree(target, ignore_errors=True)
                    print(f"  removed {target}  ({_fmt(size)})")
                dirs.remove(d)
                removed += 1
                freed += size
        for f in files:
            p = cur / f
            if p.suffix in PY_CACHE_SUFFIXES:
                size = _file_size(p)
                if dry_run:
                    print(f"  would remove {p}  ({_fmt(size)})")
                else:
                    try:
                        p.unlink()
                        print(f"  removed {p}  ({_fmt(size)})")
                    except OSError as e:
                        print(f"  failed {p}: {e}")
                        continue
                removed += 1
                freed += size
    return removed, freed


def _remove_path(path: Path, dry_run: bool, label: str):
    if not path.exists():
        return 0
    size = _dir_size(path) if path.is_dir() else _file_size(path)
    if dry_run:
        print(f"  would remove {label}: {path}  ({_fmt(size)})")
        return size
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        print(f"  removed {label}: {path}  ({_fmt(size)})")
        return size
    except OSError as e:
        print(f"  failed {label}: {path}  ({e})")
        return 0


def _xeria_root() -> Path:
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from core.paths import XERIA_ROOT

        return XERIA_ROOT
    except Exception:  # noqa: BLE001
        import platform

        if platform.system() == "Windows":
            return Path(os.getenv("APPDATA", str(Path.home()))) / "Xeria"
        if platform.system() == "Darwin":
            return Path.home() / "Library" / "Application Support" / "Xeria"
        return Path.home() / ".xeria"


def main():
    ap = argparse.ArgumentParser(
        prog="debug/clear.py",
        description="Clear Python caches and Xeria Launcher settings.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without removing it",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Skip the 'is this really Xeria?' sanity check",
    )
    ap.add_argument(
        "--keep-cache",
        action="store_true",
        help="Keep the launcher's icon/app cache directory",
    )
    ap.add_argument(
        "--keep-settings",
        action="store_true",
        help="Keep settings.json (accounts, JVM flags, theme, etc.)",
    )
    ap.add_argument(
        "--keep-instances",
        action="store_true",
        help="Keep the profiles/ directory (user instances)",
    )
    ap.add_argument(
        "--keep-java", action="store_true", help="Keep downloaded Java runtimes"
    )
    args = ap.parse_args()

    print(f"Script dir: {HERE}")
    print(f"Repository root: {ROOT}")
    print()

    print("Sanity check:")
    ok, reasons = _looks_like_xeria(ROOT)
    for r in reasons:
        print(f"  {r}")
    print()

    if not ok and not args.force:
        print("This does not look like an Xeria Launcher repository.")
        print("Refusing to run. Pass --force to override.")
        return 1

    print("Python caches:")
    count, freed_py = _walk_remove_py_cache(args.dry_run)
    print(f"  -> {count} item(s), {_fmt(freed_py)}")
    print()

    xeria = _xeria_root()
    print(f"Xeria root: {xeria}")

    freed = 0

    if not args.keep_settings:
        freed += _remove_path(xeria / "settings.json", args.dry_run, "settings")
    if not args.keep_cache:
        freed += _remove_path(xeria / "cache", args.dry_run, "cache")
    if not args.keep_instances:
        freed += _remove_path(xeria / "profiles", args.dry_run, "profiles")
    if not args.keep_java:
        freed += _remove_path(xeria / "java", args.dry_run, "java runtimes")

    print()
    print(f"Total freed: {_fmt(freed_py + freed)}")

    if args.dry_run:
        print()
        print("Dry run. Nothing was actually removed.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
