import contextlib
import hashlib
import json
import os
import platform
import re
import shlex
import signal
import subprocess
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from core import hardware, translate
from core.java import best_java
from core.jvm import build_jvm_flags
from core.paths import (
    IS_WIN,
    MANIFEST_URL,
    MC_ROOT,
    NO_WINDOW,
)
from core.worker import Worker
from instances.env import build_launch_env
from integration import loaders
from integration import net as http
from ui.helpers import s_btn_launch, s_btn_stop

HW = hardware.get()


def _detached_flags():
    if IS_WIN:
        return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    return 0


class LaunchOps:
    """Mixin: every launch-related action for MainWindow."""

    def fetch_manifest(self):
        def task(log, progress, progress_end):
            log("net", f"GET {MANIFEST_URL}")
            t0 = time.time()
            r = http.get(MANIFEST_URL)
            r.raise_for_status()
            d = r.json()
            rel = [v for v in d["versions"] if v["type"] == "release"]
            return d, rel, time.time() - t0

        w = Worker(task)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.done.connect(self._manifest_done, Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _manifest_done(self, r):
        if not r:
            return
        d, rel, secs = r
        self.manifest, self.releases = d, rel
        self.console.log(
            "ok", translate.t("console.manifest_loaded", n=len(rel), secs=f"{secs:.2f}")
        )

    def _run_auto_check(self):
        with contextlib.suppress(Exception):
            self.settings.set("auto_check_last_run", time.time())
            self.settings.save()
        profiles = list(self.profiles)
        if not profiles:
            self._schedule_auto_check()
            return
        self.console.log("sys", translate.t("console.auto_check"))
        for prof in profiles:
            try:
                mods_dir = prof.dir / "mods"
                if not mods_dir.exists():
                    continue
                jars = [
                    f
                    for f in mods_dir.iterdir()
                    if f.is_file() and f.suffix.lower() == ".jar"
                ]
                if not jars:
                    continue
                mv = prof.version
                ld = (prof.loader or "vanilla").lower()
                paths = [str(j) for j in jars]

                def task(
                    log,
                    progress,
                    progress_end,
                    paths_=paths,
                    mv_=mv,
                    ld_=ld,
                    prof_=prof,
                ):
                    from integration import modrinth

                    result = modrinth.resolve_mods_parallel(
                        paths_, mv_, "mod", ld_, workers=3
                    )
                    try:
                        meta = getattr(prof_, "mods_meta", {}) or {}
                        meta.update(result)
                        prof_.mods_meta = meta
                        prof_.save()
                    except Exception:  # noqa: BLE001, S110
                        pass
                    return prof_, result

                w = Worker(task)
                w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
                w.done.connect(
                    self._on_auto_check_done, Qt.ConnectionType.QueuedConnection
                )
                self._track(w)
                w.start()
            except Exception as e:  # noqa: BLE001
                self.console.log("warn", str(e))
        self._schedule_auto_check()

    def _on_auto_check_done(self, payload):
        if not payload:
            return
        prof, result = payload
        hits = sum(1 for r in (result or {}).values() if r.get("project_id"))
        total = len(result or {})
        self.console.log(
            "ok",
            translate.t(
                "console.auto_check_done", hits=hits, total=total, name=prof.name
            ),
        )

    def _get_username(self):
        acc = self.settings.active_online_account()
        if acc.signed_in:
            return acc.name
        return self.settings.active_offline_name()

    def _uuid(self, u):
        acc = self.settings.active_online_account()
        if acc.signed_in:
            return acc.uuid
        active = self.settings.get_active_account()
        if active and active.get("type") == "offline":
            stored = (active.get("data") or {}).get("uuid")
            if stored:
                return stored
        h = hashlib.md5(f"OfflinePlayer:{u}".encode()).hexdigest()
        return f"{h[:8]}-{h[8:12]}-3{h[13:16]}-{h[16:20]}-{h[20:32]}"

    def launch_toggle(self):
        if self._process and self._process.poll() is None:
            self.stop_instance()
        else:
            self.launch()

    def _set_launch_state(self, running, profile=None):
        if running:
            self._running_profile = profile
        else:
            self._running_profile = None

        same = (
            running
            and profile is not None
            and self.current_profile is not None
            and getattr(profile, "name", None)
            == getattr(self.current_profile, "name", None)
        )

        if same:
            self.launch_btn.setText(translate.t("btn.stop"))
            self.launch_btn.setStyleSheet(s_btn_stop())
        else:
            self.launch_btn.setText(translate.t("btn.launch"))
            self.launch_btn.setStyleSheet(s_btn_launch())
        self.launch_btn.setMinimumWidth(140)

    def launch(self):
        if self._process and self._process.poll() is not None:
            self._process = None
        if self._process:
            return
        if not self.current_profile:
            QMessageBox.information(
                self, translate.t("warn.wait"), translate.t("console.no_instance")
            )
            return
        if not self.manifest:
            QMessageBox.warning(
                self, translate.t("warn.wait"), translate.t("console.wait_manifest")
            )
            return
        p = self.current_profile
        self._launching_profile = p
        self.console.log(
            "info", translate.t("console.starting", name=p.name, version=p.version)
        )
        w = Worker(self._do_launch, p)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection,
        )
        w.done.connect(self._launch_done, Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _launch_done(self, proc):
        if proc:
            self._process = proc
            self._set_launch_state(True, self._launching_profile)
            self.console.log("ok", translate.t("console.running_pid", pid=proc.pid))
            threading.Thread(
                target=self._watch_process, args=(proc,), daemon=True
            ).start()
            threading.Thread(target=self._tail_log, daemon=True).start()
        else:
            self.console.log("error", translate.t("console.launch_failed"))
            self._set_launch_state(False)

    def _tail_log(self):
        profile = self._running_profile or self.current_profile
        candidates = []
        if profile is not None:
            candidates.append(profile.dir / "logs" / "latest.log")
            ext = getattr(profile, "_external_dir", None)
            if ext is not None:
                candidates.append(ext / "logs" / "latest.log")
        candidates.append(MC_ROOT / "logs" / "latest.log")
        seen_lines = 0
        timeout = time.time() + 30

        while self._process and self._process.poll() is None:
            log_file = next((p for p in candidates if p.exists()), None)
            if log_file is not None:
                try:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                        if len(lines) > seen_lines:
                            for line in lines[seen_lines:]:
                                clean = line.strip()
                                if clean:
                                    self.mc_log.emit(clean)
                            seen_lines = len(lines)
                            timeout = time.time() + 30
                except Exception:  # noqa: BLE001, S110
                    pass

            if time.time() > timeout:
                break
            time.sleep(0.5)

    def _watch_process(self, proc):
        with contextlib.suppress(Exception):
            proc.wait()
        with contextlib.suppress(Exception):
            self.mc_log.emit(translate.t("console.mc_exited", code=proc.returncode))
        self._process = None
        with contextlib.suppress(Exception):
            self.mc_log.emit("__exit__")

    def stop_instance(self):
        p = self._process
        if not p or p.poll() is not None:
            self._set_launch_state(False)
            return
        self.console.log("warn", translate.t("console.stopping_pid", pid=p.pid))
        try:
            if IS_WIN:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                    capture_output=True,
                    creationflags=NO_WINDOW,
                    check=False,
                )
            else:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:  # noqa: BLE001
                    p.kill()
        except Exception as e:  # noqa: BLE001
            self.console.log("error", translate.t("console.stop_failed", err=e))
        finally:
            self._process = None
            self._set_launch_state(False)

    def _manifest_version(self, version_id):
        if not self.manifest:
            return None
        for v in self.manifest.get("versions", []):
            if v.get("id") == version_id:
                return v
        return None

    def _ensure_vanilla_json(self, version, log):
        path = MC_ROOT / "versions" / version / f"{version}.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:  # noqa: BLE001, S110
                pass

        entry = self._manifest_version(version)
        if not entry:
            log(
                "error",
                f"Mojang's manifest does not contain version "
                f"'{version}'. Refresh the manifest or pick a "
                f"version that exists.",
            )
            return None

        log("sys", f"Downloading vanilla JSON for {version}...")
        try:
            r = http.get(entry["url"])
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
            return r.json()
        except Exception as e:  # noqa: BLE001
            log("error", f"Failed to download {version}.json: {e}")
            return None

    def _load_external_version_json(self, profile, log):
        ext = getattr(profile, "_external_dir", None)
        candidates = []
        if ext is not None:
            candidates.append(ext / f"{ext.name}.json")
        candidates.append(MC_ROOT / "versions" / profile.name / f"{profile.name}.json")
        if profile.version:
            candidates.append(
                MC_ROOT / "versions" / profile.version / f"{profile.version}.json"
            )
        for path in candidates:
            if path.exists():
                try:
                    return json.loads(path.read_text())
                except Exception as e:  # noqa: BLE001
                    log("warn", f"failed to parse {path}: {e}")
                    continue
        log(
            "error",
            f"Could not find an on-disk version JSON for "
            f"'{profile.name}'. Looked in: "
            f"{[str(p) for p in candidates]}",
        )
        return None

    def _ensure_vanilla_jar(
        self, version, vjson, log, progress=None, progress_end=None
    ):
        jar_path = MC_ROOT / "versions" / version / f"{version}.jar"
        if jar_path.exists() and jar_path.stat().st_size > 1000000:
            self._ensure_client_mappings(version, vjson, log)
            return jar_path

        log("sys", f"Downloading vanilla client.jar for {version}...")
        try:
            if "downloads" in vjson and "client" in vjson["downloads"]:
                url = vjson["downloads"]["client"]["url"]
                jar_path.parent.mkdir(parents=True, exist_ok=True)
                with http.stream("GET", url) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("content-length", 0))
                    done = 0
                    with open(jar_path, "wb") as f:
                        for chunk in r.iter_bytes(65536):
                            f.write(chunk)
                            done += len(chunk)
                            if progress and total:
                                progress("client.jar", done, total, "", "")
                if progress_end:
                    progress_end()
                self._ensure_client_mappings(version, vjson, log)
                return jar_path
        except Exception as e:  # noqa: BLE001
            log("error", f"Failed to download vanilla jar: {e}")
            return None
        return None

    def _ensure_client_mappings(self, version, vjson, log):
        downloads = (vjson or {}).get("downloads", {}) or {}
        entry = downloads.get("client_mappings")
        if not entry or not entry.get("url"):
            return
        mp = MC_ROOT / "versions" / version / f"{version}-client-mappings.txt"
        if mp.exists() and mp.stat().st_size > 0:
            return
        try:
            mp.parent.mkdir(parents=True, exist_ok=True)
            with http.stream("GET", entry["url"]) as r:
                r.raise_for_status()
                tmp = mp.with_suffix(".part")
                with open(tmp, "wb") as f:
                    f.writelines(r.iter_bytes(65536))
                tmp.replace(mp)
            log("sys", f"Downloaded client mappings for {version}")
        except Exception as e:  # noqa: BLE001
            log("warn", f"client mappings download failed: {e}")

    def _version_tokens(self, s):
        if not s:
            return []
        out = []
        for tok in re.split(r"[-_ /:\\]+", str(s)):
            tok = tok.strip()
            if re.match(r"^\d+(?:\.\d+)+$", tok):
                out.append(tok)
        return out

    def _collect_labymod_candidates(self, profile, laby, ext_dir):
        raw = []

        if laby:
            for k in ("inheritsFrom", "clientVersion", "id"):
                v = laby.get(k)
                if isinstance(v, str) and v.strip():
                    raw.append(v.strip())

        if ext_dir is not None:
            raw.append(ext_dir.name)
        raw.append(profile.name or "")
        raw.append(profile.version or "")

        seen = set()
        ordered = []

        def push(v):
            if v and v not in seen:
                seen.add(v)
                ordered.append(v)

        for r in raw:
            if not r:
                continue
            push(r)
            for tok in self._version_tokens(r):
                push(tok)

        return ordered

    def _resolve_labymod_base(self, profile, log):
        ext = getattr(profile, "_external_dir", None)
        if ext is not None:
            json_path = ext / f"{ext.name}.json"
        else:
            json_path = MC_ROOT / "versions" / profile.name / f"{profile.name}.json"

        laby = None
        if json_path.exists():
            try:
                laby = json.loads(json_path.read_text())
            except Exception as e:  # noqa: BLE001
                log("error", f"failed to read {json_path}: {e}")
                return None

        candidates = self._collect_labymod_candidates(profile, laby, ext)
        known = {v["id"] for v in (self.manifest or {}).get("versions", [])}

        for c in candidates:
            if c in known:
                if laby is not None and laby.get("inheritsFrom") != c:
                    with contextlib.suppress(Exception):
                        laby["inheritsFrom"] = c
                        json_path.write_text(json.dumps(laby, indent=2))
                        log("ok", f"Patched {json_path.name}: inheritsFrom = {c}")
                return c

        log(
            "error",
            f"LabyMod profile '{profile.name}' could not resolve a "
            f"base Minecraft version. Tried: {candidates}. "
            f"None is in Mojang's manifest.",
        )
        return None

    def _do_launch(self, profile, log, progress, progress_end):
        acc = self.settings.active_online_account()
        if acc.signed_in:
            try:
                acc.ensure_valid()
                accs = self.settings.get_accounts()
                active = self.settings.get("active_account", 0)
                if 0 <= active < len(accs):
                    accs[active]["data"] = acc.to_dict()
                    self.settings.set_accounts(accs)
                log("ok", translate.t("console.account_ok", name=acc.name))
            except Exception as e:  # noqa: BLE001
                log("warn", translate.t("console.token_refresh_failed", err=e))
                log("warn", translate.t("console.offline_fallback"))

        is_labymod = "labymod" in profile.name.lower()

        if is_labymod:
            vanilla_id = self._resolve_labymod_base(profile, log)
            if not vanilla_id:
                return None
            effective_version = profile.name

            vj = self._load_external_version_json(profile, log)
            if not vj:
                log("error", f"Failed to load LabyMod JSON {effective_version}")
                return None

            vanilla_vjson = self._ensure_vanilla_json(vanilla_id, log)
            if not vanilla_vjson:
                log("error", f"Failed to load vanilla JSON {vanilla_id}")
                return None

            jar_path = self._ensure_vanilla_jar(
                vanilla_id, vanilla_vjson, log, progress, progress_end
            )
            if not jar_path:
                log("error", "Failed to obtain vanilla client.jar")
                return None

            log("sys", "Building LabyMod classpath (filtering Quilt/Fabric)...")
            cp = [str(jar_path)]

            def add_jars(base_dir):
                if not base_dir.exists():
                    return
                for jar in base_dir.rglob("*.jar"):
                    path_str = str(jar).lower()
                    if "quilt" in path_str or "fabric" in path_str:
                        continue
                    cp.append(str(jar))

            add_jars(MC_ROOT / "libraries")
            add_jars(MC_ROOT / "labymod-neo" / "libraries")
            ext = getattr(profile, "_external_dir", None)
            if ext is not None:
                add_jars(ext / "libraries")
                ext_jar = ext / f"{ext.name}.jar"
                if ext_jar.exists() and ext_jar.stat().st_size > 1000:
                    cp.append(str(ext_jar))

            patches_dir = MC_ROOT / "labymod-neo" / "patches"
            patches_dir.mkdir(parents=True, exist_ok=True)
            patch_file = patches_dir / "net.minecraft.json"
            release_time = vanilla_vjson.get("releaseTime", "2024-01-01T00:00:00+00:00")
            patch_data = {"id": vanilla_id, "releaseTime": release_time}
            with contextlib.suppress(Exception):
                patch_file.write_text(json.dumps(patch_data, indent=2))
                log("sys", f"Generated LabyMod patch (id={vanilla_id})")

            main_class = "net.minecraft.launchwrapper.Launch"
            tweak_class = (
                "net.labymod.core.loader.vanilla."
                "launchwrapper.LabyModLaunchWrapperTweaker"
            )
        else:
            vanilla_id = profile.version
            effective_version = profile.version

            is_external = getattr(profile, "_external_dir", None) is not None
            if is_external:
                effective_version = profile.name
                vanilla_id = profile.version
            else:
                effective_version = loaders.install(
                    profile.loader,
                    profile.version,
                    log=log,
                    progress=progress,
                    progress_end=progress_end,
                    force_version=getattr(profile, "loader_version", "") or "",
                )
                if not effective_version:
                    log("warn", translate.t("console.loader_fallback"))
                    effective_version = profile.version
                vanilla_id = profile.version

            vj = self._ensure_vanilla_json(effective_version, log)
            if not vj:
                log("error", f"Failed to load JSON for {effective_version}")
                return None

            vanilla_vjson = self._ensure_vanilla_json(vanilla_id, log)
            if not vanilla_vjson:
                log("error", f"Failed to load vanilla JSON for {vanilla_id}")
                return None

            jar_path = self._ensure_vanilla_jar(
                vanilla_id, vanilla_vjson, log, progress, progress_end
            )
            if not jar_path:
                log("error", "Failed to obtain vanilla client.jar")
                return None

            vj = self._resolve_inheritance(effective_version, vj, log)

            libs_dir = MC_ROOT / "libraries"
            cp = [str(jar_path)]

            libs = [
                x for x in vj.get("libraries", []) if self._rules_ok(x.get("rules"))
            ]
            for lib in libs:
                url, rel = self._resolve_library(lib)
                if not url or not rel:
                    continue
                p = libs_dir / rel
                if p.exists() and p.stat().st_size > 0 or self._dl_silent(url, p):
                    cp.append(str(p))

            main_class = vj.get("mainClass", "net.minecraft.client.main.Main")
            tweak_class = None

        java_override = profile.override_java_path or self.settings.get("java_path", "")
        if is_labymod and not java_override:
            log("java", "LabyMod requires Java 25 - installing")
            java = best_java(vanilla_id, log, override="", required_major=25)
        else:
            java = best_java(vanilla_id, log, override=java_override)
        if not java:
            log("error", translate.t("console.no_java"))
            return None

        native_dirs = []
        for lib in vj.get("libraries", []):
            if not self._rules_ok(lib.get("rules")):
                continue
            nat = self._native(lib)
            if nat:
                out = (
                    MC_ROOT
                    / "versions"
                    / vanilla_id
                    / "natives"
                    / lib["name"].replace(":", "_")
                )
                out.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(Exception):
                    with zipfile.ZipFile(nat) as z:
                        z.extractall(out)
                    native_dirs.append(str(out))

        self._download_assets(vanilla_vjson, progress, progress_end, log)
        assets = MC_ROOT / "assets"
        idx = vanilla_vjson.get("assetIndex")

        sep = ";" if IS_WIN else ":"
        jvm_flags = build_jvm_flags(profile, self.settings, native_dirs, sep)

        if is_labymod:
            jvm_flags.extend(
                [
                    f"-Dnet.labymod.running-version={vanilla_id}",
                    "-Dnet.labymod.launcher=multimc",
                    f"-Dnet.labymod.minecraft.version={vanilla_id}",
                ]
            )

        if getattr(profile, "_external_dir", None) is not None:
            game_dir = profile._external_dir
        else:
            game_dir = profile.dir
        game_dir.mkdir(parents=True, exist_ok=True)

        cmd = (
            [java]
            + jvm_flags
            + [
                "-cp",
                sep.join(cp),
                main_class,
                "--username",
                self._get_username(),
                "--version",
                vanilla_id,
                "--gameDir",
                str(game_dir),
                "--assetsDir",
                str(assets),
                "--assetIndex",
                idx["id"] if idx else "legacy",
                "--uuid",
                self._uuid(self._get_username()),
                "--accessToken",
                acc.mc_access if acc.signed_in else "0",
                "--userType",
                "msa" if acc.signed_in else "legacy",
                "--versionType",
                "release",
            ]
        )

        if tweak_class:
            cmd.extend(["--tweakClass", tweak_class])

        wrapper = (
            profile.override_wrapper or self.settings.get("wrapper_command", "").strip()
        )
        if wrapper:
            try:
                cmd = shlex.split(wrapper) + cmd
            except Exception as e:  # noqa: BLE001
                log("error", translate.t("console.invalid_wrapper", err=e))

        log_dir = game_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "latest.log"
        try:
            log_fp = open(  # noqa: SIM115
                log_file,
                "w",
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:  # noqa: BLE001
            log("error", f"could not open log: {e}")
            return None

        env = build_launch_env(profile, self.settings)
        if not IS_WIN and is_labymod:
            st = os.environ.get("XDG_SESSION_TYPE", "").lower()
            wl = bool(os.environ.get("WAYLAND_DISPLAY")) or st == "wayland"
            if wl:
                env["SDL_VIDEODRIVER"] = "x11"
                env["_JAVA_AWT_WM_NONREPARENTING"] = "1"
                log("sys", "Wayland detected. Forcing SDL to X11.")

        log("sys", translate.t("console.spawning", ram=profile.ram))
        popen_kwargs = {
            "cwd": str(game_dir),
            "stdin": subprocess.DEVNULL,
            "stdout": log_fp,
            "stderr": subprocess.STDOUT,
            "env": env,
            "close_fds": True,
        }
        if IS_WIN:
            popen_kwargs["creationflags"] = _detached_flags()
        else:
            popen_kwargs["start_new_session"] = True

        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
        except FileNotFoundError:
            log_fp.close()
            log("error", translate.t("console.java_not_found", path=java))
            return None
        except Exception as e:  # noqa: BLE001
            log_fp.close()
            log("error", translate.t("console.spawn_failed", err=e))
            return None

        time.sleep(0.6)
        if proc.poll() is not None:
            log_fp.close()
            try:
                tail = log_file.read_text(encoding="utf-8", errors="replace")
                for line in tail.splitlines()[-40:]:
                    if line.strip():
                        log("error", line)
            except Exception:  # noqa: BLE001, S110
                pass
            log(
                "error", translate.t("console.exited_immediately", code=proc.returncode)
            )
            return None

        log_fp.close()
        log("ok", translate.t("console.game_detached", path=log_file))
        return proc

    def _download_assets(self, vjson, progress, progress_end, log):
        idx = vjson.get("assetIndex")
        if not idx:
            return
        assets_root = MC_ROOT / "assets"
        idx_path = assets_root / "indexes" / f"{idx['id']}.json"
        if not idx_path.exists():
            idx_path.parent.mkdir(parents=True, exist_ok=True)
            r = http.get(idx["url"])
            r.raise_for_status()
            idx_path.write_bytes(r.content)
        try:
            index = json.loads(idx_path.read_text())
        except Exception as e:  # noqa: BLE001
            log("error", f"asset index parse failed: {e}")
            return
        objects = index.get("objects", {})
        to_get = []
        for meta in objects.values():
            h = meta["hash"]
            sub = h[:2]
            dest = assets_root / "objects" / sub / h
            if not dest.exists():
                to_get.append((h, dest))
        if not to_get:
            return
        log("sys", translate.t("console.assets_missing", n=len(to_get)))
        lock = threading.Lock()
        done = [0]
        workers = HW.asset_workers

        def fetch(item):
            h, dest = item
            url = f"https://resources.download.minecraft.net/{h[:2]}/{h}"
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with http.stream("GET", url) as r:
                    r.raise_for_status()
                    tmp = dest.with_suffix(".part")
                    with open(tmp, "wb") as f:
                        f.writelines(r.iter_bytes(65536))
                    tmp.replace(dest)
                ok = True
            except Exception:  # noqa: BLE001
                ok = False
            with lock:
                done[0] += 1
                if done[0] % 25 == 0 or done[0] == len(to_get):
                    progress("assets", done[0], len(to_get), "", "")
            return ok

        ok_count = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for ok in ex.map(fetch, to_get):
                if ok:
                    ok_count += 1
        progress_end()
        log("ok", translate.t("console.assets_done", n=ok_count, total=len(to_get)))

    def _resolve_inheritance(self, vid, vj, log):
        parent_id = vj.get("inheritsFrom")
        if not parent_id:
            return vj
        log("sys", f"{vid} inherits from {parent_id}")
        parent = self._get_vjson(parent_id)
        if not parent:
            log("error", f"could not load parent {parent_id}")
            return vj
        merged_libs = list(parent.get("libraries", []))
        merged_libs.extend(vj.get("libraries", []))
        merged = dict(parent)
        merged.update(vj)
        merged["libraries"] = merged_libs
        for k in ("downloads", "assetIndex", "assets", "javaVersion"):
            if k not in merged and k in parent:
                merged[k] = parent[k]
        return merged

    def _resolve_library(self, lib):
        art = lib.get("downloads", {}).get("artifact")
        if art:
            return art["url"], art["path"]
        name = lib.get("name")
        if not name:
            return None, None
        parts = name.split(":")
        if len(parts) < 3:
            return None, None
        group, artifact, version = parts[0], parts[1], parts[2]
        classifier = parts[3] if len(parts) > 3 else None
        group_path = group.replace(".", "/")
        fname = f"{artifact}-{version}"
        if classifier:
            fname += f"-{classifier}"
        fname += ".jar"
        rel = f"{group_path}/{artifact}/{version}/{fname}"
        base = (lib.get("url") or "https://libraries.minecraft.net/").rstrip("/")
        return f"{base}/{rel}", rel

    def _dl_silent(self, url, dest):
        from pathlib import Path

        dest = Path(dest)
        if dest.exists() and dest.stat().st_size > 0:
            return True
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with http.stream("GET", url) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as f:
                    f.writelines(r.iter_bytes(65536))
                tmp.replace(dest)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _get_vjson(self, vid):
        entry = self._manifest_version(vid)
        if entry:
            with contextlib.suppress(Exception):
                return http.get(entry["url"]).json()
        path = MC_ROOT / "versions" / vid / f"{vid}.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:  # noqa: BLE001
                return None
        return None

    def _rules_ok(self, rules):
        if not rules:
            return True
        o = {"windows": "windows", "darwin": "osx", "linux": "linux"}.get(
            platform.system().lower(), "linux"
        )
        a = False
        for r in rules:
            ro = r.get("os", {}).get("name")
            if ro is None or ro == o:
                a = r.get("action") == "allow"
        return a

    def _native(self, lib):
        cl = lib.get("downloads", {}).get("classifiers", {})
        if not cl:
            return None
        s = platform.system().lower()
        keys = {
            "windows": ["natives-windows", "natives-windows-64"],
            "darwin": ["natives-macos", "natives-osx"],
            "linux": ["natives-linux"],
        }.get(s, [])
        for k in keys:
            if k in cl:
                art = cl[k]
                p = MC_ROOT / "libraries" / art["path"]
                if p.exists():
                    return p
                try:
                    with http.stream("GET", art["url"]) as r:
                        r.raise_for_status()
                        p.parent.mkdir(parents=True, exist_ok=True)
                        with open(p, "wb") as f:
                            f.writelines(r.iter_bytes(16384))
                    return p
                except Exception:  # noqa: BLE001
                    return None
        return None
