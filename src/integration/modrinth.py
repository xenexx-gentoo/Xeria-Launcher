import json
import hashlib
import time
import threading
import re as _re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from core.paths import MODRINTH_API


UA = "Xeria-Launcher/2.504"
HEADERS = {"User-Agent": UA, "Accept": "application/json"}

_session = None
_session_lock = threading.Lock()

_FILENAME_CACHE = {}


def _s():
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = requests.Session()
                _session.headers.update(HEADERS)
    return _session


def _get(url, **kwargs):
    try:
        r = _s().get(url, timeout=20, **kwargs)
    except requests.RequestException:
        return None
    if r.status_code in (429, 500, 502, 503, 504):
        time.sleep(1.5)
        try:
            r = _s().get(url, timeout=20, **kwargs)
        except requests.RequestException:
            return None
    return r


def search(query, kind, mc_version=None, loader=None, limit=30):
    facets = [[f"project_type:{kind}"]]
    if mc_version and kind != "modpack":
        facets.append([f"versions:{mc_version}"])
    if kind == "mod" and loader and loader != "vanilla":
        facets.append([f"categories:{loader}"])
    r = _get(f"{MODRINTH_API}/search", params={
        "query": query, "limit": limit, "facets": json.dumps(facets)})
    if r is None or r.status_code != 200:
        return []
    return [{"id": h["project_id"], "title": h["title"], "author": h["author"],
             "desc": h.get("description", ""), "dl": h.get("downloads", 0),
             "categories": h.get("categories", [])}
            for h in r.json().get("hits", [])]


def list_versions(project_id):
    r = _get(f"{MODRINTH_API}/project/{project_id}/version")
    if r is None or r.status_code != 200:
        return []
    try:
        data = r.json()
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _loader_matches(want, x):
    """Strict: True only if version x supports loader `want`.
    No Forge <-> NeoForge swap. Vanilla matches only files with no
    loaders tags or a `vanilla` tag."""
    want = (want or "vanilla").lower()
    xl = [str(l).lower() for l in (x.get("loaders") or [])]
    if want == "vanilla":
        return not xl or "vanilla" in xl
    return want in xl


def _version_compatible(x, mc_version, kind, loader):
    if mc_version and mc_version not in x.get("game_versions", []):
        return False
    if kind == "mod":
        if not _loader_matches(loader, x):
            return False
    return True


def _primary_file(x):
    files = x.get("files", [])
    if not files:
        return None
    return next((f for f in files if f.get("primary")), files[0])


def pick_file(project_id, mc_version, kind, loader=None, version_id=None):
    versions = list_versions(project_id)
    if not versions:
        return None
    if version_id:
        for x in versions:
            if x.get("id") == version_id:
                prim = _primary_file(x)
                if prim is None:
                    return None
                return prim["url"], prim["filename"]
        return None
    candidates = [x for x in versions
                  if _version_compatible(x, mc_version, kind, loader)]
    if not candidates:
        return None
    candidates.sort(key=lambda v: v.get("published", ""), reverse=True)
    prim = _primary_file(candidates[0])
    if prim is None:
        return None
    return prim["url"], prim["filename"]


def latest_file(project_id, mc_version, kind, loader=None):
    versions = list_versions(project_id)
    candidates = [x for x in versions
                  if _version_compatible(x, mc_version, kind, loader)]
    if not candidates:
        return None
    candidates.sort(key=lambda v: v.get("published", ""), reverse=True)
    prim = _primary_file(candidates[0])
    if prim is None:
        return None
    return (prim["url"], prim["filename"],
            candidates[0].get("version_number", ""))


def search_modpacks(query, limit=20):
    return search(query, "modpack", None, None, limit=limit)


def pick_modpack_file(project_id):
    r = _get(f"{MODRINTH_API}/project/{project_id}/version")
    if r is None or r.status_code != 200:
        return None
    for v in r.json():
        for f in v.get("files", []):
            if f["filename"].endswith(".mrpack"):
                return f["url"], f["filename"], v.get("version_number", "")
    return None


def project_from_hash(sha1):
    r = _get(f"{MODRINTH_API}/version_file/{sha1}")
    if r is None or r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("project_id"):
        return None
    return {
        "project_id": data.get("project_id"),
        "version_id": data.get("id"),
        "version_number": data.get("version_number", ""),
        "name": data.get("name", ""),
        "game_versions": data.get("game_versions", []),
        "loaders": data.get("loaders", []),
    }


_STRIP_PATTERNS = [
    r"-(?:fabric|forge|neoforge|quilt|mc|server|client)?[-_]?"
    r"(?:\d+\.\d+(?:\.\d+)?(?:\.\d+)?)(?:[-+].*)?$",
    r"-(?:fabric|forge|neoforge|quilt|mc|server|client)$",
    r"[-_]v?\d+(?:\.\d+){1,3}.*$",
]


