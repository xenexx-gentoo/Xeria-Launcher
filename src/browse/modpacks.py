import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
)

from browse.base import BrowseBase
from core import theme, translate
from core.paths import MANIFEST_URL
from integration import modrinth
from integration import net as http
from ui.helpers import s_combo


class _NoWheelCombo(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        event.ignore()


class ModpackSearchDialog(BrowseBase):
    DEFAULT_QUERY = "fabulously optimized"

    def __init__(self, parent, log_fn=None):
        self.result = None
        self._mc_version = ""
        self._forced_loader = "pack"
        super().__init__(parent, _DummyProfile(), log_fn or (lambda t, m: None))
        self.setWindowTitle(translate.t("title.modpacks"))
        self._build_version_picker()
        self.list.currentRowChanged.connect(self._on_pack_row_changed)
        if not self.search.text():
            self.search.setText(self.DEFAULT_QUERY)

    def _build_version_picker(self):
        bar = QHBoxLayout()
        bar.setSpacing(8)

        ver_lbl = QLabel(translate.t("modpack.target_version"))
        ver_lbl.setStyleSheet(f"color:{theme.FG};font-size:10pt;background:transparent")
        bar.addWidget(ver_lbl)

        self._version_box = _NoWheelCombo()
        self._version_box.setStyleSheet(s_combo())
        self._version_box.addItem(translate.t("modpack.any_version"), "")
        bar.addWidget(self._version_box)

        lo_lbl = QLabel(translate.t("modpack.loader"))
        lo_lbl.setStyleSheet(
            f"color:{theme.FG};font-size:10pt;background:transparent;padding-left:12px"
        )
        bar.addWidget(lo_lbl)

        self._loader_box = _NoWheelCombo()
        self._loader_box.setStyleSheet(s_combo())
        self._loader_box.addItem(translate.t("modpack.loader_pack"), "pack")
        for key in ("fabric", "quilt", "forge", "neoforge", "vanilla"):
            self._loader_box.addItem(translate.t(f"loader.{key}"), key)
        bar.addWidget(self._loader_box)

        self._declared_lbl = QLabel(translate.t("modpack.declared_loader") + ": —")
        self._declared_lbl.setStyleSheet(
            f"color:{theme.GRAY};font-size:10pt;background:transparent;"
            f"padding-left:12px"
        )
        bar.addWidget(self._declared_lbl)

        bar.addStretch(1)

        self._version_box.currentIndexChanged.connect(self._on_mc_version_changed)
        self._loader_box.currentIndexChanged.connect(self._on_loader_changed)

        self.layout().insertLayout(2, bar)
        self._populate_mc_versions()

    def _populate_mc_versions(self):
        def task(log, progress, progress_end):
            r = http.get(MANIFEST_URL)
            r.raise_for_status()
            d = r.json()
            out = []
            latest_id = (d.get("latest") or {}).get("release", "")
            for v in d.get("versions", []):
                if v.get("type") != "release":
                    continue
                if v.get("id") == latest_id:
                    out.insert(0, v["id"])
                else:
                    out.append(v["id"])
            return out

        from core.worker import Worker

        w = Worker(task)
        w.log.connect(self._log, Qt.ConnectionType.QueuedConnection)
        w.done.connect(self._on_mc_versions_ready, Qt.ConnectionType.QueuedConnection)
        self._versions_worker = w
        w.start()

    def _on_mc_versions_ready(self, versions):
        if not versions:
            return
        cur = self._version_box.currentData()
        self._version_box.blockSignals(True)
        self._version_box.clear()
        self._version_box.addItem(translate.t("modpack.any_version"), "")
        for v in versions:
            self._version_box.addItem(v, v)
        idx = self._version_box.findData(cur)
        if idx >= 0:
            self._version_box.setCurrentIndex(idx)
        self._version_box.blockSignals(False)

    def _on_mc_version_changed(self, _idx):
        self._mc_version = self._version_box.currentData() or ""
        q = self.search.text().strip()
        if q:
            self._last_query = ""
            self.search_now()

    def _on_loader_changed(self, _idx):
        self._forced_loader = self._loader_box.currentData() or "pack"

    def _on_pack_row_changed(self, row):
        if row < 0 or row >= len(self.results_data):
            self._declared_lbl.setText(translate.t("modpack.declared_loader") + ": —")
            return
        hit = self.results_data[row]
        pid = hit.get("id") or hit.get("project_id")
        if not pid:
            self._declared_lbl.setText(translate.t("modpack.declared_loader") + ": —")
            return
        self._load_declared_loader(pid)

    def _load_declared_loader(self, project_id):
        self._declared_lbl.setText(translate.t("modpack.declared_loader") + ": …")

        def task(log, progress, progress_end):
            return modrinth.list_versions(project_id)

        from core.worker import Worker

        w = Worker(task)
        w.log.connect(self._log, Qt.ConnectionType.QueuedConnection)
        w.done.connect(
            lambda vs, p=project_id: self._on_declared_ready(p, vs),
            Qt.ConnectionType.QueuedConnection,
        )
        self._declared_worker = w
        w.start()

    def _on_declared_ready(self, project_id, versions):
        if self._deleted:
            return
        row = self.list.currentRow()
        if row < 0 or row >= len(self.results_data):
            return
        hit = self.results_data[row]
        if (hit.get("id") or hit.get("project_id")) != project_id:
            return
        names = set()
        for v in versions or []:
            for f in v.get("files", []):
                if not f["filename"].endswith(".mrpack"):
                    continue
                for loader_name in v.get("loaders") or []:
                    names.add(loader_name)
        if not names:
            self._declared_lbl.setText(translate.t("modpack.declared_loader") + ": —")
            return
        display = ", ".join(sorted(n.capitalize() for n in names))
        self._declared_lbl.setText(
            f"{translate.t('modpack.declared_loader')}: {display}"
        )

    def _search_url(self, query, offset=0):
        facets = [["project_type:modpack"]]
        if self._mc_version:
            facets.append([f"versions:{self._mc_version}"])
        return (
            "https://api.modrinth.com/v2/search",
            {
                "query": query,
                "limit": self.PAGE_SIZE * 10,
                "offset": offset,
                "facets": json.dumps(facets),
            },
        )

    def window_title(self):
        return translate.t("title.modpacks")

    def search_placeholder(self):
        return translate.t("search.modpacks")

    def header_icon(self):
        return "package-x-generic"

    def folder_name(self):
        return "modpacks"

    def pick_download(self, hit):
        picked = modrinth.pick_modpack_file(hit["id"])
        if not picked:
            return None
        url, filename, _ver = picked
        return url, filename

    def row_subtitle(self, hit):
        return translate.t("browse.meta_modpack", author=hit["author"])

    def install_selected(self):
        hit = self._selected_hit()
        if hit is None:
            QMessageBox.information(
                self, translate.t("warn.wait"), translate.t("warn.select_row")
            )
            return
        self.result = hit
        self.accept()

    def selected_version(self):
        return self._mc_version

    def selected_loader(self):
        return self._forced_loader


class _DummyProfile:
    name = "(modpacks)"
    loader = "vanilla"
    version = ""

    class _D:
        def __truediv__(self, other):
            return self

        def exists(self):
            return False

        def iterdir(self):
            return iter(())

    dir = _D()
