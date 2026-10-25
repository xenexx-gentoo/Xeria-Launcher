import hashlib
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import Qt, QSize, QUrl, QTimer
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtNetwork import QNetworkAccessManager
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QMessageBox, QMenu,
    QSizePolicy,
)

from core import theme
from core import translate
from core.paths import IS_WIN, IS_MAC
from core.worker import Worker, _leaked_threads
from integration import modrinth, net as http
from browse.common import (
    ICON_SIZE_ROW, make_placeholder, square_icon, square_icon_pixmap,
    IconLoader,
)


KIND_FOLDER = {
    "mod":          "mods",
    "resourcepack": "resourcepacks",
    "shader":       "shaderpacks",
}

KIND_PROJECT_TYPE = {
    "mod":          "mod",
    "resourcepack": "resourcepack",
    "shader":       "shader",
}

DOWNLOAD_WORKERS = 12
LOOKUP_WORKERS = 3


def _verify_installed(path, mc_version, kind, loader):
    from instances.migrate import verify_one
    return verify_one(path, mc_version, kind, loader)


def _kind_label(kind):
    return translate.t(f"kind.{kind}")


class ControlTab(QWidget):
    ROW_HEIGHT = 64

    def __init__(self, parent, profile, log_fn, kind):
        super().__init__(parent)
        self.profile = profile
        self.log_fn = log_fn
        self.kind = kind
        self.folder = KIND_FOLDER[kind]
        self.label = _kind_label(kind)

        self._mods = {}
        self._sync_running = False
        self._active_workers = set()
        self._rows = {}
        self._pending_rerender = False
        self._deleted = False
        self._summary_lbl = None
        self._resolve_worker = None

        self._nam = QNetworkAccessManager(self)
        self.icon_loader = IconLoader(self, nam=self._nam)
        try:
            self.icon_loader.icon_ready.connect(self._on_icon_ready)
        except Exception:
            pass

        self._build_ui()
        self._summary_lbl = self.summary
        self.rescan()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._cull_visible)
        QTimer.singleShot(0, self._ensure_resolved)

    def refresh_from_disk(self):
        try:
            if self._deleted:
                return
            self.rescan()
            self._ensure_resolved()
        except RuntimeError:
            pass

    def _ensure_resolved(self):
        try:
            if self._deleted:
                return
            if self._resolve_worker is not None:
                return
            unresolved = []
            for path, entry in self._mods.items():
                if entry.get("status") in ("", None, "unchecked"):
                    unresolved.append(path)
            if not unresolved:
                return

            for path in unresolved:
                entry = self._mods.get(path)
                if entry is not None:
                    entry["status"] = "checking"
            self._rerender()
            self._update_summary()

            paths = list(unresolved)
            mv = self.profile.version
            ld = (self.profile.loader or "vanilla").lower()
            kind = self.kind
            profile = self.profile

            def task(log, progress, progress_end):
                from integration import modrinth as _m
                result = _m.resolve_mods_parallel(
                    paths, mv, kind,
                    ld if kind == "mod" else None,
                    workers=LOOKUP_WORKERS)
                try:
                    m = getattr(profile, "mods_meta", {}) or {}
                    m.update(result)
                    profile.mods_meta = m
                    profile.save()
                except Exception:
                    pass
                return result

            w = Worker(task)
            w.log.connect(self.log_fn,
                          Qt.ConnectionType.QueuedConnection)
            self._track(w, on_done=self._on_resolved)
            self._resolve_worker = w
            w.start()
        except RuntimeError:
            pass

    def _on_resolved(self, result):
        try:
            if self._deleted:
                return
            self._resolve_worker = None
            if isinstance(result, dict):
                for path, entry in self._mods.items():
                    r = result.get(entry["filename"])
                    if not r:
                        continue
                    entry["project_id"] = (
                        r.get("project_id") or entry["project_id"])
                    entry["title"] = (
                        r.get("title") or entry["title"])
                    entry["author"] = (
                        r.get("author") or entry["author"])
                    entry["current_ver"] = (
                        r.get("version_number") or entry["current_ver"])
                    entry["latest_ver"] = (
                        r.get("latest_version") or entry["latest_ver"])
                    entry["url"] = (
                        r.get("latest_url") or entry["url"])
                    entry["target_name"] = (
                        r.get("latest_filename") or entry["target_name"])
                    entry["status"] = (
                        r.get("status") or entry["status"])
                    pid = entry.get("project_id")
                    if pid and entry.get("icon_pixmap") is None:
                        try:
                            self.icon_loader.request(pid)
                        except RuntimeError:
                            pass
            self._rerender()
            self._update_summary()
            QTimer.singleShot(0, self._ensure_resolved)
        except RuntimeError:
            pass

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)

        self.summary = QLabel("…")
        self.summary.setStyleSheet(
            f"color:{theme.GRAY};font-size:9pt;background:transparent")
        self.summary.setSizePolicy(QSizePolicy.Policy.Expanding,
                                   QSizePolicy.Policy.Preferred)
        top.addWidget(self.summary, 1)

        self.sync_all_btn = QPushButton(translate.t("btn.sync_all"))
        self.sync_all_btn.setMinimumWidth(160)
        self.sync_all_btn.setSizePolicy(QSizePolicy.Policy.Preferred,
                                        QSizePolicy.Policy.Fixed)
        self.sync_all_btn.setAutoDefault(False)
        self.sync_all_btn.setDefault(False)
        self.sync_all_btn.setStyleSheet(
            f"QPushButton{{background:{theme.ACCENT};"
            f"color:{theme.on_accent()};border:none;"
            f"padding:8px 20px;font-weight:bold;min-width:160px}}"
            f"QPushButton:hover{{background:{theme.ACCENT2}}}"
            f"QPushButton:disabled{{background:{theme.BG3};"
            f"color:{theme.GRAY}}}")
        self.sync_all_btn.clicked.connect(self.synchronize_all)
        top.addWidget(self.sync_all_btn)

        v.addLayout(top)

        self.list = QListWidget()
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection)
        self.list.setVerticalScrollMode(
            QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setIconSize(QSize(ICON_SIZE_ROW, ICON_SIZE_ROW))
        self.list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_ctx)
        self.list.setStyleSheet(
            f"QListWidget{{background:{theme.BG2};color:{theme.FG};"
            f"border:none;padding:0;outline:0}}"
            f"QListWidget::item{{padding:0;border:none}}"
            f"QListWidget::item:selected{{background:{theme.BG3};"
            f"border:none}}")
        self.list.verticalScrollBar().valueChanged.connect(
            self._cull_visible)
        v.addWidget(self.list, 1)

    def restyle(self):
        try:
            if self._deleted:
                return
            self.summary.setStyleSheet(
                f"color:{theme.GRAY};font-size:9pt;"
                f"background:transparent")
            self.sync_all_btn.setStyleSheet(
                f"QPushButton{{background:{theme.ACCENT};"
                f"color:{theme.on_accent()};border:none;"
                f"padding:8px 20px;font-weight:bold;min-width:160px}}"
                f"QPushButton:hover{{background:{theme.ACCENT2}}}"
                f"QPushButton:disabled{{background:{theme.BG3};"
                f"color:{theme.GRAY}}}")
            self._rerender()
        except RuntimeError:
            pass

    def _track(self, w, on_done=None):
        try:
            self._active_workers.add(w)
            if on_done is not None:
                w.done.connect(on_done, Qt.ConnectionType.QueuedConnection)
            w.finished.connect(
                lambda: self._active_workers.discard(w))
        except RuntimeError:
            pass

    def shutdown(self):
        try:
            if self._deleted:
                return
            self._deleted = True
            try:
                self.icon_loader.icon_ready.disconnect()
            except Exception:
                pass
            try:
                self.icon_loader.setParent(None)
                self.icon_loader.deleteLater()
            except Exception:
                pass
            self._pending_rerender = False
            for w in list(self._active_workers):
                try:
                    try:
                        w.log.disconnect()
                        w.done.disconnect()
                        w.progress.disconnect()
                        w.progress_end.disconnect()
                    except Exception:
                        pass
                    w.quit()
                    if not w.wait(200):
                        _leaked_threads.append(w)
                except Exception:
                    pass
            self._active_workers.clear()
            self._sync_running = False
        except RuntimeError:
            pass

    def closeEvent(self, event):
        try:
            self.shutdown()
        except Exception:
            pass
        super().closeEvent(event)

    def rescan(self):
        try:
            if self._deleted:
                return
            prev_icons = {
                p: e.get("icon_pixmap")
                for p, e in self._mods.items()
                if e.get("icon_pixmap") is not None
            }
            meta = getattr(self.profile, "mods_meta", {}) or {}
            self._mods = {}
            self._rows.clear()
            mods_dir = self.profile.dir / self.folder
            mods_dir.mkdir(parents=True, exist_ok=True)
            files = sorted(
                [f for f in mods_dir.iterdir()
                 if f.is_file() and f.suffix.lower() in (".jar", ".zip")],
                key=lambda f: f.name.lower())
            for f in files:
                key = str(f)
                m = meta.get(f.name, {}) or {}
                entry = {
                    "filename": f.name,
                    "project_id": m.get("project_id"),
                    "title": m.get("title") or f.stem,
                    "author": m.get("author", ""),
                    "current_ver": m.get("version_number", ""),
                    "latest_ver": m.get("latest_version", ""),
                    "url": m.get("latest_url", ""),
                    "target_name": m.get("latest_filename", f.name),
                    "status": m.get("status", "unchecked"),
                    "busy": False,
                    "icon_pixmap": prev_icons.get(key),
                }
                self._mods[key] = entry
            self._rerender()
            self._update_summary()
            for entry in self._mods.values():
                pid = entry.get("project_id")
                if pid and entry.get("icon_pixmap") is None:
                    try:
                        self.icon_loader.request(pid)
                    except RuntimeError:
                        break
        except RuntimeError:
            pass

    def synchronize_all(self):
        try:
            if self._deleted:
                return
            entries = [(p, m) for p, m in self._mods.items()
                       if not m["busy"]]
            if not entries:
                QMessageBox.information(
                    self, translate.t("control.nothing"),
                    translate.t("control.no_items", label=self.label))
                return
            if QMessageBox.question(
                self,
                translate.t("control.confirm_sync_title",
                            label=self.label),
                translate.t("control.confirm_sync",
                            n=len(entries), label=self.label,
                            version=self.profile.version),
            ) != QMessageBox.StandardButton.Yes:
                return

            self._sync_running = True
            for _, entry in entries:
                entry["busy"] = True
                if entry["status"] == "unchecked":
                    entry["status"] = "checking"
            self._rerender()
            self._update_summary()

            w = Worker(self._sync_all_task, entries)
            w.log.connect(self.log_fn,
                          Qt.ConnectionType.QueuedConnection)
            w.progress.connect(
                lambda *a: self._on_sync_progress(*a),
                Qt.ConnectionType.QueuedConnection)
            w.progress_end.connect(
                lambda: None, Qt.ConnectionType.QueuedConnection)
            self._track(w, on_done=self._sync_all_done)
            w.start()
        except RuntimeError:
            pass

    def _on_sync_progress(self, label, cur, total, extra, speed):
        try:
            if self._deleted:
                return
            self.summary.setText(f"{label} {cur}/{total}")
        except RuntimeError:
            pass

    def _sync_all_task(self, entries, log, progress, progress_end):
        mods_dir = self.profile.dir / self.folder
        loader = (self.profile.loader or "vanilla").lower()
        mc_version = self.profile.version
        kind = self.kind

        cleanup_total = len(entries)
        if cleanup_total:
            progress("cleanup", 0, cleanup_total, "", "")
        removed_paths = []
        for i, (path, entry) in enumerate(entries, 1):
            p = Path(path)
            if not p.exists():
                continue
            if not _verify_installed(p, mc_version, kind, loader):
                try:
                    p.unlink()
                    removed_paths.append(path)
                    log("warn", translate.t(
                        "console.removed_incompat",
                        name=entry["filename"], version=mc_version))
                except Exception as e:
                    log("error", translate.t(
                        "console.remove_failed",
                        name=entry["filename"], err=e))
            progress("cleanup", i, cleanup_total, entry["filename"], "")
        progress_end()

        for path in removed_paths:
            entry = self._mods.get(path)
            if entry is not None:
                entry["status"] = "removed"
                entry["busy"] = False

        remaining = [(p, e) for p, e in entries if Path(p).exists()]

        need_resolve = []
        for path, entry in remaining:
            if not entry.get("url") or not entry.get("project_id"):
                need_resolve.append((path, entry))

        if need_resolve:
            progress("resolving", 0, len(need_resolve), "", "")
            paths_only = [p for p, _ in need_resolve]
            try:
                from integration import modrinth as _m
                meta = _m.resolve_mods_parallel(
                    paths_only, mc_version, kind,
                    loader if kind == "mod" else None,
                    workers=LOOKUP_WORKERS)
                for path, entry in need_resolve:
                    r = meta.get(entry["filename"])
                    if not r:
                        entry["status"] = "error"
                        continue
                    entry["project_id"] = (
                        r.get("project_id") or entry["project_id"])
                    entry["title"] = (
                        r.get("title") or entry["title"])
                    entry["author"] = (
                        r.get("author") or entry["author"])
                    entry["current_ver"] = (
                        r.get("version_number") or entry["current_ver"])
                    entry["latest_ver"] = (
                        r.get("latest_version") or entry["latest_ver"])
                    entry["url"] = (
                        r.get("latest_url") or entry["url"])
                    entry["target_name"] = (
                        r.get("latest_filename") or entry["target_name"])
                    entry["status"] = (
                        r.get("status") or entry["status"])
            except Exception as e:
                log("error", str(e))
            progress_end()

        to_download = []
        for path, entry in remaining:
            if not entry.get("url") or not entry.get("target_name"):
                entry["busy"] = False
                if entry.get("status") == "update-available":
                    entry["status"] = "no-update-available"
                continue
            if (entry["current_ver"] == entry["latest_ver"]
                    and entry["current_ver"]):
                entry["status"] = "up-to-date"
                entry["busy"] = False
                continue
            to_download.append((path, entry))

        total = len(to_download)
        if not total:
            progress_end()
            return 0

        progress("syncing", 0, total, "", "")
        synced = 0
        done_count = 0

        def one_download(item):
            path, entry = item
            old = Path(path)
            target = mods_dir / entry["target_name"]
            tmp = target.with_suffix(target.suffix + ".part")
            log("info", translate.t(
                "console.installing", title=entry["title"]))
            try:
                with http.stream("GET", entry["url"]) as r:
                    r.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_bytes(65536):
                            f.write(chunk)
                if not _verify_installed(tmp, mc_version, kind, loader):
                    try:
                        tmp.unlink()
                    except Exception:
                        pass
                    entry["status"] = "no-update-available"
                    entry["busy"] = False
                    log("warn", translate.t(
                        "console.removed_incompat",
                        name=entry["target_name"], version=mc_version))
                    return False, entry
                if old.exists() and old.resolve() != target.resolve():
                    try:
                        old.unlink()
                    except Exception as e:
                        log("warn", str(e))
                tmp.replace(target)
                entry["status"] = "up-to-date"
                entry["current_ver"] = entry["latest_ver"]
                entry["filename"] = target.name
                entry["busy"] = False
                return True, entry
            except Exception as e:
                log("error", str(e))
                entry["status"] = "error"
                entry["busy"] = False
                try:
                    if tmp.exists():
                        tmp.unlink()
                except Exception:
                    pass
                return False, entry

        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as ex:
            futures = [ex.submit(one_download, it) for it in to_download]
            for fut in as_completed(futures):
                ok, entry = fut.result()
                if ok:
                    synced += 1
                done_count += 1
                progress("syncing", done_count, total,
                         entry["filename"], "")

        progress_end()
        return synced

    def _sync_all_done(self, synced):
        try:
            if self._deleted:
                return
            self._sync_running = False
            self._rerender()
            if synced is not None:
                self.log_fn("ok", translate.t(
                    "console.sync_done", n=synced, label=self.label))
            for entry in self._mods.values():
                pid = entry.get("project_id")
                if pid and entry.get("icon_pixmap") is None:
                    try:
                        self.icon_loader.request(pid)
                    except RuntimeError:
                        break
            self._persist_meta()
            self._update_summary()
        except RuntimeError:
            pass

    def _persist_meta(self):
        try:
            meta = {}
            for entry in self._mods.values():
                if entry.get("status") == "removed":
                    continue
                meta[entry["filename"]] = {
                    "project_id": entry.get("project_id"),
                    "title": entry.get("title", ""),
                    "author": entry.get("author", ""),
                    "version_number": entry.get("current_ver", ""),
                    "latest_version": entry.get("latest_ver", ""),
                    "latest_filename": entry.get("target_name", ""),
                    "latest_url": entry.get("url", ""),
                    "status": entry.get("status", "unchecked"),
                }
            self.profile.mods_meta = meta
            self.profile.save()
        except Exception:
            pass

    def _sync_selected(self):
        try:
            if self._deleted or self._sync_running:
                return
            items = self.list.selectedItems()
            if not items:
                return
            paths = self._sorted_paths()
            chosen = []
            for it in items:
                idx = self.list.row(it)
                if 0 <= idx < len(paths):
                    path = paths[idx]
                    entry = self._mods.get(path)
                    if entry and not entry["busy"]:
                        entry["busy"] = True
                        chosen.append((path, entry))
            if not chosen:
                return
            self._sync_running = True
            self._rerender()
            self._update_summary()

            w = Worker(self._sync_all_task, chosen)
            w.log.connect(self.log_fn,
                          Qt.ConnectionType.QueuedConnection)
            w.progress.connect(
                lambda *a: self._on_sync_progress(*a),
                Qt.ConnectionType.QueuedConnection)
            w.progress_end.connect(
                lambda: None, Qt.ConnectionType.QueuedConnection)
            self._track(w, on_done=self._sync_all_done)
            w.start()
        except RuntimeError:
            pass

    def _delete_selected(self):
        try:
            if self._deleted:
                return
            items = self.list.selectedItems()
            if not items:
                return
            paths = self._sorted_paths()
            targets = []
            for it in items:
                idx = self.list.row(it)
                if 0 <= idx < len(paths):
                    targets.append(paths[idx])
            if not targets:
                return
            if len(targets) == 1:
                entry = self._mods.get(targets[0])
                label = entry["title"] if entry else "?"
                msg = translate.t("control.confirm_delete_one",
                                  title=label)
            else:
                msg = translate.t("control.confirm_delete_many",
                                  n=len(targets), label=self.label)
            if QMessageBox.question(
                self,
                translate.t("control.confirm_delete_title",
                            label=self.label),
                msg,
            ) != QMessageBox.StandardButton.Yes:
                return
            for path in targets:
                entry = self._mods.get(path)
                try:
                    Path(path).unlink()
                    if entry:
                        self.log_fn("warn", translate.t(
                            "console.deleted", title=entry["title"]))
                except Exception as e:
                    self.log_fn("error", translate.t(
                        "console.delete_failed", err=e))
                    continue
                try:
                    if entry:
                        self.profile.mods_meta.pop(
                            entry["filename"], None)
                except Exception:
                    pass
                del self._mods[path]
            try:
                self.profile.save()
            except Exception:
                pass
            self._rerender()
            self._update_summary()
        except RuntimeError:
            pass

    def _on_ctx(self, pos):
        try:
            if self._deleted:
                return
            item = self.list.itemAt(pos)
            if item is None:
                return
            if not item.isSelected():
                self.list.clearSelection()
                item.setSelected(True)
            self.list.setCurrentItem(item)

            paths = self._sorted_paths()
            sel_count = len(self.list.selectedItems())
            row = self.list.row(item)
            primary_path = paths[row] if 0 <= row < len(paths) else None
            primary = self._mods.get(primary_path) if primary_path else None

            m = QMenu(self)
            m.setStyleSheet(
                f"QMenu{{background:{theme.BG2};color:{theme.FG};"
                f"border:none;padding:4px}}"
                f"QMenu::item{{padding:6px 20px 6px 12px}}"
                f"QMenu::item:selected{{background:{theme.BG3};"
                f"color:{theme.FG}}}"
                f"QMenu::item:disabled{{color:{theme.GRAY}}}"
                f"QMenu::separator{{height:1px;"
                f"background:{theme.BORDER};margin:4px 0}}")

            busy = self._sync_running
            sync_label = (translate.t("btn.sync_latest")
                          if sel_count == 1
                          else f"{translate.t('btn.sync_latest')} "
                               f"({sel_count})")
            sync_act = m.addAction(sync_label)
            sync_act.setEnabled(not busy)
            sync_act.triggered.connect(
                lambda _=False: self._sync_selected())

            if primary and primary.get("project_id"):
                pid = primary["project_id"]
                m.addAction(
                    translate.t("control.menu_open_modrinth"),
                    lambda pid=pid: QDesktopServices.openUrl(
                        QUrl(f"https://modrinth.com/"
                             f"{KIND_PROJECT_TYPE[self.kind]}/{pid}")))

            m.addSeparator()
            if primary_path:
                m.addAction(
                    translate.t("control.menu_reveal"),
                    lambda p=primary_path: self._reveal(p))

            m.addSeparator()
            del_label = (translate.t("btn.delete") if sel_count == 1
                         else f"{translate.t('btn.delete')} "
                              f"({sel_count})")
            del_act = m.addAction(del_label)
            del_act.triggered.connect(
                lambda _=False: self._delete_selected())

            m.exec(self.list.mapToGlobal(pos))
        except RuntimeError:
            pass

    def _reveal(self, path):
        try:
            if self._deleted:
                return
            p = Path(path)
            folder = p.parent
            if IS_WIN:
                subprocess.Popen(["explorer", "/select,", str(p)])
            elif IS_MAC:
                subprocess.Popen(["open", "-R", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            try:
                self.log_fn("error", translate.t(
                    "console.reveal_failed", err=e))
            except Exception:
                pass

    def _on_icon_ready(self, project_id, icon):
        try:
            if self._deleted:
                return
            pm = square_icon(icon, ICON_SIZE_ROW)
            if pm is None:
                return
            for path, entry in self._mods.items():
                if entry.get("project_id") == project_id:
                    entry["icon_pixmap"] = pm
                    row = self._rows.get(path)
                    if row is not None and hasattr(row, "_icon"):
                        row._icon.setPixmap(pm)
        except RuntimeError:
            pass

    def _update_summary(self):
        try:
            if self._deleted:
                return
            lbl = self._summary_lbl
            if lbl is None:
                return
            total = len(self._mods)
            if total == 0:
                lbl.setText(translate.t(
                    "control.summary_empty", label=self.label))
                return
            lbl.setText(translate.t(
                "control.summary_count",
                n=total, label=self.label))
        except RuntimeError:
            pass

    def _sorted_paths(self):
        return sorted(self._mods.keys(),
                      key=lambda p: self._mods[p]["filename"].lower())

    def _queue_rerender(self):
        try:
            if self._deleted:
                return
            if self._pending_rerender:
                return
            self._pending_rerender = True
            QTimer.singleShot(0, self._do_rerender)
        except RuntimeError:
            pass

    def _do_rerender(self):
        try:
            if self._deleted:
                return
            self._pending_rerender = False
            self._rerender()
        except RuntimeError:
            pass

    def _rerender(self):
        try:
            if self._deleted:
                return
            self.list.clear()
            self._rows.clear()
            paths = self._sorted_paths()
            self.list.setUpdatesEnabled(False)
            try:
                for path in paths:
                    it = QListWidgetItem()
                    it.setSizeHint(QSize(0, self.ROW_HEIGHT))
                    it.setData(Qt.ItemDataRole.UserRole, path)
                    self.list.addItem(it)
            finally:
                self.list.setUpdatesEnabled(True)
            QTimer.singleShot(0, self._cull_visible)
        except RuntimeError:
            pass

    def _cull_visible(self, *_):
        try:
            if self._deleted:
                return
            if not self.list.count():
                return
            vp = self.list.viewport().rect()
            if vp.height() <= 0:
                QTimer.singleShot(30, self._cull_visible)
                return
            first = self.list.indexAt(vp.topLeft()).row()
            last = self.list.indexAt(vp.bottomLeft()).row()
            if first < 0:
                first = 0
            if last < 0:
                last = self.list.count() - 1
            first = max(0, first - 1)
            last = min(self.list.count() - 1, last + 1)

            paths = self._sorted_paths()
            for path in list(self._rows.keys()):
                try:
                    idx = paths.index(path)
                except ValueError:
                    continue
                if idx < first or idx > last:
                    it = self.list.item(idx)
                    if it is not None:
                        self.list.removeItemWidget(it)
                    w = self._rows.pop(path, None)
                    if w is not None:
                        w.deleteLater()

            for idx in range(first, last + 1):
                path = paths[idx]
                if path in self._rows:
                    continue
                entry = self._mods[path]
                row = self._make_row(path, entry)
                it = self.list.item(idx)
                if it is not None:
                    self.list.setItemWidget(it, row)
                    self._rows[path] = row
        except RuntimeError:
            pass

    def _make_row(self, path, entry):
        row = QWidget()
        row.setStyleSheet(
            f"QWidget{{background:transparent;border:none;"
            f"border-bottom:1px solid {theme.BG};}}")
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(10)

        ic = QLabel()
        ic.setFixedSize(ICON_SIZE_ROW, ICON_SIZE_ROW)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cached = entry.get("icon_pixmap")
        if cached is not None and not cached.isNull():
            ic.setPixmap(cached)
        else:
            ph = make_placeholder(ICON_SIZE_ROW).pixmap(
                ICON_SIZE_ROW, ICON_SIZE_ROW)
            ic.setPixmap(square_icon_pixmap(ph, ICON_SIZE_ROW))

        ic_host = QWidget()
        ic_host.setStyleSheet("background:transparent;border:none")
        ic_host.setFixedWidth(ICON_SIZE_ROW)
        ic_col = QVBoxLayout(ic_host)
        ic_col.setContentsMargins(0, 0, 0, 0)
        ic_col.setSpacing(0)
        ic_col.addStretch(1)
        ic_col.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)
        ic_col.addStretch(1)
        h.addWidget(ic_host, 0)
        row._icon = ic

        col = QVBoxLayout()
        col.setSpacing(1)
        title = QLabel(entry["title"] or entry["filename"])
        title.setStyleSheet(
            f"color:{theme.FG};font-weight:bold;font-size:10pt;"
            f"background:transparent")
        col.addWidget(title)

        ver = entry["current_ver"] or ""
        fn = entry["filename"] or ""
        if ver:
            sub_text = translate.t("control.row_filename_ver",
                                   filename=fn, ver=ver)
        else:
            sub_text = translate.t("control.row_filename", filename=fn)
        sub = QLabel(sub_text)
        sub.setStyleSheet(
            f"color:{theme.GRAY};font-size:9pt;background:transparent")
        col.addWidget(sub)
        h.addLayout(col, 1)

        badge_text, badge_color = self._badge_for_status(entry["status"])
        if badge_text:
            badge = QLabel(badge_text)
            badge.setStyleSheet(
                f"color:{badge_color};font-size:8pt;font-weight:bold;"
                f"background:transparent")
            h.addWidget(badge)

        return row

    def _badge_for_status(self, status):
        if status == "update-available":
            return translate.t("control.badge_update"), theme.ACCENT
        if status == "up-to-date":
            return translate.t("control.badge_uptodate"), theme.FG
        if status == "checking":
            return translate.t("control.badge_checking"), theme.GRAY
        if status == "no-update-available":
            return translate.t("control.badge_no_compat"), theme.GRAY
        if status == "not-on-modrinth":
            return translate.t("control.badge_not_modrinth"), theme.GRAY
        if status == "removed":
            return translate.t("control.badge_removed"), theme.RED
        if status == "error":
            return translate.t("control.badge_error"), theme.RED
        return translate.t("control.badge_unchecked"), theme.GRAY
