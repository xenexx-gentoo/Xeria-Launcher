import contextlib
import json
import os
import platform
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QListWidgetItem,
    QMenu,
    QMessageBox,
)

from browse.modpacks import ModpackSearchDialog
from core import theme, translate
from core.java import best_java
from core.paths import (
    IS_MAC,
    IS_WIN,
    MANIFEST_URL,
    MC_ROOT,
    PROFILES_DIR,
    XERIA_ROOT,
)
from core.worker import Worker
from instances import modpack
from instances.profile import Profile
from integration import net as http
from ui.dialogs import ChooseInstallDialog, ProfileDialog
from ui.helpers import s_menu
from ui.loader_icons import fetch_loader_icon, loader_icon_sync


class ProfileOps:
    """Mixin: every profile-related action for MainWindow."""

    def load_profiles(self):
        versions_dir = MC_ROOT / "versions"

        if versions_dir.exists():
            installed_labymods = set()
            for d in versions_dir.iterdir():
                if d.is_dir() and "labymod" in d.name.lower():
                    parts = d.name.split("-")
                    if len(parts) >= 3:
                        installed_labymods.add(parts[-2])

            for v_base in installed_labymods:
                vanilla_json = PROFILES_DIR / f"{v_base}.json"
                if vanilla_json.exists():
                    with contextlib.suppress(Exception):
                        vanilla_json.unlink()

                for f in PROFILES_DIR.glob("LabyMod*.json"):
                    with contextlib.suppress(Exception):
                        f.unlink()

        self.plist.blockSignals(True)
        self.plist.clear()
        self.plist.setSpacing(self.ROW_GAP)

        self.plist.setStyleSheet(
            f"QListWidget{{background:transparent;color:{theme.FG};"
            f"padding:0;border:none;}}"
            f"QListWidget::item{{padding:0px;margin:0px;border:none;}}"
        )

        self._row_map = []
        self._row_widgets = {}

        self.profiles = Profile.load_all()
        existing_names = {p.name for p in self.profiles}

        parents = set()
        if versions_dir.exists():
            for v_dir in versions_dir.iterdir():
                if not v_dir.is_dir():
                    continue
                jp = v_dir / f"{v_dir.name}.json"
                if not jp.exists():
                    continue
                try:
                    with open(jp, "r", encoding="utf-8") as f:
                        d = json.load(f)
                except Exception:  # noqa: BLE001, S112
                    continue
                inh = d.get("inheritsFrom")
                if inh:
                    parents.add(inh)

        if versions_dir.exists():
            installed_labymods = set()
            for d in versions_dir.iterdir():
                if d.is_dir() and "labymod" in d.name.lower():
                    parts = d.name.split("-")
                    if len(parts) >= 3:
                        installed_labymods.add(parts[-2])

            for v_dir in versions_dir.iterdir():
                if not v_dir.is_dir():
                    continue

                name_lower = v_dir.name.lower()

                if (
                    "fabric" in name_lower
                    or "quilt" in name_lower
                    or "forge" in name_lower
                ):
                    continue

                if v_dir.name in parents:
                    continue

                if v_dir.name in installed_labymods and "labymod" not in name_lower:
                    continue

                if v_dir.name in existing_names:
                    continue

                json_path = v_dir / f"{v_dir.name}.json"
                if not json_path.exists():
                    continue

                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        v_data = json.load(f)
                except Exception:  # noqa: BLE001, S112
                    continue

                p = Profile(v_dir.name)
                p.version = v_data.get("inheritsFrom", v_dir.name)
                p.loader = "vanilla"
                p.ram = "4"
                p._external_dir = v_dir

                if "labymod" in name_lower:
                    p.name = "LabyMod"
                    p.version = v_data.get("inheritsFrom", v_dir.name)

                self.profiles.append(p)

        from ui.main_window import _InstanceRow

        for p in self.profiles:
            it = QListWidgetItem()
            it.setSizeHint(QSize(0, self.ROW_HEIGHT))

            loader = (p.loader or "vanilla").lower()
            icon = loader_icon_sync(loader)
            if not icon:
                icon = QIcon.fromTheme("applications-games")

            folder_name = p._external_dir.name if p._external_dir else p.version
            row = _InstanceRow(p.name, p.version, folder_name, icon)

            self.plist.addItem(it)
            self.plist.setItemWidget(it, row)
            self._row_map.append(p)
            self._row_widgets[p.name] = row

        self.plist.blockSignals(False)

        for p in self.profiles:
            loader = (p.loader or "vanilla").lower()
            if loader_icon_sync(loader) is None:
                fetch_loader_icon(
                    loader, lambda ic, name=loader: self._apply_loader_icon(name, ic)
                )

        if self.profiles:
            self.plist.setCurrentRow(0)
        else:
            self.current_profile = None
            self._update_card()

    def _apply_loader_icon(self, loader_name, icon):
        for p in self.profiles:
            if (p.loader or "vanilla").lower() == loader_name:
                row = self._row_widgets.get(p.name)
                if row:
                    row.set_icon(icon)

    def _on_profile_row_changed(self, row):
        if row < 0 or row >= len(self._row_map):
            self.current_profile = None
            self._update_card()
            self._set_launch_state(
                self._running_profile is not None, self._running_profile
            )
            return
        self.current_profile = self._row_map[row]
        self._update_card()
        self._set_launch_state(self._running_profile is not None, self._running_profile)

    def _update_card(self):
        p = self.current_profile
        if p is None:
            self.card_label.setText(
                f'<span style="color:{theme.FG};font-size:14pt;'
                f"font-family:'{theme.UI_FONT}';font-weight:300\">"
                f"{translate.t('card.no_instance')}</span>"
                f"<br>"
                f'<span style="color:{theme.GRAY};font-size:9pt;'
                f"font-family:'{theme.UI_FONT}';\">"
                f"{translate.t('card.create_hint')}</span>"
            )
            return
        loader_label = translate.t(f"loader.{(p.loader or 'vanilla').lower()}")
        self.card_label.setText(
            f'<span style="color:{theme.FG};font-size:14pt;'
            f"font-family:'{theme.UI_FONT}';font-weight:300\">"
            f"{p.name}</span>"
            f"<br>"
            f'<span style="color:{theme.GRAY};font-size:9pt;'
            f"font-family:'{theme.UI_FONT}';\">"
            f"{loader_label} {p.version}</span>"
        )

    def add_new(self):
        ch = ChooseInstallDialog(self)
        if ch.exec() != QDialog.DialogCode.Accepted or not ch.choice:
            return

        if ch.choice == "blank":
            self._add_blank_profile()
        elif ch.choice == "local":
            self._add_local_modpack()
        elif ch.choice == "modrinth":
            self._add_modrinth_modpack()
        elif ch.choice == "migrate":
            self._migrate_from_existing()
        elif ch.choice == "preset":
            self._add_preset_profile(ch.preset_choice)
        elif ch.choice == "jar":
            self._add_jar_profile(ch.jar_path)

    def _add_preset_profile(self, preset):
        if preset != "labymod":
            return
        cache_dir = XERIA_ROOT / "cache" / "downloads"
        cache_dir.mkdir(parents=True, exist_ok=True)
        installer_path = cache_dir / "labymod4-installer.jar"

        if installer_path.exists():
            self._on_labymod_downloaded(True, installer_path)
            return

        self.console.log(
            "info", "Downloading LabyMod 4 Installer from official servers..."
        )
        url = "https://releases.labymod.net/api/v1/installer/production/java"

        def task(log, progress, progress_end):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "Xeria-Launcher/2.504"}
                )
                with urllib.request.urlopen(req, timeout=60) as response:
                    total = int(response.headers.get("content-length", 0))
                    done = 0
                    with open(installer_path, "wb") as f:
                        while True:
                            chunk = response.read(8192)
                            if not chunk:
                                break
                            f.write(chunk)
                            done += len(chunk)
                            if total:
                                progress("Downloading", done, total, "", "")
                progress_end()
                return True
            except Exception as e:  # noqa: BLE001
                log("error", f"Download failed: {e}")
                return False

        w = Worker(task)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection,
        )
        w.done.connect(
            lambda success: self._on_labymod_downloaded(success, installer_path),
            Qt.ConnectionType.QueuedConnection,
        )
        self._track(w)
        w.start()

    def _on_labymod_downloaded(self, success, path):
        if success:
            self.console.log("ok", f"LabyMod Installer ready at: {path}")
            self._add_jar_profile(str(path))
        else:
            self.console.log("error", "Failed to download LabyMod Installer.")

    def _add_jar_profile(self, jar_path):
        if not Path(jar_path).exists():
            QMessageBox.warning(self, "Error", "File not found.")
            return

        self.console.log("info", f"Launching installer GUI: {jar_path}")

        try:
            java_exe = best_java("26.3", log=self.console.log) or "java"

            env = os.environ.copy()
            if platform.system() == "Linux":
                st = os.environ.get("XDG_SESSION_TYPE", "").lower()
                wl = bool(os.environ.get("WAYLAND_DISPLAY")) or st == "wayland"
                if wl:
                    env["GDK_BACKEND"] = "x11"
                    env["_JAVA_AWT_WM_NONREPARENTING"] = "1"
                    self.console.log(
                        "sys",
                        "Wayland detected. Forcing installer to use X11 (XWayland).",
                    )

            cmd = [java_exe, "-jar", jar_path, "--installClient", str(MC_ROOT)]
            self.console.log("sys", " ".join(cmd))

            subprocess.Popen(
                cmd, cwd=str(Path(jar_path).parent), start_new_session=True, env=env
            )

            self._start_install_watcher()

        except Exception as e:  # noqa: BLE001
            self.console.log("error", f"Failed to launch installer: {e}")

    def _start_install_watcher(self):
        def get_snapshot():
            snap = set()
            if PROFILES_DIR.exists():
                snap.update(
                    f"xeria:{f.name}" for f in PROFILES_DIR.iterdir() if f.is_dir()
                )
            if MC_ROOT.exists():
                v_dir = MC_ROOT / "versions"
                if v_dir.exists():
                    snap.update(f"mc:{f.name}" for f in v_dir.iterdir() if f.is_dir())
            return snap

        initial_snap = get_snapshot()
        attempts = [0]

        def check():
            attempts[0] += 1
            current_snap = get_snapshot()

            if current_snap != initial_snap:
                self.console.log("ok", "New instance detected! Refreshing list...")
                self.load_profiles()
                return

            if attempts[0] < 120:
                QTimer.singleShot(1000, check)
            else:
                self.console.log("sys", "Install watcher timed out (2 mins).")

        QTimer.singleShot(1000, check)

    def _migrate_from_existing(self):
        from ui.migrate_dialogs import MigrateDialog

        if not self.profiles:
            QMessageBox.information(
                self, translate.t("migrate.title"), translate.t("migrate.warn_empty")
            )
            return
        if not self.releases:
            try:
                d = http.get(MANIFEST_URL).json()
                self.manifest = d
                self.releases = [v for v in d["versions"] if v["type"] == "release"]
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(
                    self,
                    translate.t("migrate.title"),
                    translate.t("migrate.warn_no_releases") + f"\n\n{e}",
                )
                return
        if not self.releases:
            QMessageBox.critical(
                self,
                translate.t("migrate.title"),
                translate.t("migrate.warn_no_releases"),
            )
            return
        dlg = MigrateDialog(self, self.profiles, self.releases, self.settings)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.result_profile is not None:
            self.console.log(
                "ok",
                translate.t("console.created_profile", name=dlg.result_profile.name),
            )
            self.load_profiles()

    def _add_blank_profile(self, forced_loader=None):
        if not self.releases:
            try:
                d = http.get(MANIFEST_URL).json()
                self.manifest = d
                self.releases = [v for v in d["versions"] if v["type"] == "release"]
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, translate.t("dialog.profile_new"), str(e))
                return
        dlg = ProfileDialog(self, self.releases, self.settings)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, ver, ram, loader = dlg.values()
        if forced_loader:
            loader = forced_loader
            if not name:
                name = f"{forced_loader.capitalize()} {ver}"

        if not name:
            QMessageBox.warning(
                self,
                translate.t("dialog.profile_new"),
                translate.t("dialog.name_required"),
            )
            return
        if any(c in name for c in r'/\:*?"<>|'):
            QMessageBox.warning(
                self,
                translate.t("dialog.profile_new"),
                translate.t("dialog.invalid_chars"),
            )
            return
        if (PROFILES_DIR / f"{name}.json").exists():
            QMessageBox.warning(
                self,
                translate.t("dialog.exists"),
                translate.t("dialog.exists_msg", name=name),
            )
            return
        p = Profile(name)
        p.version = ver
        p.ram = ram
        p.loader = loader
        dlg.apply(p)
        _ = p.dir
        p.save()
        self.console.log("ok", translate.t("console.created_profile", name=name))
        self.load_profiles()

    def _add_local_modpack(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            translate.t("dialog.local"),
            str(Path.home()),
            "Modpacks (*.xerpack *.zip *.mrpack);;All files (*)",
        )
        if not path:
            return
        w = Worker(self._install_local_modpack_task, path)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection,
        )
        w.done.connect(self._modpack_done, Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _install_local_modpack_task(self, path, log, progress, progress_end):
        return modpack.install(
            path, log=log, progress=progress, progress_end=progress_end
        )

    def _add_modrinth_modpack(self):
        dlg = ModpackSearchDialog(self, self.console.log)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result:
            return
        hit = dlg.result
        preferred_mc = dlg.selected_version() or None
        forced_loader = dlg.selected_loader() or "pack"
        if forced_loader == "pack":
            forced_loader = None
        w = Worker(self._download_and_install_modpack, hit, preferred_mc, forced_loader)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection,
        )
        w.done.connect(self._modpack_done, Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _download_and_install_modpack(
        self, hit, preferred_mc, forced_loader, log, progress, progress_end
    ):
        from integration import modrinth

        picked = modrinth.pick_modpack_file(hit["id"])
        if not picked:
            log("error", translate.t("console.no_compatible"))
            return None
        url, filename, ver = picked
        log("ok", f"{ver}: {filename}")
        import tempfile

        tmp = Path(tempfile.gettempdir()) / filename
        try:
            with http.stream("GET", url) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                done = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(65536):
                        f.write(chunk)
                        done += len(chunk)
                        if total and progress:
                            progress(filename, done, total, "", "")
            if progress_end:
                progress_end()
        except Exception as e:  # noqa: BLE001
            log("error", str(e))
            return None
        name = modpack.install(
            str(tmp),
            log=log,
            progress=progress,
            progress_end=progress_end,
            force_mc_version=preferred_mc,
            force_loader=forced_loader,
        )
        with contextlib.suppress(Exception):
            tmp.unlink()
        return name

    def _modpack_done(self, name):
        if name:
            self.console.log("ok", translate.t("console.modpack_installed", name=name))
            self.load_profiles()
        else:
            self.console.log("error", translate.t("console.modpack_failed"))

    def edit_profile(self):
        if not self.current_profile:
            return
        p = self.current_profile
        dlg = ProfileDialog(self, self.releases, self.settings, profile=p)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, ver, ram, loader = dlg.values()
        if not name:
            QMessageBox.warning(
                self,
                translate.t("dialog.profile_edit", name=p.name),
                translate.t("dialog.name_required"),
            )
            return
        old = p.name
        if name != old:
            if any(c in name for c in r'/\:*?"<>|'):
                QMessageBox.warning(
                    self,
                    translate.t("dialog.profile_edit", name=p.name),
                    translate.t("dialog.invalid_chars"),
                )
                return
            if (PROFILES_DIR / f"{name}.json").exists():
                QMessageBox.warning(
                    self,
                    translate.t("dialog.exists"),
                    translate.t("dialog.exists_msg", name=name),
                )
                return
            (PROFILES_DIR / f"{old}.json").rename(PROFILES_DIR / f"{name}.json")
            if (PROFILES_DIR / old).exists():
                (PROFILES_DIR / old).rename(PROFILES_DIR / name)
            p.name = name
        p.version = ver
        p.ram = ram
        p.loader = loader
        dlg.apply(p)
        p.save()
        self.load_profiles()

    def rename_profile(self):
        if not self.current_profile:
            return
        old = self.current_profile.name
        new, ok = QInputDialog.getText(
            self, translate.t("menu.rename"), "Name:", text=old
        )
        if not ok or not new.strip():
            return
        new = new.strip()
        if new == old:
            return
        if any(c in new for c in r'/\:*?"<>|'):
            QMessageBox.warning(
                self, translate.t("menu.rename"), translate.t("dialog.invalid_chars")
            )
            return
        if (PROFILES_DIR / f"{new}.json").exists():
            QMessageBox.warning(
                self,
                translate.t("dialog.exists"),
                translate.t("dialog.exists_msg", name=new),
            )
            return
        (PROFILES_DIR / f"{old}.json").rename(PROFILES_DIR / f"{new}.json")
        (PROFILES_DIR / old).rename(PROFILES_DIR / new)
        self.load_profiles()

    def duplicate_profile(self):
        if not self.current_profile:
            return
        src = self.current_profile
        new_name = f"{src.name} (copy)"
        n = 1
        while (PROFILES_DIR / f"{new_name}.json").exists():
            new_name = f"{src.name} (copy {n})"
            n += 1
        p = Profile(new_name)
        p.version = src.version
        p.ram = src.ram
        p.loader = src.loader
        p.loader_version = getattr(src, "loader_version", "")
        p.override_gc = src.override_gc
        p.override_jvm_flags = src.override_jvm_flags
        p.override_env_vars = src.override_env_vars
        p.override_java_path = src.override_java_path
        p.override_wrapper = src.override_wrapper
        p.mods_meta = dict(getattr(src, "mods_meta", {}) or {})
        _ = p.dir
        p.save()
        with contextlib.suppress(Exception):
            if src.dir.exists():
                shutil.copytree(str(src.dir), str(p.dir), dirs_exist_ok=True)
        self.load_profiles()

    def delete_profile(self):
        if not self.current_profile:
            return
        if (
            QMessageBox.question(
                self,
                translate.t("dialog.delete_title"),
                translate.t("dialog.delete_confirm", name=self.current_profile.name),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        n = self.current_profile.name
        p = self.current_profile

        if getattr(p, "_external_dir", None) is not None:
            try:
                shutil.rmtree(str(p._external_dir))
                self.console.log("warn", f"Deleted external folder: {p._external_dir}")
            except Exception as e:  # noqa: BLE001
                self.console.log("error", f"Failed to delete external folder: {e}")

        Profile.delete(n)
        self.console.log("warn", translate.t("console.deleted_profile", name=n))
        self.current_profile = None
        self.load_profiles()

    def open_folder(self):
        if not self.current_profile:
            return
        p = str(self.current_profile.dir)
        try:
            if IS_WIN:
                os.startfile(p)
            elif IS_MAC:
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
        except Exception as e:  # noqa: BLE001
            self.console.log("error", translate.t("console.open_folder_failed", err=e))

    def open_logs(self):
        if not self.current_profile:
            return
        logs = self.current_profile.dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        try:
            if IS_WIN:
                os.startfile(str(logs))
            elif IS_MAC:
                subprocess.Popen(["open", str(logs)])
            else:
                subprocess.Popen(["xdg-open", str(logs)])
        except Exception as e:  # noqa: BLE001
            self.console.log("error", translate.t("console.open_logs_failed", err=e))

    def export_mrpack(self):
        if not self.current_profile:
            return
        p = self.current_profile
        default_name = f"{p.name}.mrpack"
        path, _ = QFileDialog.getSaveFileName(
            self,
            translate.t("menu.export_modrinth"),
            str(Path.home() / default_name),
            "Modrinth pack (*.mrpack);;Zip (*.zip)",
        )
        if not path:
            return
        self.console.log("info", translate.t("console.exporting", name=p.name))
        w = Worker(self._export_task, p, path)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection,
        )
        self._track(w)
        w.start()

    def _export_task(self, profile, path, log, progress, progress_end):
        return modpack.export_mrpack(
            profile, path, log=log, progress=progress, progress_end=progress_end
        )

    def export_xeriapack(self):
        if not self.current_profile:
            return
        p = self.current_profile
        path, _ = QFileDialog.getSaveFileName(
            self,
            translate.t("menu.export_xeria"),
            str(Path.home() / f"{p.name}.xeriapack"),
            "Xeria pack (*.xeriapack);;Zip (*.zip)",
        )
        if not path:
            return
        self.console.log("info", translate.t("console.exporting", name=p.name))
        w = Worker(self._export_xeria_task, p, path)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.done.connect(lambda _r: None, Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _export_xeria_task(self, profile, path, log, progress, progress_end):
        dest = Path(path)
        game_dir = profile.dir
        items = []
        for f in game_dir.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(game_dir)
            if rel.parts and rel.parts[0] in (".cache", "logs", "crash-reports"):
                continue
            items.append((f, str(rel)))
        total = max(1, len(items))
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("profile.json", profile.json_path.read_text(encoding="utf-8"))
            for i, (src, arc) in enumerate(items, 1):
                z.write(str(src), arc)
                if progress and i % 20 == 0:
                    progress("backup", i, total, "", "")
        if progress_end:
            progress_end()
        log("ok", translate.t("console.exporting", name=dest.name))
        return str(dest)

    def import_instance(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            translate.t("menu.import_instance"),
            str(Path.home()),
            "Xeria pack (*.xeriapack *.zip *.mrpack);;All files (*)",
        )
        if not path:
            return
        if path.lower().endswith(".mrpack"):
            w = Worker(self._install_local_modpack_task, path)
            w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
            w.progress.connect(
                lambda *a: self.console.log("progress", a),
                Qt.ConnectionType.QueuedConnection,
            )
            w.progress_end.connect(
                lambda: self.console.log("progress_end", None),
                Qt.ConnectionType.QueuedConnection,
            )
            w.done.connect(self._modpack_done, Qt.ConnectionType.QueuedConnection)
            self._track(w)
            w.start()
            return
        self.console.log("info", translate.t("console.importing", name=Path(path).name))

        def task(log, progress, progress_end):
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if "profile.json" not in names:
                    log("error", translate.t("console.import_no_json"))
                    return None
                data = json.loads(z.read("profile.json"))
                base = data.get("name") or Path(path).stem
                name = base
                n = 1
                while (PROFILES_DIR / f"{name}.json").exists():
                    name = f"{base} ({n})"
                    n += 1
                target_dir = PROFILES_DIR / name
                target_dir.mkdir(parents=True, exist_ok=True)
                total = max(1, len(names))
                for i, member in enumerate(names, 1):
                    if member == "profile.json":
                        continue
                    if member.endswith("/"):
                        (target_dir / member).mkdir(parents=True, exist_ok=True)
                        continue
                    out = target_dir / member
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    if progress and i % 20 == 0:
                        progress("import", i, total, "", "")
                (PROFILES_DIR / f"{name}.json").write_text(json.dumps(data, indent=2))
                if progress_end:
                    progress_end()
                log("ok", translate.t("console.imported", name=name))
                return name

        w = Worker(task)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection,
        )
        w.done.connect(
            lambda _: self.load_profiles(), Qt.ConnectionType.QueuedConnection
        )
        self._track(w)
        w.start()

    def backup_instance(self):
        if not self.current_profile:
            return
        import datetime

        p = self.current_profile
        backups = XERIA_ROOT / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        dest = backups / f"{p.name}-{ts}.zip"
        self.console.log("info", translate.t("console.backup", name=dest.name))

        def task(log, progress, progress_end):
            files = []
            game_dir = p.dir
            for sub in ("mods", "resourcepacks", "shaderpacks", "config", "saves"):
                d = game_dir / sub
                if not d.exists():
                    continue
                for f in d.rglob("*"):
                    if f.is_file():
                        files.append((f, str(f.relative_to(game_dir))))
            total = max(1, len(files))
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
                for i, (src, arc) in enumerate(files, 1):
                    z.write(src, arc)
                    if progress and i % 20 == 0:
                        progress("backup", i, total, "", "")
            if progress_end:
                progress_end()
            log(
                "ok", translate.t("console.backup_done", kb=dest.stat().st_size // 1024)
            )

        w = Worker(task)
        w.log.connect(self.console.log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection,
        )
        self._track(w)
        w.start()

    def copy_launch_command(self):
        if not self.current_profile:
            return
        import shlex

        from PyQt6.QtGui import QGuiApplication

        from core.jvm import default_jvm_flags as _djf

        p = self.current_profile
        try:
            java_override = p.override_java_path or self.settings.get("java_path", "")
            java = best_java(p.version, log=None, override=java_override) or "java"
            gc = p.override_gc or self.settings.get("gc", "G1GC")
            combined = (
                (self.settings.get("default_jvm_flags", "") or "")
                + " "
                + (p.override_jvm_flags or "")
            ).strip()
            user_flags = shlex.split(combined) if combined else []
            jvm = user_flags if user_flags else _djf(p.ram, gc)
            cmd = (
                [java]
                + jvm
                + [
                    "-cp",
                    "<classpath>",
                    "net.minecraft.client.main.Main",
                    "--username",
                    self._get_username(),
                    "--version",
                    p.version,
                    "--gameDir",
                    str(p.dir),
                    "--assetsDir",
                    str(MC_ROOT / "assets"),
                    "--assetIndex",
                    "legacy",
                    "--uuid",
                    self._uuid(self._get_username()),
                    "--accessToken",
                    self.account.mc_access if self.account.signed_in else "0",
                    "--userType",
                    "msa" if self.account.signed_in else "legacy",
                    "--versionType",
                    "release",
                ]
            )
            wrapper = (
                p.override_wrapper or self.settings.get("wrapper_command", "").strip()
            )
            if wrapper:
                cmd = shlex.split(wrapper) + cmd
            text = " ".join(shlex.quote(c) for c in cmd)
            QGuiApplication.clipboard().setText(text)
            self.console.log("ok", translate.t("console.copied_cmd"))
        except Exception as e:  # noqa: BLE001
            self.console.log("error", translate.t("console.copy_failed", err=e))

    def _ctx_menu(self, pos):
        it = self.plist.itemAt(pos)
        if not it:
            return
        self.plist.setCurrentItem(it)
        if not self.current_profile:
            return

        m = QMenu(self)
        m.setStyleSheet(s_menu())

        is_vanilla = (self.current_profile.loader or "vanilla").lower() == "vanilla"

        for label_key, kind in (
            ("title.mods", "mod"),
            ("title.resourcepacks", "resourcepack"),
            ("title.shaders", "shader"),
        ):
            label = translate.t(label_key)
            a = QAction(label, m)

            if is_vanilla and kind in ("mod", "shader"):
                a.setText(f"{label} (Vanilla)")
                a.setEnabled(False)
            else:
                a.triggered.connect(lambda _, k=kind: self._open_browse(k))

            m.addAction(a)

        m.addSeparator()
        for label_key, fn in (
            ("menu.edit_instance", self.edit_profile),
            ("menu.open_folder", self.open_folder),
            ("menu.rename", self.rename_profile),
            ("menu.duplicate", self.duplicate_profile),
        ):
            a = QAction(translate.t(label_key), m)
            a.triggered.connect(fn)
            m.addAction(a)
        m.addSeparator()
        exp = m.addMenu(translate.t("menu.export_instance"))
        exp.setStyleSheet(s_menu())
        for label_key, fn in (
            ("menu.export_modrinth", self.export_mrpack),
            ("menu.export_xeria", self.export_xeriapack),
        ):
            a = QAction(translate.t(label_key), exp)
            a.triggered.connect(fn)
            exp.addAction(a)
        for label_key, fn in (
            ("menu.import_instance", self.import_instance),
            ("menu.backup", self.backup_instance),
            ("menu.copy_cmd", self.copy_launch_command),
            ("menu.open_logs", self.open_logs),
        ):
            a = QAction(translate.t(label_key), m)
            a.triggered.connect(fn)
            m.addAction(a)
        m.addSeparator()
        a = QAction(translate.t("btn.delete"), m)
        a.triggered.connect(self.delete_profile)
        m.addAction(a)
        m.exec(self.plist.mapToGlobal(pos))

    def _open_browse(self, kind):
        from browse.items import ItemsDialog

        if not self.current_profile:
            return
        ItemsDialog(self, self.current_profile, self.console.log, kind).exec()
