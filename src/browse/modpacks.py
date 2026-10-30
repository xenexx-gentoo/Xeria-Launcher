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
    KNOWN_LOADERS = ("fabric", "quilt", "forge", "neoforge")

    def __init__(self, parent, log_fn=None):
        self.result = None
        self._mc_version = ""
        self._forced_loader = self.KNOWN_LOADERS[0]
        super().__init__(parent, _DummyProfile(), log_fn or (lambda t, m: None))
        self.setWindowTitle(translate.t("title.modpacks"))
        self._build_version_picker()
        self.head_row.addStretch()
        self.main_layout.insertWidget(
            self.main_layout.count() - 1, self.search_body, 1
        )
        if not self.search.text():
            self.search.setText(self.DEFAULT_QUERY)

    def _build_version_picker(self):
        bar = QHBoxLayout()
        bar.setSpacing(8)

        ver_lbl = QLabel(translate.t("modpack.target_version"))
        ver_lbl.setStyleSheet(
            f"color:{theme.FG};font-size:10pt;background:transparent"
        )
        bar.addWidget(ver_lbl)

        self._version_box = _NoWheelCombo()
        self._version_box.setStyleSheet(s_combo())
        self._version_box.addItem(translate.t("modpack.any_version"), "")
        bar.addWidget(self._version_box)

        lo_lbl = QLabel(translate.t("modpack.loader"))
        lo_lbl.setStyleSheet(
            f"color:{theme.FG};font-size:10pt;"
            f"background:transparent;padding-left:12px"
        )
        bar.addWidget(lo_lbl)

        self._loader_box = _NoWheelCombo()
        self._loader_box.setStyleSheet(s_combo())
        # No "any" entry, no vanilla — a loader is always required.
        for key in self.KNOWN_LOADERS:
            self._loader_box.addItem(translate.t(f"loader.{key}"), key)
        idx = self._loader_box.findData(self._forced_loader)
        if idx >= 0:
            self._loader_box.setCurrentIndex(idx)
        bar.addWidget(self._loader_box)

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
        new_v = self._version_box.currentData() or ""
        if new_v == self._mc_version:
            return
        self._mc_version = new_v
        q = self.search.text().strip()
        if q:
            self._last_query = ""
            self.search_now()

    def _on_loader_changed(self, _idx):
        new_l = self._loader_box.currentData() or ""
        if not new_l or new_l == self._forced_loader:
            return
        self._forced_loader = new_l
        q = self.search.text().strip()
        if not q:
            return
        self._last_query = ""
        self.search_now()

    def _search_url(self, query, offset=0):
        facets = [["project_type:modpack"]]
        if self._mc_version:
            facets.append([f"versions:{self._mc_version}"])
        # Loader is always set — vanilla-only packs can never match.
        facets.append([f"categories:{self._forced_loader}"])
        return (
            "https://api.modrinth.com/v2/search",
            {
                "query": query,
                "limit": self.PAGE_SIZE,
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

    def row_subtitle_color(self):
        return theme.ACCENT

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
        # Always a concrete loader now; "" is never returned.
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
