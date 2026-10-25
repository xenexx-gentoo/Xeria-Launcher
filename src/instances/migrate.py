from pathlib import Path
import shutil

from core.paths import PROFILES_DIR
from core import translate
from core.worker import _shutdown
from instances.profile import Profile
from integration import modrinth, net as http


SOURCE_FOLDERS = ("mods", "resourcepacks", "shaderpacks")
KIND_BY_FOLDER = {
    "mods": "mod",
    "resourcepacks": "resourcepack",
    "shaderpacks": "shader",
}


def verify_one(path, mc_version, kind, loader):
    concrete = (loader or "vanilla").lower() if kind == "mod" else None
    try:
        sha1 = modrinth._sha1_file(path)
    except Exception:
        return False
    info = modrinth.project_from_hash(sha1)
    project_id = info.get("project_id") if info else None
    version_id = info.get("version_id") if info else None

    if not project_id:
        project_id = modrinth.project_id_from_filename(Path(path).name)
        version_id = None

    if not project_id:
        return False

    if version_id:
        for v in modrinth.list_versions(project_id):
            if v.get("id") != version_id:
                continue
            return modrinth._version_compatible(
                v, mc_version, kind, concrete)

    latest = modrinth.latest_file(
        project_id, mc_version, kind, concrete)
    return latest is not None


def scan_profile(profile):
    path = profile.dir
    info = {
        "profile": profile,
        "path": path,
        "mods": [],
        "resourcepacks": [],
        "shaderpacks": [],
        "has_config": False,
        "has_saves": False,
        "has_options": False,
        "has_servers": False,
    }
    for sub in SOURCE_FOLDERS:
        d = path / sub
        if not d.exists() or not d.is_dir():
            continue
        files = [f for f in d.iterdir()
                 if f.is_file() and f.suffix.lower() in (".jar", ".zip")]
        info[sub] = sorted(files, key=lambda f: f.name.lower())
    info["has_config"] = (path / "config").is_dir()
    info["has_saves"] = (path / "saves").is_dir()
    info["has_options"] = (path / "options.txt").is_file()
    info["has_servers"] = (path / "servers.dat").is_file()
    return info


def _resolve_source_file(path):
    try:
        sha1 = modrinth._sha1_file(path)
    except Exception:
        return None, "", path.stem

    info = modrinth.project_from_hash(sha1)
    if info and info.get("project_id"):
        title = info.get("name") or path.stem
        try:
            proj = modrinth.fetch_project(info["project_id"])
            if proj and proj.get("title"):
                title = proj["title"]
        except Exception:
            pass
        return (info["project_id"],
                info.get("version_number", ""),
                title)

    pid = modrinth.project_id_from_filename(path.name)
    if pid:
        title = path.stem
        try:
            proj = modrinth.fetch_project(pid)
            if proj and proj.get("title"):
                title = proj["title"]
        except Exception:
            pass
        return pid, "", title

    return None, "", path.stem


def check_files(files, mc_version, kind, loader, log=None, progress=None):
    out = {}
    total = len(files)
    if total == 0:
        return out

    concrete_loader = (loader or "vanilla").lower()
    target_loader = concrete_loader if kind == "mod" else None

    for i, p in enumerate(files, 1):
        if log:
            log("sys", f"Checking {p.name} ({i}/{total})")
        project_id, old_ver, title = _resolve_source_file(p)
        if not project_id:
            out[str(p)] = {
                "compatible": False,
                "project_id": None,
                "title": title,
                "reason": "Not on Modrinth",
                "download_url": "",
                "download_name": "",
            }
            if progress:
                progress(i, total)
            continue

        latest = modrinth.latest_file(
            project_id, mc_version, kind, target_loader)
        if latest:
            url, fname, new_ver = latest
            if old_ver and new_ver and old_ver != new_ver:
                reason = f"Update to {new_ver}"
            else:
                reason = f"Install {new_ver or 'latest'}"
            out[str(p)] = {
                "compatible": True,
                "project_id": project_id,
                "title": title,
                "reason": reason,
                "download_url": url,
                "download_name": fname,
            }
        else:
            out[str(p)] = {
                "compatible": False,
                "project_id": project_id,
                "title": title,
                "reason": f"No build for {mc_version}",
                "download_url": "",
                "download_name": "",
            }
        if progress:
            progress(i, total)
    return out


