import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QMessageBox, QDialog, QFileDialog, QInputDialog, QListWidgetItem,
)

from core import theme
from core import translate
from core.paths import (
    PROFILES_DIR, MANIFEST_URL,
    IS_WIN, IS_MAC, NO_WINDOW, XERIA_ROOT, MC_ROOT,
)
from core.java import best_java
from core.worker import Worker
from instances.profile import Profile
from ui.dialogs import (
    ChooseInstallDialog, ModpackSearchDialog, ProfileDialog,
)
from ui.helpers import s_menu
from ui.loader_icons import loader_icon_sync, fetch_loader_icon
from integration import net as http


class ProfilesMixin:
    ROW_HEIGHT = 56
    ROW_GAP = 6

    def load_profiles(self):
        self.plist.blockSignals(True)
        self.plist.clear()
        self.plist.setSpacing(self.ROW_GAP)
        self._row_map = []
        self.profiles = Profile.load_all()

        for p in self.profiles:
            it = QListWidgetItem(f"{p.name}\n{p.version}")
            it.setSizeHint(QSize(0, self.ROW_HEIGHT))
            loader = (p.loader or "vanilla").lower()
            cached = loader_icon_sync(loader)
            if cached is not None:
                it.setIcon(cached)
            self.plist.addItem(it)
            self._row_map.append(p)

        self.plist.blockSignals(False)

        for p in self.profiles:
            loader = (p.loader or "vanilla").lower()
            if loader_icon_sync(loader) is None:
                fetch_loader_icon(loader, self._apply_loader_icon)

        if self.profiles:
            self.plist.setCurrentRow(0)
        else:
            self.current_profile = None
            self._update_card()

    def _on_row_changed(self, row):
        if row < 0 or row >= len(self._row_map):
            self.current_profile = None
            self._update_card()
            self._set_launch_state(self._running_profile is not None,
                                   self._running_profile)
            return
        self.current_profile = self._row_map[row]
        self._update_card()
        self._set_launch_state(self._running_profile is not None,
                               self._running_profile)

    def _update_card(self):
        p = self.current_profile
        if p is None:
            self.card_title.setText(translate.t("card.no_instance"))
            self.card_sub.setText(translate.t("card.create_hint"))
            return
        self.card_title.setText(p.name)
        loader_label = translate.t(f"loader.{(p.loader or 'vanilla').lower()}")
        self.card_sub.setText(f"{loader_label} {p.version}")

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

    def _migrate_from_existing(self):
        from ui.migrate_dialogs import MigrateDialog
        if not self.profiles:
            QMessageBox.information(
                self, translate.t("migrate.title"),
                translate.t("migrate.warn_empty"))
            return
        if not self.releases:
            try:
                d = http.get(MANIFEST_URL).json()
                self.manifest = d
                self.releases = [v for v in d["versions"]
                                 if v["type"] == "release"]
            except Exception as e:
                QMessageBox.critical(
                    self, translate.t("migrate.title"),
                    translate.t("migrate.warn_no_releases") + f"\n\n{e}")
                return
        if not self.releases:
            QMessageBox.critical(
                self, translate.t("migrate.title"),
                translate.t("migrate.warn_no_releases"))
            return
        dlg = MigrateDialog(
            self, self.profiles, self.releases, self.settings)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.result_profile is not None:
            self.console.log(
                "ok",
                translate.t("console.created_profile",
                            name=dlg.result_profile.name))
            self.load_profiles()

    def _add_blank_profile(self):
        if not self.releases:
            try:
                d = http.get(MANIFEST_URL).json()
                self.manifest = d
                self.releases = [v for v in d["versions"]
                                 if v["type"] == "release"]
            except Exception as e:
                QMessageBox.critical(
                    self, translate.t("dialog.profile_new"), str(e))
                return
        dlg = ProfileDialog(self, self.releases, self.settings)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, ver, ram, loader = dlg.values()
        if not name:
            QMessageBox.warning(
                self, translate.t("dialog.profile_new"),
                translate.t("dialog.name_required"))
            return
        if any(c in name for c in r'/\:*?"<>|'):
            QMessageBox.warning(
                self, translate.t("dialog.profile_new"),
                translate.t("dialog.invalid_chars"))
            return
        if (PROFILES_DIR / f"{name}.json").exists():
            QMessageBox.warning(
                self, translate.t("dialog.exists"),
                translate.t("dialog.exists_msg", name=name))
            return
        p = Profile(name)
        p.version = ver
        p.ram = ram
        p.loader = loader
        dlg.apply(p)
        p.dir
        p.save()
        self.console.log("ok",
                         translate.t("console.created_profile", name=name))
        self.load_profiles()

    def _add_local_modpack(self):
        path, _ = QFileDialog.getOpenFileName(
            self, translate.t("dialog.local"), str(Path.home()),
            "Modpacks (*.xerpack *.zip *.mrpack);;All files (*)")
        if not path:
            return
        w = Worker(self._install_local_modpack_task, path)
        w.log.connect(self.console.log,
                      Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection)
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection)
        w.done.connect(self._modpack_done,
                       Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _install_local_modpack_task(self, path, log, progress, progress_end):
        from integration import modpack
        return modpack.install(path, log=log, progress=progress,
                               progress_end=progress_end)

    def _add_modrinth_modpack(self):
        dlg = ModpackSearchDialog(self, self.console.log)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result:
            return
        hit = dlg.result
        w = Worker(self._download_and_install_modpack, hit)
        w.log.connect(self.console.log,
                      Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection)
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection)
        w.done.connect(self._modpack_done,
                       Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _download_and_install_modpack(self, hit, log, progress, progress_end):
        from integration import modrinth, modpack
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
        except Exception as e:
            log("error", str(e))
            return None
        name = modpack.install(str(tmp), log=log, progress=progress,
                               progress_end=progress_end)
        try:
            tmp.unlink()
        except Exception:
            pass
        return name

    def _modpack_done(self, name):
        if name:
            self.console.log(
                "ok", translate.t("console.modpack_installed", name=name))
            self.load_profiles()
        else:
            self.console.log(
                "error", translate.t("console.modpack_failed"))

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
                self, translate.t("dialog.profile_edit", name=p.name),
                translate.t("dialog.name_required"))
            return
        old = p.name
        if name != old:
            if any(c in name for c in r'/\:*?"<>|'):
                QMessageBox.warning(
                    self, translate.t("dialog.profile_edit", name=p.name),
                    translate.t("dialog.invalid_chars"))
                return
            if (PROFILES_DIR / f"{name}.json").exists():
                QMessageBox.warning(
                    self, translate.t("dialog.exists"),
                    translate.t("dialog.exists_msg", name=name))
                return
            (PROFILES_DIR / f"{old}.json").rename(
                PROFILES_DIR / f"{name}.json")
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
            self, translate.t("menu.rename"), "Name:", text=old)
        if not ok or not new.strip():
            return
        new = new.strip()
        if new == old:
            return
        if any(c in new for c in r'/\:*?"<>|'):
            QMessageBox.warning(
                self, translate.t("menu.rename"),
                translate.t("dialog.invalid_chars"))
            return
        if (PROFILES_DIR / f"{new}.json").exists():
            QMessageBox.warning(
                self, translate.t("dialog.exists"),
                translate.t("dialog.exists_msg", name=new))
            return
        (PROFILES_DIR / f"{old}.json").rename(
            PROFILES_DIR / f"{new}.json")
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
        p.override_gc = src.override_gc
        p.override_jvm_flags = src.override_jvm_flags
        p.override_env_vars = src.override_env_vars
        p.override_java_path = src.override_java_path
        p.override_wrapper = src.override_wrapper
        p.mods_meta = dict(getattr(src, "mods_meta", {}) or {})
        p.dir
        p.save()
        try:
            if src.dir.exists():
                shutil.copytree(str(src.dir), str(p.dir),
                                dirs_exist_ok=True)
        except Exception:
            pass
        self.load_profiles()

    def delete_profile(self):
        if not self.current_profile:
            return
        if QMessageBox.question(
            self, translate.t("dialog.delete_title"),
            translate.t("dialog.delete_confirm",
                        name=self.current_profile.name),
        ) != QMessageBox.StandardButton.Yes:
            return
        n = self.current_profile.name
        Profile.delete(n)
        self.console.log(
            "warn", translate.t("console.deleted_profile", name=n))
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
        except Exception as e:
            self.console.log(
                "error",
                translate.t("console.open_folder_failed", err=e))

    def export_mrpack(self):
        if not self.current_profile:
            return
        p = self.current_profile
        default_name = f"{p.name}.mrpack"
        path, _ = QFileDialog.getSaveFileName(
            self, translate.t("menu.export_modrinth"),
            str(Path.home() / default_name),
            "Modrinth pack (*.mrpack);;Zip (*.zip)")
        if not path:
            return
        self.console.log(
            "info", translate.t("console.exporting", name=p.name))
        w = Worker(self._export_task, p, path)
        w.log.connect(self.console.log,
                      Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection)
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def _export_task(self, profile, path, log, progress, progress_end):
        from integration import modpack
        return modpack.export_mrpack(profile, path, log=log,
                                     progress=progress,
                                     progress_end=progress_end)

    def export_xeriapack(self):
        if not self.current_profile:
            return
        p = self.current_profile
        path, _ = QFileDialog.getSaveFileName(
            self, translate.t("menu.export_xeria"),
            str(Path.home() / f"{p.name}.xeriapack"),
            "Xeria pack (*.xeriapack);;Zip (*.zip)")
        if not path:
            return
        self.console.log(
            "info", translate.t("console.exporting", name=p.name))
        w = Worker(self._export_xeria_task, p, path)
        w.log.connect(self.console.log,
                      Qt.ConnectionType.QueuedConnection)
        w.done.connect(
            lambda _r: None, Qt.ConnectionType.QueuedConnection)
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
            z.writestr("profile.json",
                       profile.json_path.read_text(encoding="utf-8"))
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
            self, translate.t("menu.import_instance"), str(Path.home()),
            "Xeria pack (*.xeriapack *.zip *.mrpack);;All files (*)")
        if not path:
            return
        if path.lower().endswith(".mrpack"):
            w = Worker(self._install_local_modpack_task, path)
            w.log.connect(self.console.log,
                          Qt.ConnectionType.QueuedConnection)
            w.progress.connect(
                lambda *a: self.console.log("progress", a),
                Qt.ConnectionType.QueuedConnection)
            w.progress_end.connect(
                lambda: self.console.log("progress_end", None),
                Qt.ConnectionType.QueuedConnection)
            w.done.connect(self._modpack_done,
                           Qt.ConnectionType.QueuedConnection)
            self._track(w)
            w.start()
            return
        self.console.log(
            "info",
            translate.t("console.importing", name=Path(path).name))

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
                        (target_dir / member).mkdir(
                            parents=True, exist_ok=True)
                        continue
                    out = target_dir / member
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    if progress and i % 20 == 0:
                        progress("import", i, total, "", "")
                (PROFILES_DIR / f"{name}.json").write_text(
                    json.dumps(data, indent=2))
                if progress_end:
                    progress_end()
                log("ok", translate.t("console.imported", name=name))
                return name

        w = Worker(task)
        w.log.connect(self.console.log,
                      Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection)
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection)
        w.done.connect(lambda _: self.load_profiles(),
                       Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def backup_instance(self):
        if not self.current_profile:
            return
        import datetime
        p = self.current_profile
        backups = XERIA_ROOT / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = backups / f"{p.name}-{ts}.zip"
        self.console.log("info", translate.t("console.backup", name=dest.name))

        def task(log, progress, progress_end):
            files = []
            game_dir = p.dir
            for sub in ("mods", "resourcepacks", "shaderpacks",
                        "config", "saves"):
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
            log("ok", translate.t("console.backup_done",
                                  kb=dest.stat().st_size // 1024))

        w = Worker(task)
        w.log.connect(self.console.log,
                      Qt.ConnectionType.QueuedConnection)
        w.progress.connect(
            lambda *a: self.console.log("progress", a),
            Qt.ConnectionType.QueuedConnection)
        w.progress_end.connect(
            lambda: self.console.log("progress_end", None),
            Qt.ConnectionType.QueuedConnection)
        self._track(w)
        w.start()

    def copy_launch_command(self):
        if not self.current_profile:
            return
        p = self.current_profile
        try:
            from core.java import best_java as _bj
            from core.jvm import default_jvm_flags as _djf
            java_override = (p.override_java_path
                             or self.settings.get("java_path", ""))
            java = _bj(p.version, log=None, override=java_override) or "java"
            gc = p.override_gc or self.settings.get("gc", "G1GC")
            combined = ((self.settings.get("jvm_flags", "") or "") + " "
                        + (p.override_jvm_flags or "")).strip()
            import shlex as _sh
            user_flags = _sh.split(combined) if combined else []
            jvm = _djf(p.ram, gc) + user_flags
            cmd = [java] + jvm + [
                "-cp", "<classpath>",
                "net.minecraft.client.main.Main",
                "--username", self._get_username(),
                "--version", p.version,
                "--gameDir", str(p.dir),
                "--assetsDir", str(MC_ROOT / "assets"),
                "--assetIndex", "legacy",
                "--uuid", self._uuid(self._get_username()),
                "--accessToken",
                self.account.mc_access
                if self.account.signed_in else "0",
                "--userType",
                "msa" if self.account.signed_in else "legacy",
                "--versionType", "release"]
            wrapper = (p.override_wrapper
                       or self.settings.get("wrapper_command", "").strip())
            if wrapper:
                cmd = _sh.split(wrapper) + cmd
            text = " ".join(_sh.quote(c) for c in cmd)
            from PyQt6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(text)
            self.console.log("ok", translate.t("console.copied_cmd"))
        except Exception as e:
            self.console.log(
                "error", translate.t("console.copy_failed", err=e))

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
        except Exception as e:
            self.console.log(
                "error", translate.t("console.open_logs_failed", err=e))
