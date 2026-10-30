import json

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QListWidgetItem

from core import theme
from core.paths import MC_ROOT
from instances.profile import Profile
from ui.loader_icons import loader_icon_sync, fetch_loader_icon


def load_profiles_for_window(win):
    """Populate win.plist with one _InstanceRow per profile.

    Reads Profile.load_all() for profiles stored under PROFILES_DIR,
    plus any non-LabyMod, non-loader Minecraft version directories
    found under MC_ROOT/versions. LabyMod profiles are added
    separately by ui.labymod_builder.
    """
    from ui.main_window import _InstanceRow

    versions_dir = MC_ROOT / "versions"

    win.plist.blockSignals(True)
    win.plist.clear()
    win.plist.setSpacing(win.ROW_GAP)

    win.plist.setStyleSheet(
        f"QListWidget{{background:transparent;color:{theme.FG};"
        f"padding:0;border:none;}}"
        f"QListWidget::item{{padding:0px;margin:0px;border:none;}}"
    )

    win._row_map = []
    win._row_widgets = {}

    win.profiles = Profile.load_all()
    existing_names = {p.name for p in win.profiles}

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
        for v_dir in versions_dir.iterdir():
            if not v_dir.is_dir():
                continue

            name_lower = v_dir.name.lower()

            if ("fabric" in name_lower or
                    "quilt" in name_lower or
                    "forge" in name_lower):
                continue

            if v_dir.name in parents:
                continue

            if "labymod" in name_lower:
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
            win.profiles.append(p)

    for p in win.profiles:
        it = QListWidgetItem()
        it.setSizeHint(QSize(0, win.ROW_HEIGHT))

        loader = (p.loader or "vanilla").lower()
        icon = loader_icon_sync(loader)
        if not icon:
            icon = QIcon.fromTheme("applications-games")

        folder_name = (p._external_dir.name
                       if p._external_dir else p.version)
        row = _InstanceRow(p.name, p.version, folder_name, icon)

        win.plist.addItem(it)
        win.plist.setItemWidget(it, row)
        win._row_map.append(p)
        win._row_widgets[p.name] = row

    win.plist.blockSignals(False)

    for p in win.profiles:
        loader = (p.loader or "vanilla").lower()
        if loader_icon_sync(loader) is None:
            fetch_loader_icon(
                loader,
                lambda ic, name=loader:
                    win._apply_loader_icon(name, ic))

    if win.profiles:
        win.plist.setCurrentRow(0)
    else:
        win.current_profile = None
        win._update_card()
