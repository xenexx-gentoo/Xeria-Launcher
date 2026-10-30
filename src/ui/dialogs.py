import json as _json
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core import theme, translate
from core.java import best_java, find_javas
from core.paths import IS_WIN, SETTINGS_FILE
from core.settings import DEFAULTS
from ui.helpers import (
    TranslucentDialog,
    dialog_shell_style,
    s_btn,
    s_btn_accent,
    s_combo,
    s_entry,
    s_tabs,
    s_textedit,
)


class _EscCloseFilter(QObject):
    def __init__(self, dialog, field):
        super().__init__(dialog)
        self._dialog = dialog
        self._field = field

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            if self._field.text():
                self._field.clear()
            else:
                self._dialog.reject()
            return True
        return super().eventFilter(obj, event)


def fade_in(dialog, duration=120):
    effect = QGraphicsOpacityEffect(dialog)
    effect.setOpacity(0.0)
    dialog.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", dialog)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _cleanup():
        dialog.setGraphicsEffect(None)

    anim.finished.connect(_cleanup)
    anim.start()
    dialog._fade_anim = anim


class ChooseInstallDialog(TranslucentDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.choice = None
        self.jar_path = None
        self.preset_choice = None

        self.setWindowTitle(translate.t("dialog.add_title"))
        self.setFixedSize(520, 480)
        self.setSizeGripEnabled(False)
        self.setStyleSheet(dialog_shell_style())

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)

        title = QLabel(translate.t("dialog.add_title"))
        title.setStyleSheet(
            f"background:transparent;color:{theme.FG};"
            f"font-size:14pt;font-weight:bold;"
            f"font-family:'{theme.UI_FONT}'"
        )
        v.addWidget(title)

        subtitle = QLabel(translate.t("dialog.add_sub"))
        subtitle.setStyleSheet(
            f"background:transparent;color:{theme.GRAY};"
            f"font-size:9pt;font-family:'{theme.UI_FONT}'"
        )
        v.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.setStyleSheet(
            f"QTabWidget::pane{{border:none;background:transparent;"
            f"outline:none;}}"
            f"QTabBar::tab{{background:transparent;color:{theme.FG};"
            f"padding:8px 14px;border:none;outline:none;"
            f"font-family:'{theme.UI_FONT}';font-size:10pt}}"
            f"QTabBar::tab:focus{{outline:none;}}"
            f"QTabBar::tab:selected{{color:{theme.FG};"
            f"border-bottom:1px solid {theme.ACCENT};outline:none;}}"
        )
        v.addWidget(self.tabs, 1)

        t1 = QWidget()
        g1 = QVBoxLayout(t1)
        g1.setContentsMargins(0, 10, 0, 0)
        g1.setSpacing(6)

        for label_key, sub_key, key, accent in (
            ("dialog.modrinth", "dialog.modrinth_sub", "modrinth", True),
            ("dialog.blank", "dialog.blank_sub", "blank", False),
            ("dialog.local", "dialog.local_sub", "local", False),
        ):
            btn = QPushButton(translate.t(label_key))
            btn.setToolTip(translate.t(sub_key))
            btn.setStyleSheet(
                s_btn_accent() if accent else s_btn(theme.BG3, theme.FG, theme.BG2)
            )
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda checked=False, k=key: self._pick(k))
            g1.addWidget(btn)
        g1.addStretch()
        self.tabs.addTab(t1, "Standard")

        t2 = QWidget()
        g2 = QVBoxLayout(t2)
        g2.setContentsMargins(0, 10, 0, 0)
        g2.setSpacing(6)

        lbl2 = QLabel("Quick install .jar-based clients:")
        lbl2.setStyleSheet(f"color:{theme.GRAY}; font-size:9pt;")
        g2.addWidget(lbl2)

        for preset_name, key in (("LabyMod 4", "labymod"),):
            btn = QPushButton(preset_name)
            btn.setStyleSheet(s_btn(theme.BG3, theme.FG, theme.BG2))
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda checked=False, k=key: self._pick_preset(k))
            g2.addWidget(btn)
        g2.addStretch()
        self.tabs.addTab(t2, "Presets")

        t3 = QWidget()
        g3 = QVBoxLayout(t3)
        g3.setContentsMargins(0, 10, 0, 0)
        g3.setSpacing(10)

        lbl3 = QLabel(
            "Manually select an installer `.jar` (e.g., labymod4-installer.jar)."
        )
        lbl3.setStyleSheet(f"color:{theme.GRAY}; font-size:9pt;")
        lbl3.setWordWrap(True)
        g3.addWidget(lbl3)

        self.jar_input = QLineEdit()
        self.jar_input.setPlaceholderText("Path to .jar...")
        self.jar_input.setStyleSheet(s_entry())
        self.jar_input.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        g3.addWidget(self.jar_input)

        btn_browse = QPushButton("Browse for .jar...")
        btn_browse.setStyleSheet(s_btn(theme.BG3, theme.FG, theme.BG2))
        btn_browse.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_browse.clicked.connect(self._browse_jar)
        g3.addWidget(btn_browse)

        btn_run = QPushButton("Extract and Install")
        btn_run.setStyleSheet(s_btn_accent())
        btn_run.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_run.clicked.connect(self._pick_jar)
        g3.addWidget(btn_run)

        g3.addStretch()
        self.tabs.addTab(t3, "Advanced")

        for _lbl in self.findChildren(QLabel):
            _lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            _lbl.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        for _btn in self.findChildren(QPushButton):
            _btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        fade_in(self)

    def _browse_jar(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Installer .jar",
            str(Path.home()),
            "Java Archives (*.jar);;All Files (*)",
        )
        if path:
            self.jar_input.setText(path)

    def _pick(self, c):
        self.choice = c
        self.accept()

    def _pick_preset(self, key):
        self.preset_choice = key
        self.choice = "preset"
        self.accept()

    def _pick_jar(self):
        path = self.jar_input.text().strip()
        if not path or not Path(path).exists():
            QMessageBox.warning(
                self, "Invalid File", "Please select a valid .jar file."
            )
            return
        self.jar_path = path
        self.choice = "jar"
        self.accept()