def create_profile(source_profile, name, mc_version):
    base = name
    n = 1
    while (PROFILES_DIR / f"{name}.json").exists():
        name = f"{base} ({n})"
        n += 1
    p = Profile(name)
    p.version = mc_version
    p.loader = source_profile.loader
    p.ram = source_profile.ram
    p.override_gc = getattr(source_profile, "override_gc", "")
    p.override_jvm_flags = getattr(
        source_profile, "override_jvm_flags", "")
    p.override_env_vars = getattr(
        source_profile, "override_env_vars", "")
    p.override_java_path = getattr(
        source_profile, "override_java_path", "")
    p.override_wrapper = getattr(
        source_profile, "override_wrapper", "")
    p.dir
    p.save()
    return p


def _walk_copy(src_dir, dst_dir, items):
    dst_dir.mkdir(parents=True, exist_ok=True)
    for f in src_dir.rglob("*"):
        if f.is_file():
            rel = f.relative_to(src_dir)
            items.append((f, dst_dir / rel))


def _cleanup_target(target_profile, mc_version, loader,
                    log=None, progress=None):
    tasks = []
    for folder, kind in KIND_BY_FOLDER.items():
        d = target_profile.dir / folder
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.is_file() and f.suffix.lower() in (".jar", ".zip"):
                tasks.append((kind, f))

    total = len(tasks)
    if not total:
        return 0

    removed = 0
    for i, (kind, path) in enumerate(tasks, 1):
        if _shutdown.is_set():
            break
        if progress:
            progress(i, total)
        if not verify_one(path, mc_version, kind, loader):
            try:
                path.unlink()
                removed += 1
                if log:
                    log("warn", translate.t(
                        "console.removed_incompat",
                        name=path.name, version=mc_version))
            except Exception as e:
                if log:
                    log("error", translate.t(
                        "console.remove_failed",
                        name=path.name, err=e))
    return removed


def apply_plan(target_profile, plan, mc_version, loader,
               log=None, progress=None):
    target = target_profile.dir
    target.mkdir(parents=True, exist_ok=True)

    downloads = []
    for kind in SOURCE_FOLDERS:
        for item in plan[kind]:
            src_path, dst_rel, url, filename, title = item
            downloads.append((kind, src_path, dst_rel, url,
                              filename, title))

    plain_items = []
    if plan.get("copy_config"):
        src_dir = plan.get("_source_config_dir")
        if src_dir and src_dir.exists():
            _walk_copy(src_dir, target / "config", plain_items)
    if plan.get("copy_saves"):
        src_dir = plan.get("_source_saves_dir")
        if src_dir and src_dir.exists():
            _walk_copy(src_dir, target / "saves", plain_items)
    if plan.get("copy_options"):
        p = plan.get("_source_options")
        if p and p.exists():
            plain_items.append((p, target / "options.txt"))
    if plan.get("copy_servers"):
        p = plan.get("_source_servers")
        if p and p.exists():
            plain_items.append((p, target / "servers.dat"))

    total = len(downloads) + len(plain_items)
    installed = 0
    failed = 0

    for i, (kind, src_path, dst_rel, url, filename, title) in enumerate(
            downloads, 1):
        if _shutdown.is_set():
            if log:
                log("warn", "Shutdown requested, stopping migration")
            break
        if not url or not filename:
            failed += 1
            if log:
                log("warn", f"No download for {title or src_path.name}")
            if progress:
                progress(i, total)
            continue
        folder = dst_rel.split("/", 1)[0] if "/" in dst_rel else "mods"
        dst = target / folder / filename
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".part")
        try:
            with http.stream("GET", url) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(65536):
                        f.write(chunk)
            tmp.replace(dst)
            installed += 1
            if log:
                log("ok", f"Downloaded {filename}")
        except Exception as e:
            failed += 1
            if log:
                log("error", f"Failed to download {filename}: {e}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
        if progress:
            progress(i, total)

    for j, (src, dst) in enumerate(
            plain_items, len(downloads) + 1):
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
        except Exception as e:
            if log:
                log("warn", f"Failed to copy {src.name}: {e}")
        if progress:
            progress(j, total)

    _cleanup_target(target_profile, mc_version, loader,
                    log=log, progress=progress)

    return installed, len(plan.get("skipped", [])), failed
