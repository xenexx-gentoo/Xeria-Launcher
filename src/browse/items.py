import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton, QStackedLayout, QWidget

from browse.base import BrowseBase
from browse.control import ControlTab
from core import theme, translate
from integration import modrinth
from ui.helpers import glass_accent, glass_soft

KIND_CONFIG = {
    "mod": {
        "title_key": "title.mods",
        "search_key": "search.mods",
        "icon": "system-software-install",
        "folder": "mods",
        "project_type": "mod",
        "vanilla_warning": True,
    },
    "resourcepack": {
        "title_key": "title.resourcepacks",
        "search_key": "search.resourcepacks",
        "icon": "preferences-desktop-theme",
        "folder": "resourcepacks",
        "project_type": "resourcepack",
        "vanilla_warning": False,
    },
    "shader": {
        "title_key": "title.shaders",
        "search_key": "search.shaders",
        "icon": "video-display",
        "folder": "shaderpacks",
        "project_type": "shader",
        "vanilla_warning": True,
    },
}


class ItemsDialog(BrowseBase):
    def __init__(self, parent, profile, log_fn, kind):
        self._kind = kind
        cfg = KIND_CONFIG[kind]
        super().__init__(parent, profile, log_fn)
        self.setWindowTitle(f"{translate.t(cfg['title_key'])} - {profile.name}")

        self.head_row.addStretch()

        self.btn_search = QPushButton(translate.t("tab.search"))
        self.btn_control = QPushButton(translate.t("tab.control"))

        for btn in (self.btn_search, self.btn_control):
            btn.setFixedHeight(28)
            btn.setMinimumWidth(90)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.head_row.addWidget(btn)

        self.btn_search.clicked.connect(lambda: self._switch_tab(0))
        self.btn_control.clicked.connect(lambda: self._switch_tab(1))

        self.control_tab = ControlTab(self, profile, log_fn, kind)

        self.mode_container = QWidget()
        self.mode_container.setStyleSheet("background:transparent;")
        self.mode_stack = QStackedLayout(self.mode_container)
        self.mode_stack.setContentsMargins(0, 0, 0, 0)
        self.mode_stack.setSpacing(0)

        self.mode_stack.addWidget(self.search_body)
        self.mode_stack.addWidget(self.control_tab)

        self.main_layout.insertWidget(
            self.main_layout.count() - 1, self.mode_container, 1
        )

        self._switch_tab(0)
        self.install_finished.connect(self._on_install_finished)

    def _switch_tab(self, index):
        self.mode_stack.setCurrentIndex(index)
        self.search.setVisible(index == 0)
        self.detail.setVisible(index == 0)
        self.bottom_widget.setVisible(index == 0)

        if index == 1:
            try:
                self.control_tab.refresh_from_disk()
            except Exception:  # noqa: BLE001, S110
                pass

        self._update_toggle_styles()

    def _update_toggle_styles(self):
        active = (
            f"QPushButton{{background:{glass_accent(180)};"
            f"color:{theme.accent_text()};"
            f"padding:0 16px;border-radius:6px;border:none;"
            f"font-family:'{theme.UI_FONT}';font-size:9pt;"
            f"font-weight:400;outline:none;}}"
        )
        inactive = (
            f"QPushButton{{background:transparent;color:{theme.GRAY};"
            f"padding:0 16px;border-radius:6px;border:none;"
            f"font-family:'{theme.UI_FONT}';font-size:9pt;outline:none;}}"
            f"QPushButton:hover{{background:{glass_soft(80)};"
            f"color:{theme.FG};}}"
        )
        is_search = self.mode_stack.currentIndex() == 0
        self.btn_search.setStyleSheet(active if is_search else inactive)
        self.btn_control.setStyleSheet(inactive if is_search else active)

    def window_title(self):
        return translate.t(KIND_CONFIG[self._kind]["title_key"])

    def search_placeholder(self):
        return translate.t(KIND_CONFIG[self._kind]["search_key"])

    def header_icon(self):
        return KIND_CONFIG[self._kind]["icon"]

    def vanilla_warning(self):
        if not KIND_CONFIG[self._kind]["vanilla_warning"]:
            return ""
        return translate.t("warn.vanilla_mods")

    def folder_name(self):
        return KIND_CONFIG[self._kind]["folder"]

    def _search_url(self, query, offset=0):
        project_type = KIND_CONFIG[self._kind]["project_type"]
        facets = [[f"project_type:{project_type}"]]
        if self._kind == "mod":
            loader = (self.profile.loader or "vanilla").lower()
            if loader and loader != "vanilla":
                facets.append([f"categories:{loader}"])
        if self.profile.version:
            facets.append([f"versions:{self.profile.version}"])
        return (
            "https://api.modrinth.com/v2/search",
            {
                "query": query,
                "limit": self.PAGE_SIZE,
                "offset": offset,
                "facets": json.dumps(facets),
            },
        )

    def pick_download(self, hit):
        loader = None
        if self._kind == "mod":
            loader = (self.profile.loader or "vanilla").lower()
        return modrinth.pick_file(
            hit["id"],
            self.profile.version,
            KIND_CONFIG[self._kind]["project_type"],
            loader,
        )

    def _on_install_finished(self, path):
        try:
            self.control_tab.refresh_from_disk()
        except Exception as e:  # noqa: BLE001
            try:
                self.log_fn("error", str(e))
            except Exception:  # noqa: BLE001, S110
                pass

    def closeEvent(self, event):
        try:
            self.control_tab.shutdown()
        except Exception:  # noqa: BLE001, S110
            pass
        super().closeEvent(event)
