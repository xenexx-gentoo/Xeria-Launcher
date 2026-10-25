from PyQt6.QtWidgets import QMessageBox

from core import translate
from integration import modrinth
from browse.base import BrowseBase


class ModpackSearchDialog(BrowseBase):
    DEFAULT_QUERY = "fabulously optimized"

    def __init__(self, parent, log_fn=None):
        self.result = None
        super().__init__(
            parent, _DummyProfile(),
            log_fn or (lambda t, m: None))
        self.setWindowTitle(translate.t("title.modpacks"))
        if not self.search.text():
            self.search.setText(self.DEFAULT_QUERY)

    def window_title(self):
        return translate.t("title.modpacks")

    def search_placeholder(self):
        return translate.t("search.modpacks")

    def header_icon(self):
        return "package-x-generic"

    def folder_name(self):
        return "modpacks"

    def _search_url(self, query):
        return ("https://api.modrinth.com/v2/search",
                {"query": query, "limit": 30,
                 "facets": '[[\"project_type:modpack\"]]'})

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
                self, translate.t("warn.wait"),
                translate.t("warn.select_row"))
            return
        self.result = hit
        self.accept()


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