def _slug_candidates(filename):
    stem = filename
    for ext in (".jar", ".zip"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    out = []
    seen = set()

    def _add(s):
        s = s.strip(" -_.")
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)

    _add(stem)
    for pat in _STRIP_PATTERNS:
        _add(_re.sub(pat, "", stem, flags=_re.I))
    if "-" in stem:
        _add(stem.split("-", 1)[0])
    return out


def project_id_from_filename(filename, kind_hint=None):
    """Best-effort lookup of a Modrinth project by jar filename.
    Returns a project id or None. Cached by filename."""
    if not filename:
        return None
    cache_key = filename.lower()
    cached = _FILENAME_CACHE.get(cache_key)
    if cached is not None:
        return cached or None

    for slug in _slug_candidates(filename):
        r = _get(f"{MODRINTH_API}/search",
                 params={"query": slug, "limit": 5})
        if r is None or r.status_code != 200:
            continue
        try:
            hits = r.json().get("hits", [])
        except Exception:
            continue
        target = slug.replace("-", " ").replace("_", " ").lower()
        for h in hits:
            title = (h.get("title") or "").lower()
            pid = h.get("project_id") or h.get("id")
            if not pid:
                continue
            slug_ok = (
                target == title
                or target in title
                or title in target
                or (h.get("slug") or "").lower() == target.replace(" ", "-")
            )
            if slug_ok:
                _FILENAME_CACHE[cache_key] = pid
                return pid
    _FILENAME_CACHE[cache_key] = ""
    return None


def fetch_project(project_id):
    r = _get(f"{MODRINTH_API}/project/{project_id}")
    if r is None or r.status_code != 200:
        return None
    try:
        d = r.json()
    except Exception:
        return None
    author = ""
    mr = _get(f"{MODRINTH_API}/project/{project_id}/members")
    if mr is not None and mr.status_code == 200:
        try:
            members = mr.json()
            if isinstance(members, list) and members:
                for m in members:
                    if m.get("role") in ("Owner", "Admin"):
                        author = (m.get("user") or {}).get("username", "")
                        break
                if not author:
                    author = (members[0].get("user") or {}).get(
                        "username", "")
        except Exception:
            pass
    return {
        "title": d.get("title", ""),
        "author": author,
        "icon_url": d.get("icon_url", ""),
        "description": d.get("description", ""),
        "downloads": d.get("downloads", 0),
    }


def _sha1_file(path, chunk=1 << 20):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def resolve_one(path, mc_version, kind, loader=None, want_latest=True):
    p = Path(path)
    out = {
        "project_id": None,
        "title": p.stem,
        "author": "",
        "version_number": "",
        "latest_version": "",
        "latest_filename": "",
        "latest_url": "",
        "status": "unchecked",
    }
    try:
        sha1 = _sha1_file(path)
    except Exception:
        out["status"] = "error"
        return out
    info = project_from_hash(sha1)
    if not info or not info.get("project_id"):
        pid = project_id_from_filename(p.name)
        if pid:
            info = {"project_id": pid, "version_number": "",
                    "name": p.stem}
        else:
            out["status"] = "not-on-modrinth"
            return out
    out["project_id"] = info["project_id"]
    out["version_number"] = info.get("version_number", "")
    if info.get("name"):
        out["title"] = info["name"]
    proj = fetch_project(info["project_id"])
    if proj:
        if proj.get("title"):
            out["title"] = proj["title"]
        if proj.get("author"):
            out["author"] = proj["author"]
    if want_latest:
        effective_loader = loader if kind == "mod" else None
        latest = latest_file(info["project_id"], mc_version, kind,
                             effective_loader)
        if latest:
            url, fname, ver = latest
            out["latest_version"] = ver
            out["latest_filename"] = fname
            out["latest_url"] = url
            if out["version_number"] == ver:
                out["status"] = "up-to-date"
            else:
                out["status"] = "update-available"
        else:
            out["status"] = "no-update-available"
    else:
        out["status"] = "checked"
    return out


def resolve_mods_parallel(paths, mc_version, kind, loader=None,
                          workers=3, progress=None):
    results = {}
    total = len(paths)
    if not total:
        return results

    def one(p):
        return p, resolve_one(p, mc_version, kind, loader)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(one, p) for p in paths]
        for fut in as_completed(futures):
            try:
                p, info = fut.result()
            except Exception:
                continue
            results[Path(p).name] = info
            done += 1
            if progress:
                try:
                    progress(done, total)
                except Exception:
                    pass
    return results
