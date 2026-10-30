import contextlib

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core import theme, translate
from core.paths import PROFILES_DIR
from core.worker import Worker
from instances import migrate
from ui.helpers import (
    TranslucentDialog,
    dialog_shell_style,
    s_combo,
    s_entry,
)

KIND_BY_FOLDER = {
    "mods": "mod",
    "resourcepacks": "resourcepack",
    "shaderpacks": "shader",
}


class MigrateDialog(TranslucentDialog):
    def __init__(self, parent, profiles, releases, settings):
        super().__init__(parent)
        self.settings = settings
        self.profiles = list(profiles or [])
        self.releases = list(releases or [])
        self.source_profile = None
        self.source_info = None
        self.checks = {}
        self.result_profile = None
        self._check_worker = None
        self._copy_worker = None
        self._closing = False

        self.setWindowTitle(translate.t("migrate.title"))
        self.setFixedSize(760, 660)
        self.setSizeGripEnabled(False)
        self.setStyleSheet(
            dialog_shell_style() + f"QLabel{{background:transparent;color:{theme.FG};"
            f"font-family:'{theme.UI_FONT}'}}"
            f"QListWidget{{background:{theme.BG3};color:{theme.FG};"
            f"outline:0;padding:0;border-radius:8px}}"
            f"QListWidget::item{{padding:6px;"
            f"border-bottom:1px solid {theme.BG2}}}"
            f"QCheckBox{{background:transparent;color:{theme.FG};"
            f"font-family:'{theme.UI_FONT}'}}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(10)

        title = QLabel(translate.t("migrate.header"))
        title.setStyleSheet(f"color:{theme.FG};font-size:14pt;font-weight:bold")
        v.addWidget(title)

        sub = QLabel(translate.t("migrate.desc"))
        sub.setStyleSheet(f"color:{theme.GRAY};font-size:9pt")
        sub.setWordWrap(True)
        v.addWidget(sub)

        grid = QGridLayout()
        grid.setSpacing(8)

        grid.addWidget(QLabel(translate.t("migrate.source")), 0, 0)
        self.source_box = QComboBox()
        self.source_box.setStyleSheet(s_combo())
        for p in self.profiles:
            self.source_box.addItem(p.name, p.name)
        grid.addWidget(self.source_box, 0, 1, 1, 2)

        grid.addWidget(QLabel(translate.t("migrate.new_name")), 1, 0)
        self.name_edit = QLineEdit()
        self.name_edit.setStyleSheet(s_entry())
        grid.addWidget(self.name_edit, 1, 1, 1, 2)

        grid.addWidget(QLabel(translate.t("dialog.loader")), 2, 0)
        self.loader_lbl = QLabel("-")
        self.loader_lbl.setStyleSheet(
            f"color:{theme.FG};background:{theme.BG3};padding:6px;"
            f"border-radius:8px;font-family:'{theme.UI_FONT}'"
        )
        grid.addWidget(self.loader_lbl, 2, 1, 1, 2)

        grid.addWidget(QLabel(translate.t("dialog.ram")), 3, 0)
        self.ram_lbl = QLabel("-")
        self.ram_lbl.setStyleSheet(
            f"color:{theme.FG};background:{theme.BG3};padding:6px;"
            f"border-radius:8px;font-family:'{theme.UI_FONT}'"
        )
        grid.addWidget(self.ram_lbl, 3, 1, 1, 2)

        grid.addWidget(QLabel(translate.t("migrate.target_version")), 4, 0)
        self.ver_box = QComboBox()
        self.ver_box.setStyleSheet(s_combo())
        grid.addWidget(self.ver_box, 4, 1, 1, 2)

        v.addLayout(grid)

        self.warn_lbl = QLabel("")
        self.warn_lbl.setStyleSheet(
            f"color:{theme.YELLOW};font-size:9pt;padding:8px;"
            f"background:{theme.BG3};border-radius:8px"
        )
        self.warn_lbl.setWordWrap(True)
        v.addWidget(self.warn_lbl)

        legend = QLabel(translate.t("migrate.legend"))
        legend.setStyleSheet(f"color:{theme.GRAY};font-size:9pt")
        legend.setWordWrap(True)
        v.addWidget(legend)

        self.check_list = QListWidget()
        self.check_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        v.addWidget(self.check_list, 1)

        misc = QFrame()
        misc.setStyleSheet(f"QFrame{{background:{theme.BG3};border-radius:8px}}")
        ml = QHBoxLayout(misc)
        ml.setContentsMargins(10, 8, 10, 8)
        ml.setSpacing(14)
        self.cb_worlds = QCheckBox(translate.t("migrate.copy_worlds"))
        self.cb_worlds.setStyleSheet(
            f"QCheckBox{{background:transparent;color:{theme.FG};"
            f"font-size:9pt;font-family:'{theme.UI_FONT}'}}"
        )
        ml.addWidget(self.cb_worlds)
        ml.addStretch()
        v.addWidget(misc)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton(translate.t("btn.cancel"))
        cancel.setAutoDefault(False)
        cancel.setDefault(False)
        cancel.setStyleSheet(
            f"QPushButton{{background:{theme.BG3};color:{theme.FG};"
            f"padding:8px 20px;border-radius:8px;"
            f"font-family:'{theme.UI_FONT}'}}"
            f"QPushButton:hover{{background:{theme.BORDER}}}"
        )
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)

        self.migrate_btn = QPushButton(translate.t("migrate.btn_migrate"))
        self.migrate_btn.setAutoDefault(False)
        self.migrate_btn.setDefault(False)
        self.migrate_btn.setEnabled(False)
        self.migrate_btn.setStyleSheet(
            f"QPushButton{{background:{theme.ACCENT};"
            f"color:{theme.on_accent()};"
            f"padding:8px 24px;font-weight:bold;border-radius:8px;"
            f"font-family:'{theme.UI_FONT}'}}"
            f"QPushButton:hover{{background:{theme.ACCENT2}}}"
            f"QPushButton:disabled{{background:{theme.BG3};"
            f"color:{theme.GRAY}}}"
        )
        self.migrate_btn.clicked.connect(self._run_migration)
        btns.addWidget(self.migrate_btn)
        v.addLayout(btns)

        self.source_box.currentIndexChanged.connect(self._on_source_changed)
        self.ver_box.currentIndexChanged.connect(self._on_target_changed)

        self._init_source()

    def _stop_workers(self):
        self._closing = True
        for attr in ("_check_worker", "_copy_worker"):
            w = getattr(self, attr, None)
            if w is None:
                continue
            with contextlib.suppress(Exception):
                w.log.disconnect()
            with contextlib.suppress(Exception):
                w.progress.disconnect()
            with contextlib.suppress(Exception):
                w.progress_end.disconnect()
            with contextlib.suppress(Exception):
                w.done.disconnect()
            with contextlib.suppress(Exception):
                w.quit()
                if not w.wait(3000):
                    w.setParent(None)
                    from core.worker import _leaked_threads

                    _leaked_threads.append(w)
            setattr(self, attr, None)

    def closeEvent(self, event):
        self._stop_workers()
        super().closeEvent(event)

    def reject(self):
        self._stop_workers()
        super().reject()

    def accept(self):
        self._stop_workers()
        super().accept()

    def _init_source(self):
        if not self.profiles:
            self.warn_lbl.setText(translate.t("migrate.warn_empty"))
            self.source_box.setEnabled(False)
            return
        if not self.releases:
            self.warn_lbl.setText(translate.t("migrate.warn_no_releases"))
            self.source_box.setEnabled(False)
            self.ver_box.setEnabled(False)
            return
        self.source_box.setCurrentIndex(0)
        self._on_source_changed()

    def _unique_name(self, base):
        name = base
        n = 1
        while (PROFILES_DIR / f"{name}.json").exists():
            name = f"{base} ({n})"
            n += 1
        return name

    def _repopulate_versions(self):
        self.ver_box.blockSignals(True)
        self.ver_box.clear()
        self.ver_box.addItem(translate.t("migrate.choose_target"), None)
        src_ver = self.source_profile.version if self.source_profile else ""
        added = 0
        for r in self.releases:
            vid = r["id"]
            if vid == src_ver:
                continue
            self.ver_box.addItem(vid, vid)
            added += 1
        self.ver_box.setCurrentIndex(0)
        self.ver_box.blockSignals(False)
        return added

    def _on_source_changed(self):
        if not self.profiles:
            return
        name = self.source_box.currentData()
        profile = next((p for p in self.profiles if p.name == name), None)
        if profile is None:
            return
        self.source_profile = profile
        self.source_info = migrate.scan_profile(profile)

        ld = (profile.loader or "vanilla").capitalize()
        self.loader_lbl.setText(ld)
        self.ram_lbl.setText(f"{profile.ram} GB")

        added = self._repopulate_versions()
        self.check_list.clear()
        self.checks = {}
        self.migrate_btn.setEnabled(False)
        self.name_edit.setText("")
        if added == 0:
            self.warn_lbl.setText(translate.t("migrate.no_versions"))
        else:
            self.warn_lbl.setText(translate.t("migrate.choose_first"))

    def _on_target_changed(self, *_):
        ver = self.ver_box.currentData()
        if not ver or self.source_info is None:
            self.check_list.clear()
            self.checks = {}
            self.migrate_btn.setEnabled(False)
            if self.ver_box.currentIndex() <= 0:
                self.warn_lbl.setText(translate.t("migrate.choose_first"))
            return
        base = f"{self.source_profile.name} - {ver}".strip()
        self.name_edit.setText(self._unique_name(base))
        self.warn_lbl.setText(translate.t("migrate.checking"))
        self._start_check()

    def _start_check(self):
        if self._closing:
            return
        ver = self.ver_box.currentData()
        if self.source_info is None or not ver:
            return
        if self._check_worker is not None:
            with contextlib.suppress(Exception):
                self._check_worker.done.disconnect()
            with contextlib.suppress(Exception):
                self._check_worker.quit()
                self._check_worker.wait(500)
            self._check_worker = None

        self.checks = {}
        self.check_list.clear()
        self.migrate_btn.setEnabled(False)

        info = self.source_info
        mc_version = ver
        loader = (self.source_profile.loader or "vanilla").lower()

        all_files = []
        for folder in ("mods", "resourcepacks", "shaderpacks"):
            project_type = KIND_BY_FOLDER[folder]
            for p in info[folder]:
                all_files.append((project_type, p))

        if not all_files:
            self.warn_lbl.setText(translate.t("migrate.no_files"))
            self._build_checklist()
            return

        def task(log, progress, progress_end):
            results = {}
            total = len(all_files)
            done = [0]
            for kind, p in all_files:
                sub = migrate.check_files(
                    [p],
                    mc_version,
                    kind,
                    loader,
                    log=log,
                    progress=lambda i, t, d=done, tt=total, p=p: progress(
                        "check", d[0] + i, tt, p.name, ""
                    ),
                )
                results.update(sub)
                done[0] += 1
            progress_end()
            return results

        w = Worker(task)
        w.log.connect(self._worker_log, Qt.ConnectionType.QueuedConnection)
        w.progress.connect(self._worker_progress, Qt.ConnectionType.QueuedConnection)
        w.done.connect(self._checks_done, Qt.ConnectionType.QueuedConnection)
        self._check_worker = w
        w.start()

    def _worker_log(self, tag, msg):
        if self._closing:
            return
        if tag in ("sys", "net"):
            self.warn_lbl.setText(translate.t("migrate.checking_msg", msg=msg))

    def _worker_progress(self, label, cur, total, extra, speed):
        if self._closing:
            return
        self.warn_lbl.setText(
            translate.t("migrate.checking_progress", cur=cur, total=total, name=extra)
        )

    def _checks_done(self, results):
        if self._closing:
            return
        self._check_worker = None
        if not isinstance(results, dict):
            self.warn_lbl.setText(translate.t("migrate.check_failed"))
            self._build_checklist()
            return
        self.checks = results
        self._build_checklist()

    def _build_checklist(self):
        if self._closing:
            return
        info = self.source_info
        if info is None:
            return
        self.check_list.clear()

        incompat = 0
        compat = 0
        for folder in ("mods", "resourcepacks", "shaderpacks"):
            label_key = {
                "mods": "migrate.hdr_mods",
                "resourcepacks": "migrate.hdr_resourcepacks",
                "shaderpacks": "migrate.hdr_shaderpacks",
            }[folder]
            files = info[folder]
            if not files:
                continue
            hdr = QListWidgetItem(translate.t(label_key, n=len(files)))
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            hdr.setForeground(QColor(theme.ACCENT))
            self.check_list.addItem(hdr)
            for p in files:
                c = self.checks.get(str(p))
                if c is None:
                    continue
                ok = c["compatible"]
                if ok:
                    compat += 1
                else:
                    incompat += 1
                mark = "[OK]" if ok else "[NO]"
                text = f"  {mark}  {p.name}\n       {c['reason']}"
                it = QListWidgetItem(text)
                it.setForeground(QColor(theme.FG if ok else theme.GRAY))
                self.check_list.addItem(it)

        self.cb_worlds.setChecked(info["has_saves"])
        self.cb_worlds.setEnabled(info["has_saves"])

        loader = (
            (self.source_profile.loader or "vanilla") if self.source_profile else "-"
        )

        ver = self.ver_box.currentData()
        total = compat + incompat
        if total == 0:
            self.warn_lbl.setText(translate.t("migrate.no_files_migrate"))
        elif incompat > 0:
            self.warn_lbl.setText(
                translate.t(
                    "migrate.warn_partial",
                    ok=compat,
                    skip=incompat,
                    version=ver,
                    loader=loader,
                )
            )
        else:
            self.warn_lbl.setText(translate.t("migrate.warn_all_ok", n=compat))

        self.migrate_btn.setEnabled(bool(ver))

    def _collect_plan(self):
        info = self.source_info
        plan = {
            "mods": [],
            "resourcepacks": [],
            "shaderpacks": [],
            "copy_config": info["has_config"],
            "copy_saves": self.cb_worlds.isChecked() and info["has_saves"],
            "copy_options": info["has_options"],
            "copy_servers": info["has_servers"],
            "skipped": [],
            "_source_config_dir": info["path"] / "config",
            "_source_saves_dir": info["path"] / "saves",
            "_source_options": info["path"] / "options.txt",
            "_source_servers": info["path"] / "servers.dat",
        }
        for kind in ("mods", "resourcepacks", "shaderpacks"):
            for p in info[kind]:
                c = self.checks.get(str(p))
                if c is None:
                    plan["skipped"].append((p, "not checked"))
                    continue
                if c["compatible"] and c.get("download_url"):
                    plan[kind].append(
                        (
                            p,
                            f"{kind}/{c['download_name']}",
                            c["download_url"],
                            c["download_name"],
                            c["title"],
                        )
                    )
                else:
                    plan["skipped"].append((p, c["reason"]))
        return plan

    def _run_migration(self):
        if self._closing:
            return
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(
                self, translate.t("migrate.title"), translate.t("migrate.name_required")
            )
            return
        if any(c in name for c in r'/\:*?"<>|'):
            QMessageBox.warning(
                self, translate.t("migrate.title"), translate.t("migrate.invalid_chars")
            )
            return

        mc_version = self.ver_box.currentData()
        if not mc_version:
            QMessageBox.warning(
                self,
                translate.t("migrate.title"),
                translate.t("migrate.choose_target_warn"),
            )
            return
        if self.source_profile and mc_version == self.source_profile.version:
            QMessageBox.warning(
                self, translate.t("migrate.title"), translate.t("migrate.same_version")
            )
            return

        loader = (self.source_profile.loader or "vanilla").lower()
        plan = self._collect_plan()

        try:
            profile = migrate.create_profile(self.source_profile, name, mc_version)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self,
                translate.t("migrate.title"),
                translate.t("migrate.cant_create", err=e),
            )
            return

        self.migrate_btn.setEnabled(False)
        self.warn_lbl.setText(translate.t("migrate.downloading"))

        def task(log, progress, progress_end):
            installed, skipped, failed = migrate.apply_plan(
                profile,
                plan,
                mc_version,
                loader,
                log=log,
                progress=lambda c, t: progress("download", c, t, "", ""),
            )
            progress_end()
            return installed, skipped, failed, str(profile.dir)

        w = Worker(task)
        w.log.connect(
            lambda tag, msg: (
                self.warn_lbl.setText(
                    translate.t(
                        "migrate.progress", label=tag.capitalize(), cur=0, total=0
                    )
                )
                if not self._closing
                else None
            ),
            Qt.ConnectionType.QueuedConnection,
        )
        w.progress.connect(
            lambda label, cur, total, extra, speed: (
                self.warn_lbl.setText(
                    translate.t(
                        "migrate.progress",
                        label=label.capitalize(),
                        cur=cur,
                        total=total,
                    )
                )
                if not self._closing
                else None
            ),
            Qt.ConnectionType.QueuedConnection,
        )
        w.done.connect(
            lambda r: self._migration_done(r, profile),
            Qt.ConnectionType.QueuedConnection,
        )
        self._copy_worker = w
        w.start()

    def _migration_done(self, result, profile):
        if self._closing:
            return
        self._copy_worker = None
        if not result:
            QMessageBox.critical(
                self, translate.t("migrate.title"), translate.t("migrate.failed")
            )
            self.migrate_btn.setEnabled(True)
            return
        installed, skipped, failed, _ = result
        self.result_profile = profile
        failed_part = translate.t("migrate.done_failed", n=failed) if failed else ""
        msg = translate.t(
            "migrate.done",
            installed=installed,
            skipped=skipped,
            failed_part=failed_part,
        )
        if skipped:
            msg += "\n\n" + translate.t("migrate.skip_note")
        QMessageBox.information(self, translate.t("migrate.done_title"), msg)
        self.accept()
