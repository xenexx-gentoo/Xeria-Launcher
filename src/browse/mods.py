import json

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTabWidget

from core import theme
from core import translate
from integration import modrinth
from browse.base import BrowseBase
from browse.control import ControlTab


class ModsSearchTab(BrowseBase):
    def window_title(self):
        return translate.t("title.mods")

    def search_placeholder(self):
        return translate.t("search.mods")

    def header_icon(self):
        return "system-software-install"

    def vanilla_warning(self):
        return translate.t("warn.vanilla_mods")

    def folder_name(self):
        return "mods"

    def _search_url(self, query):
        facets = [["project_type:mod"]]
        loader = (self.profile.loader or "vanilla").lower()
        if loader and loader != "vanilla":
            facets.append([f"categories:{loader}"])
        if self.profile.version:
            facets.append([f"versions:{self.profile.version}"])
        return ("https://api.modrinth.com/v2/search",
                {"query": query, "limit": 30,
                 "facets": json.dumps(facets)})

    def pick_download(self, hit):
        loader = (self.profile.loader or "vanilla").lower()
        return modrinth.pick_file(
            hit["id"], self.profile.version, "mod", loader)


class ModsDialog(QDialog):
    def __init__(self, parent, profile, log_fn):
        super().__init__(parent)
        self.profile = profile
        self.log_fn = log_fn
        self.setWindowTitle(
            f"{translate.t('title.mods')} — {profile.name}")
        self.resize(1080, 700)
        self.setMinimumSize(760, 500)
        self.setStyleSheet(
            f"QDialog{{background:{theme.BG};border:none}}")

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)

        self.tabs = QTabWidget(self)
        self.tabs.setStyleSheet(
            f"QTabWidget::pane{{border:none;background:{theme.BG}}}"
            f"QTabBar::tab{{background:transparent;color:{theme.FG};"
            f"padding:8px 14px;border:none;"
            f"font-family:'{theme.UI_FONT}';font-size:10pt}}"
            f"QTabBar::tab:selected{{color:{theme.FG};"
            f"border-bottom:1px solid {theme.ACCENT}}}")
        v.addWidget(self.tabs, 1)

        self.search_tab = ModsSearchTab(self, profile, log_fn)
        self.tabs.addTab(self.search_tab, translate.t("tab.search"))

        self.control_tab = ControlTab(self, profile, log_fn, "mod")
        self.tabs.addTab(self.control_tab, translate.t("tab.control"))

        self.search_tab.install_finished.connect(self._on_install_finished)
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _on_install_finished(self, path):
        try:
            self.control_tab.refresh_from_disk()
        except Exception as e:
            try:
                self.log_fn("error", str(e))
            except Exception:
                pass

    def _on_tab_changed(self, idx):
        if idx == 1:
            try:
                self.control_tab.refresh_from_disk()
            except Exception:
                pass

    def closeEvent(self, event):
        try:
            self.control_tab.shutdown()
        except Exception:
            pass
        try:
            self.search_tab.closeEvent(event)
        except Exception:
            super().closeEvent(event)
