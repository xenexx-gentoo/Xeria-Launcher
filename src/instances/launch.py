import hashlib
import json
import platform
import shlex
import subprocess
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from core.paths import MC_ROOT, IS_WIN, NO_WINDOW
from core import hardware
from core import translate
from core.java import best_java
from core.jvm import build_jvm_flags
from instances.env import build_launch_env
from integration import net as http


HW = hardware.get()


class LaunchMixin:
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
        from ui.helpers import s_btn_launch
        from core import theme
        if running:
            self._running_profile = profile
        else:
            self._running_profile = None

        same = (running and profile is not None
                and self.current_profile is not None
                and getattr(profile, "name", None)
                == getattr(self.current_profile, "name", None))

        if same:
            self.launch_btn.setText(translate.t("btn.stop"))
            self.launch_btn.setStyleSheet(
                f"QPushButton{{background:{theme.RED};"
                f"color:{theme.WHITE};border:none;"
                f"padding:8px 20px;font-weight:bold;"
                f"min-width:140px;"
                f"font-family:\"{theme.UI_FONT}\"}}"
                f"QPushButton:hover{{background:{theme.ACCENT2}}}")
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
                self, translate.t("warn.wait"),
                translate.t("console.no_instance"))
            return
        if not self.manifest:
            QMessageBox.warning(
                self, translate.t("warn.wait"),
                translate.t("console.wait_manifest"))
            return
        p = self.current_profile
        self._launching_profile = p
        self.console.log("info", translate.t(
            "console.starting", name=p.name, version=p.version))
        from core.worker import Worker
        w = Worker(self._do_launch, p)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection)
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection)
        w.done.connect(self._launch_done, Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _launch_done(self, proc):
        if proc:
            self._process = proc
            self._set_launch_state(True, self._launching_profile)
            self.console.log("ok", translate.t(
                "console.running_pid", pid=proc.pid))
            threading.Thread(target=self._stream_process, args=(proc,),
                             daemon=True).start()
        else:
            self.console.log("error", translate.t("console.launch_failed"))
            self._set_launch_state(False)

    def _stream_process(self, proc):
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.mc_log.emit(line)
            proc.wait()
            self.mc_log.emit(translate.t(
                "console.mc_exited", code=proc.returncode))
        except Exception as e:
            self.mc_log.emit(translate.t(
                "console.stream_error", err=e))
        finally:
            self._process = None
            self.mc_log.emit("__exit__")

    def stop_instance(self):
        p = self._process
        if not p or p.poll() is not None:
            self._set_launch_state(False)
            return
        self.console.log("warn", translate.t(
            "console.stopping_pid", pid=p.pid))
        try:
            if IS_WIN:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                    capture_output=True, creationflags=NO_WINDOW)
            else:
                p.terminate()
            try:
                p.wait(3000)
            except subprocess.TimeoutExpired:
                p.kill()
        except Exception as e:
            self.console.log("error", translate.t(
                "console.stop_failed", err=e))
        finally:
            self._process = None
            self._set_launch_state(False)

    def _do_launch(self, profile, log, progress, progress_end):
        from integration import loaders

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
            except Exception as e:
                log("warn", translate.t(
                    "console.token_refresh_failed", err=e))
                log("warn", translate.t("console.offline_fallback"))

        effective_version = loaders.install(
            profile.loader, profile.version,
            log=log, progress=progress, progress_end=progress_end)
        if not effective_version:
            log("warn", translate.t("console.loader_fallback"))
            effective_version = profile.version

        java_override = (profile.override_java_path
                         or self.settings.get("java_path", ""))
        java = best_java(profile.version, log, override=java_override)
        if not java:
            log("error", translate.t("console.no_java"))
            return None

        log("net", translate.t(
            "console.fetching_vjson", id=effective_version))
        vj = self._get_vjson(effective_version)
        if not vj:
            log("error", translate.t("console.vjson_failed"))
            return None

        jar_dir = MC_ROOT / "versions" / effective_version
        jar_dir.mkdir(parents=True, exist_ok=True)
        own_json = jar_dir / f"{effective_version}.json"
        if not own_json.exists():
            own_json.write_text(json.dumps(vj))
        vj = self._resolve_inheritance(effective_version, vj, log)
        vanilla_id = vj.get("inheritsFrom") or effective_version

        libs_dir = MC_ROOT / "libraries"
        cp = []
        vanilla_jar = (MC_ROOT / "versions" / vanilla_id
                       / f"{vanilla_id}.jar")
        if not vanilla_jar.exists():
            vvj = self._get_vjson(vanilla_id)
            if vvj and "downloads" in vvj:
                vanilla_jar.parent.mkdir(parents=True, exist_ok=True)
                self._dl(vvj["downloads"]["client"]["url"], vanilla_jar,
                         "client.jar", progress, progress_end)
        if vanilla_jar.exists():
            cp.append(str(vanilla_jar))

        if vanilla_id != effective_version:
            loader_jar = jar_dir / f"{effective_version}.jar"
            if not loader_jar.exists():
                if "downloads" in vj and "client" in vj.get("downloads", {}):
                    self._dl(vj["downloads"]["client"]["url"], loader_jar,
                             "loader.jar", progress, progress_end)
            if loader_jar.exists():
                cp.append(str(loader_jar))

        native_dirs = []
        libs = [x for x in vj.get("libraries", [])
                if self._rules_ok(x.get("rules"))]
        needed = []
        for lib in libs:
            url, rel = self._resolve_library(lib)
            if not url or not rel:
                continue
            p = libs_dir / rel
            if p.exists() and p.stat().st_size > 0:
                cp.append(str(p))
            else:
                needed.append((url, p))
        if needed:
            log("sys", translate.t(
                "console.libs_missing", n=len(needed)))
            done_count = [0]
            lock = threading.Lock()
            workers = HW.library_workers

            def fetch(item):
                url, path = item
                ok = self._dl_silent(url, path)
                with lock:
                    done_count[0] += 1
                    progress("libraries", done_count[0],
                             len(needed), "", "")
                return ok, path

            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(fetch, it) for it in needed]
                for f in as_completed(futures):
                    ok, path = f.result()
                    if ok:
                        cp.append(str(path))
            progress_end()

        for lib in libs:
            nat = self._native(lib)
            if nat:
                out = (MC_ROOT / "versions" / effective_version
                       / "natives" / lib["name"].replace(":", "_"))
                out.mkdir(parents=True, exist_ok=True)
                try:
                    with zipfile.ZipFile(nat) as z:
                        z.extractall(out)
                    native_dirs.append(str(out))
                except Exception:
                    pass

        self._download_assets(vj, progress, progress_end, log)
        assets = MC_ROOT / "assets"
        idx = vj.get("assetIndex")

        sep = ";" if IS_WIN else ":"
        jvm_flags = build_jvm_flags(profile, self.settings,
                                    native_dirs, sep)
        cmd = [java] + jvm_flags + [
            "-cp", sep.join(cp),
            vj.get("mainClass", "net.minecraft.client.main.Main"),
            "--username", self._get_username(),
            "--version", effective_version,
            "--gameDir", str(profile.dir),
            "--assetsDir", str(assets),
            "--assetIndex", idx["id"] if idx else "legacy",
            "--uuid", self._uuid(self._get_username()),
            "--accessToken", acc.mc_access if acc.signed_in else "0",
            "--userType", "msa" if acc.signed_in else "legacy",
            "--versionType", "release"]

        wrapper = (profile.override_wrapper
                   or self.settings.get("wrapper_command", "").strip())
        if wrapper:
            try:
                cmd = shlex.split(wrapper) + cmd
            except Exception as e:
                log("error", translate.t(
                    "console.invalid_wrapper", err=e))

        env = build_launch_env(profile, self.settings)
        log("sys", translate.t("console.spawning", ram=profile.ram))
        try:
            proc = subprocess.Popen(cmd, cwd=str(profile.dir),
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    text=True, bufsize=1,
                                    creationflags=NO_WINDOW, env=env)
        except FileNotFoundError:
            log("error", translate.t(
                "console.java_not_found", path=java))
            return None
        except Exception as e:
            log("error", translate.t(
                "console.spawn_failed", err=e))
            return None
        time.sleep(0.6)
        if proc.poll() is not None:
            out, _ = proc.communicate(timeout=2)
            for line in (out or "").splitlines()[-40:]:
                log("error", line)
            log("error", translate.t(
                "console.exited_immediately", code=proc.returncode))
            return None
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
        except Exception as e:
            log("error", f"asset index parse failed: {e}")
            return
        objects = index.get("objects", {})
        to_get = []
        for name, meta in objects.items():
            h = meta["hash"]
            sub = h[:2]
            dest = assets_root / "objects" / sub / h
            if not dest.exists():
                to_get.append((h, dest))
        if not to_get:
            return
        log("sys", translate.t(
            "console.assets_missing", n=len(to_get)))
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
                        for chunk in r.iter_bytes(65536):
                            f.write(chunk)
                    tmp.replace(dest)
                ok = True
            except Exception:
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
        log("ok", translate.t(
            "console.assets_done",
            n=ok_count, total=len(to_get)))

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
        base = (lib.get("url")
                or "https://libraries.minecraft.net/").rstrip("/")
        return f"{base}/{rel}", rel

    def _dl(self, url, dest, label, progress, progress_end):
        dest = Path(dest)
        if dest.exists() and dest.stat().st_size > 0:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with http.stream("GET", url) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                done = 0
                b0 = 0
                tl = time.time()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(65536):
                        f.write(chunk)
                        done += len(chunk)
                        now = time.time()
                        if now - tl >= 0.15 or done == total:
                            spd = (done - b0) / (now - tl) if now > tl else 0
                            progress(label, done, total, "",
                                     self._speed(spd))
                            tl = now
                            b0 = done
                tmp.replace(dest)
                progress_end()
        except Exception as e:
            progress_end()
            self.console.log("error", f"dl failed {dest.name}: {e}")

    def _dl_silent(self, url, dest):
        dest = Path(dest)
        if dest.exists() and dest.stat().st_size > 0:
            return True
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with http.stream("GET", url) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(65536):
                        f.write(chunk)
                tmp.replace(dest)
            return True
        except Exception:
            return False

    @staticmethod
    def _speed(bps):
        if bps > 1024 * 1024:
            return f"{bps / 1024 / 1024:.1f} MB/s"
        if bps > 1024:
            return f"{bps / 1024:.0f} KB/s"
        return f"{bps:.0f} B/s"

    def _get_vjson(self, vid):
        try:
            for v in self.manifest["versions"]:
                if v["id"] == vid:
                    return http.get(v["url"]).json()
        except Exception:
            pass
        path = MC_ROOT / "versions" / vid / f"{vid}.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                return None
        return None

    def _rules_ok(self, rules):
        if not rules:
            return True
        o = {"windows": "windows", "darwin": "osx",
             "linux": "linux"}.get(platform.system().lower(), "linux")
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
        keys = {"windows": ["natives-windows", "natives-windows-64"],
                "darwin": ["natives-macos", "natives-osx"],
                "linux": ["natives-linux"]}.get(s, [])
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
                            for ch in r.iter_bytes(16384):
                                f.write(ch)
                    return p
                except Exception:
                    return None
        return None