class ProfileDialog(TranslucentDialog):
    def __init__(self, parent, releases, settings, profile=None):
        super().__init__(parent)
        self.settings = settings
        self.profile = profile
        self.is_new = profile is None
        self.setWindowTitle(
            translate.t("dialog.profile_new")
            if self.is_new
            else translate.t("dialog.profile_edit", name=profile.name)
        )
        self.setFixedSize(700, 640)
        self.setSizeGripEnabled(False)
        self.setStyleSheet(dialog_shell_style())

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(2000)
        self._save_timer.timeout.connect(self._flush)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)
        self.tabs = QTabWidget(self)
        self.tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.setStyleSheet(s_tabs())
        v.addWidget(self.tabs, 1)

        t1 = QWidget()
        g1 = QGridLayout(t1)
        g1.setContentsMargins(14, 14, 14, 14)
        g1.setSpacing(8)
        g1.addWidget(QLabel(translate.t("dialog.name")), 0, 0)
        self.name = QLineEdit(profile.name if profile else "My Instance")
        self.name.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.name.setStyleSheet(s_entry())
        g1.addWidget(self.name, 0, 1)
        g1.addWidget(QLabel(translate.t("dialog.version")), 1, 0)
        self.ver = QComboBox()
        self.ver.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ver.setStyleSheet(s_combo())
        ids = [x["id"] for x in releases]
        self.ver.addItems(ids)
        if profile and profile.version in ids:
            self.ver.setCurrentText(profile.version)
        g1.addWidget(self.ver, 1, 1)
        g1.addWidget(QLabel(translate.t("dialog.loader")), 2, 0)
        self.loader = QComboBox()
        self.loader.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.loader.setStyleSheet(s_combo())
        for k in ("vanilla", "fabric", "forge", "neoforge", "quilt"):
            self.loader.addItem(translate.t(f"loader.{k}"), k)
        if profile:
            idx = self.loader.findData(profile.loader)
            if idx >= 0:
                self.loader.setCurrentIndex(idx)
        g1.addWidget(self.loader, 2, 1)
        g1.addWidget(QLabel(translate.t("dialog.ram")), 3, 0)
        self.ram = QComboBox()
        self.ram.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ram.setStyleSheet(s_combo())
        for label, val in (
            ("2 GB", "2"),
            ("4 GB", "4"),
            ("8 GB", "8"),
            ("16 GB", "16"),
        ):
            self.ram.addItem(label, val)
        cur_gb = str(int(profile.ram)) if profile else "4"
        idx = self.ram.findData(cur_gb)
        if idx >= 0:
            self.ram.setCurrentIndex(idx)
        g1.addWidget(self.ram, 3, 1)
        g1.setRowStretch(4, 1)
        self.tabs.addTab(t1, translate.t("dialog.tab_basic"))

        t2 = QWidget()
        g2 = QVBoxLayout(t2)
        g2.setContentsMargins(14, 14, 14, 14)
        g2.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel(translate.t("dialog.gc")))
        self.gc = QComboBox()
        self.gc.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.gc.setStyleSheet(s_combo())
        self.gc.addItem(
            translate.t("dialog.gc_global", gc=settings.get("gc", "G1GC")), ""
        )
        for g in ("G1GC", "ZGC", "Parallel", "Serial"):
            self.gc.addItem(translate.t("dialog.gc_override", gc=g), g)
        if profile and profile.override_gc:
            idx = self.gc.findData(profile.override_gc)
            if idx >= 0:
                self.gc.setCurrentIndex(idx)
        row.addWidget(self.gc)
        row.addStretch()
        g2.addLayout(row)

        self.jvm_lbl = QLabel(translate.t("menu.jvm_flags"))
        self.jvm_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        g2.addWidget(self.jvm_lbl)

        self.jvm = QPlainTextEdit()
        self.jvm.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.jvm.viewport().setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.jvm.setStyleSheet(s_textedit())
        self.jvm.setPlaceholderText(translate.t("menu.jvm_flags"))
        self.jvm.setFixedHeight(90)

        self._jvm_seed = ""
        self._load_jvm_from_settings()

        g2.addWidget(self.jvm, 0)
        g2.addStretch(1)
        self.tabs.addTab(t2, translate.t("dialog.tab_jvm"))

        t3 = QWidget()
        g3 = QVBoxLayout(t3)
        g3.setContentsMargins(14, 14, 14, 14)
        g3.setSpacing(8)
        self.env_lbl = QLabel(translate.t("dialog.env"))
        self.env_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        g3.addWidget(self.env_lbl)
        self.env = QPlainTextEdit()
        self.env.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.env.viewport().setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.env.setStyleSheet(s_textedit())
        self.env.setPlaceholderText(translate.t("dialog.env_ph"))
        self.env.setPlainText(profile.override_env_vars if profile else "")
        self.env.setFixedHeight(90)
        g3.addWidget(self.env, 0)
        g3.addStretch(1)
        self.tabs.addTab(t3, translate.t("dialog.tab_env"))

        t4 = QWidget()
        g4 = QGridLayout(t4)
        g4.setContentsMargins(14, 14, 14, 14)
        g4.setSpacing(8)
        g4.addWidget(QLabel(translate.t("dialog.java")), 0, 0)
        jrow = QHBoxLayout()
        self.java_path = QLineEdit(profile.override_java_path if profile else "")
        self.java_path.setStyleSheet(s_entry())
        self.java_path.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        try:
            resolved = best_java(
                "1.20.1", log=None, override=settings.get("java_path", "")
            )
        except Exception:  # noqa: BLE001
            resolved = None
        if resolved:
            self.java_path.setPlaceholderText(
                translate.t("dialog.java_auto", path=resolved)
            )
        else:
            self.java_path.setPlaceholderText(translate.t("dialog.java_autodetect"))
        jrow.addWidget(self.java_path, 1)
        find_btn = QPushButton(translate.t("btn.auto"))
        find_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        find_btn.setStyleSheet(s_btn(theme.BG3, theme.FG, theme.BG2))
        find_btn.clicked.connect(self._find_java)
        jrow.addWidget(find_btn)
        browse_btn = QPushButton(translate.t("btn.browse"))
        browse_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        browse_btn.setStyleSheet(s_btn(theme.BG3, theme.FG, theme.BG2))
        browse_btn.clicked.connect(self._browse_java)
        jrow.addWidget(browse_btn)
        g4.addLayout(jrow, 0, 1)

        g4.addWidget(QLabel(translate.t("dialog.wrapper")), 1, 0)
        self.wrapper = QLineEdit(profile.override_wrapper if profile else "")
        self.wrapper.setStyleSheet(s_entry())
        self.wrapper.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.wrapper.setPlaceholderText(translate.t("dialog.wrapper_ph"))
        g4.addWidget(self.wrapper, 1, 1)
        g4.setRowStretch(2, 1)
        self.tabs.addTab(t4, translate.t("dialog.tab_advanced"))

        btns_widget = QWidget()
        btns_widget.setFixedHeight(50)
        btns = QHBoxLayout(btns_widget)
        btns.setContentsMargins(0, 10, 0, 0)
        btns.addStretch()

        c = QPushButton(translate.t("btn.cancel"))
        c.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        c.setStyleSheet(s_btn(theme.BG3, theme.FG, theme.BG2))
        c.setMinimumWidth(100)
        c.clicked.connect(self.reject)
        btns.addWidget(c)

        ok = QPushButton(
            translate.t("btn.create") if self.is_new else translate.t("btn.save")
        )
        ok.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ok.setStyleSheet(s_btn_accent())
        ok.setMinimumWidth(100)
        ok.clicked.connect(self.accept)
        btns.addWidget(ok)

        v.addWidget(btns_widget, 0)

        self.name.selectAll()
        self.name.setFocus()

        for _lbl in self.findChildren(QLabel):
            _lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            _lbl.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)

        fade_in(self)

    def _load_jvm_from_settings(self):
        try:
            data = _json.loads(SETTINGS_FILE.read_text())
            global_val = (
                data.get("default_jvm_flags", DEFAULTS.get("default_jvm_flags", ""))
                or ""
            ).strip()
        except Exception:  # noqa: BLE001
            global_val = (self.settings.get("default_jvm_flags", "") or "").strip()

        instance_val = ""
        if self.profile is not None:
            instance_val = (self.profile.override_jvm_flags or "").strip()

        if instance_val and instance_val != global_val:
            shown = instance_val
        else:
            shown = global_val

        self._jvm_seed = shown
        self.jvm.blockSignals(True)
        self.jvm.setPlainText(shown)
        self.jvm.blockSignals(False)

    def showEvent(self, event):
        super().showEvent(event)
        if self.profile is not None:
            self._load_jvm_from_settings()

    def _schedule_save(self, *a):
        pass

    def _flush(self):
        pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            event.accept()
            return
        super().keyPressEvent(event)

    def _find_java(self):
        javas = find_javas()
        if not javas:
            QMessageBox.information(
                self, translate.t("menu.no_java"), translate.t("menu.no_java_msg")
            )
            return
        items = [f"{label} — {path}" for path, (label, _) in javas]
        choice, ok = QInputDialog.getItem(
            self,
            translate.t("menu.browse_java_title"),
            translate.t("menu.browse_java_installs"),
            items,
            0,
            False,
        )
        if ok and choice:
            idx = items.index(choice)
            self.java_path.setText(javas[idx][0])

    def _browse_java(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            translate.t("menu.select_java_file"),
            str(Path.home()),
            "Java (java)" if not IS_WIN else "Java (*.exe)",
        )
        if path:
            self.java_path.setText(path)

    def apply(self, profile):
        profile.version = self.ver.currentText()
        profile.ram = str(int(self.ram.currentData()))
        profile.loader = self.loader.currentData()
        profile.override_gc = self.gc.currentData() or ""

        new_jvm = self.jvm.toPlainText().strip()
        if new_jvm == (self._jvm_seed or "").strip():
            profile.override_jvm_flags = ""
        else:
            profile.override_jvm_flags = new_jvm

        profile.override_env_vars = self.env.toPlainText().strip()
        profile.override_java_path = self.java_path.text().strip()
        profile.override_wrapper = self.wrapper.text().strip()

    def values(self):
        return (
            self.name.text().strip(),
            self.ver.currentText(),
            str(int(self.ram.currentData())),
            self.loader.currentData(),
        )
