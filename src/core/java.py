import contextlib
import glob
import os
import platform
import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

from core.paths import ADOPTIUM_API, IS_WIN, JAVA_DIR, MC_ROOT, NO_WINDOW
from integration import net as http


def recommended_java_for(mc_version):
    try:
        p = mc_version.split(".")
        major = int(p[0])
        minor = int(p[1]) if len(p) > 1 else 0
        patch = int(p[2]) if len(p) > 2 else 0
    except Exception:  # noqa: BLE001
        return 25
    if major >= 26:
        return 25
    if major != 1:
        return 25
    if minor >= 22:
        return 25
    if minor == 21:
        return 25 if patch >= 9 else 21
    if minor == 20:
        return 21 if patch >= 5 else 17
    if minor >= 18:
        return 17
    if minor == 17:
        return 16
    return 8


def java_version(path):
    try:
        out = subprocess.run(
            [str(path), "-version"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=NO_WINDOW,
            check=False,
        )
    except Exception:  # noqa: BLE001
        return None, None
    txt = (out.stderr or "") + "\n" + (out.stdout or "")
    if "version" not in txt.lower():
        return None, None
    m = re.search(r'version "([^"]+)"', txt) or re.search(r"version (\S+)", txt)
    ver = m.group(1) if m else "?"
    try:
        major = (
            int(ver.split(".")[1])
            if ver.startswith("1.")
            else int(re.match(r"(\d+)", ver).group(1))
        )
    except Exception:  # noqa: BLE001
        major = None
    return ver, major


def find_javas():
    raw = set()

    def add(p):
        if p:
            raw.add(str(p))

    if IS_WIN:
        roots = [
            r"C:\Program Files\Java",
            r"C:\Program Files (x86)\Java",
            r"C:\Program Files\Eclipse Adoptium",
            r"C:\Program Files\Microsoft",
            r"C:\Program Files\Zulu",
            r"C:\Program Files\Amazon Corretto",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Eclipse Adoptium"),
            os.path.expandvars(r"%USERPROFILE%\.jdks"),
            str(MC_ROOT / "runtime"),
        ]
        for r in roots:
            if not os.path.isdir(r):
                continue
            add(os.path.join(r, "bin", "java.exe"))
            for n in os.listdir(r):
                sub = os.path.join(r, n)
                if os.path.isdir(sub):
                    add(os.path.join(sub, "bin", "java.exe"))
                    add(os.path.join(sub, "jre", "bin", "java.exe"))
        for w in (shutil.which("java.exe"), shutil.which("java")):
            add(w)
        jh = os.environ.get("JAVA_HOME")
        if jh:
            add(os.path.join(jh, "bin", "java.exe"))
    else:
        for p in ("/usr/bin/java", "/usr/local/bin/java"):
            add(p)
        for pat in (
            "/usr/lib/jvm/*/bin/java",
            "/usr/lib/jvm/*/jre/bin/java",
            "/usr/lib/jvm/*/*/bin/java",
            "/opt/*/bin/java",
            os.path.expanduser("~/.sdkman/candidates/java/*/bin/java"),
            os.path.expanduser("~/.jdks/*/bin/java"),
            str(MC_ROOT / "runtime/*/*/bin/java"),
        ):
            raw.update(glob.glob(pat))
        add(shutil.which("java"))
        jh = os.environ.get("JAVA_HOME")
        if jh:
            add(os.path.join(jh, "bin", "java"))

    for p in JAVA_DIR.rglob("java" if not IS_WIN else "java.exe"):
        add(str(p))

    resolved = set()
    for c in raw:
        try:
            resolved.add(c)
            resolved.add(os.path.realpath(c))
        except Exception:  # noqa: BLE001
            resolved.add(c)

    found = {}
    for c in resolved:
        try:
            if not Path(c).is_file():
                continue
            if not IS_WIN and not os.access(c, os.X_OK):
                continue
        except Exception:  # noqa: BLE001, S112
            continue
        ver, major = java_version(c)
        if ver:
            found[c] = (ver, major or 0)

    def _rank(item):
        path, (ver, major) = item
        norm = path.replace("\\", "/").lower()
        pri = 0
        if "/runtime/" in norm:
            pri = 3
        else:
            jh = os.environ.get("JAVA_HOME", "").replace("\\", "/").lower()
            if jh and norm.startswith(jh):
                pri = 2
            elif "/.jdks/" in norm or "/.sdkman/" in norm:
                pri = 1
        return (major, pri, ver)

    by_major = {}
    for item in found.items():
        major = item[1][1]
        cur = by_major.get(major)
        if cur is None or _rank(item) > _rank(cur):
            by_major[major] = item

    out = []
    for major, item in by_major.items():
        path, (ver, _mj) = item
        if major and major >= 9:
            label = f"JDK {major}"
        else:
            label = f"Java {ver}"
        out.append((path, (label, major)))

    return sorted(out, key=lambda x: -x[1][1])


def install_java(ver, log=None):
    osname = {"Windows": "windows", "Linux": "linux", "Darwin": "mac"}.get(
        platform.system(), "linux"
    )
    arch = platform.machine().lower()
    arch = (
        "x64"
        if arch in ("x86_64", "amd64")
        else ("aarch64" if arch in ("aarch64", "arm64") else "x64")
    )
    url = (
        f"{ADOPTIUM_API}/assets/latest/{ver}/hotspot"
        f"?architecture={arch}&image_type=jre&os={osname}&vendor=eclipse"
    )
    try:
        info = http.get(url).json()
        if not info:
            return None
        pkg = info[0]["binary"]["package"]
        link, fname, rel = pkg["link"], pkg["name"], info[0]["release_name"]
    except Exception as e:  # noqa: BLE001
        if log:
            log("error", f"adoptium: {e}")
        return None

    dest = JAVA_DIR / rel
    exe = "java.exe" if IS_WIN else "java"
    if not (dest / "bin").exists():
        if log:
            log("java", f"downloading temurin {ver} ({fname})")
        archive = JAVA_DIR / fname
        try:
            with http.stream("GET", link) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                done = 0
                with open(archive, "wb") as f:
                    for chunk in r.iter_bytes(65536):
                        f.write(chunk)
                        done += len(chunk)
                        if log and total and done % (1024 * 1024) < 65536:
                            log("java", f"  {done * 100 // total}%")
            if fname.endswith(".zip"):
                with zipfile.ZipFile(archive) as z:
                    z.extractall(dest)
            else:
                with tarfile.open(archive) as t:
                    t.extractall(dest)
        except Exception as e:  # noqa: BLE001
            if log:
                log("error", f"download failed: {e}")
            return None
        finally:
            with contextlib.suppress(Exception):
                archive.unlink()

    hits = [m for m in dest.rglob(exe) if m.is_file()]
    if not hits:
        return None
    path = str(hits[0])
    if not IS_WIN:
        with contextlib.suppress(Exception):
            os.chmod(path, 0o755)
    return path


def best_java(mc_version, log=None, override="", required_major=None):
    if override and Path(override).exists():
        return override
    want = required_major if required_major else recommended_java_for(mc_version)
    if log:
        log("java", f"need java {want} for {mc_version}")
    installed = find_javas()
    for path, (label, major) in installed:
        if major == want:
            if log:
                log("java", f"using {label}")
            return path
    for path, (label, major) in installed:
        if major and want <= major <= want + 4:
            if log:
                log("java", f"using {label} (newer than needed)")
            return path
    if log:
        log("java", f"java {want} not found - fetching from Adoptium")
    fetched = install_java(want, log)
    if fetched:
        if log:
            log("java", f"installed JDK {want}")
        return fetched
    for path, (label, major) in installed:
        if major == 25:
            if log:
                log("java", f"fallback {label}")
            return path
    return None
