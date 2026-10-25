import platform
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QGridLayout, QTabWidget,
    QPlainTextEdit, QMessageBox, QInputDialog, QFileDialog,
)

from core import theme
from core import hardware
from core import translate
from core.paths import IS_WIN, MC_ROOT, XERIA_ROOT
from core.java import find_javas, best_java
from ui.helpers import s_btn, s_tabs, s_combo, s_textedit, s_entry


GITHUB_URL = "https://github.com/xenexx-arch/Xeria-Launcher/tree/main"
APP_VERSION = "v2.504"


class MenuView(QWidget):
    back_requested = pyqtSignal()
    theme_changed = pyqtSignal(str, str)

    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self.tabs = QTabWidget(self)
        self.tabs.setStyleSheet(s_tabs())
        v.addWidget(self.tabs, 1)

        gen = QWidget()
        gg = QGridLayout(gen)
        gg.setContentsMargins(14, 14, 14, 14)
        gg.setSpacing(8)

        gg.addWidget(QLabel(translate.t("menu.theme")), 0, 0)
        self.theme_box = QComboBox()
        self.theme_box.addItem(translate.t("menu.theme_dark"), "dark")
        self.theme_box.addItem(translate.t("menu.theme_light"), "light")
        cur = str(self.settings.get("theme", "dark")).lower()
        idx = self.theme_box.findData(cur)
        if idx >= 0:
            self.theme_box.setCurrentIndex(idx)
        gg.addWidget(self.theme_box, 0, 1)

        gg.addWidget(QLabel(translate.t("menu.accent")), 1, 0)
        self.accent_box = QComboBox()
        self.accent_box.addItems(
            ["White", "Blue", "Purple", "Green", "Orange",
             "Red", "Pink", "Cyan"])
        self.accent_box.setCurrentText(
            self.settings.get("accent", "White"))
        gg.addWidget(self.accent_box, 1, 1)

        gg.addWidget(QLabel(translate.t("menu.check_interval")), 2, 0)
        self.check_interval = QComboBox()
        for key, secs in (
            ("menu.interval_never", 0),
            ("menu.interval_hourly", 3600),
            ("menu.interval_daily", 86400),
            ("menu.interval_weekly", 604800),
            ("menu.interval_monthly", 2592000),
        ):
            self.check_interval.addItem(translate.t(key), secs)
        current = int(self.settings.get("auto_check_interval", 86400))
        idx = self.check_interval.findData(current)
        if idx < 0:
            idx = self.check_interval.findData(86400)
        self.check_interval.setCurrentIndex(idx)
        gg.addWidget(self.check_interval, 2, 1)

        gg.setRowStretch(3, 1)
        self.tabs.addTab(gen, translate.t("menu.tab_general"))

        jv = QWidget()
        gj = QGridLayout(jv)
        gj.setContentsMargins(14, 14, 14, 14)
        gj.setSpacing(8)

        gj.addWidget(QLabel(translate.t("menu.java")), 0, 0)
        jrow = QHBoxLayout()
        self.java_path = QLineEdit(self.settings.get("java_path", ""))
        try:
            resolved = best_java(
                "1.20.1", log=None,
                override=self.settings.get("java_path", ""))
        except Exception:
            resolved = None
        if resolved:
            self.java_path.setPlaceholderText(
                translate.t("dialog.java_auto", path=resolved))
        else:
            self.java_path.setPlaceholderText(
                translate.t("dialog.java_autodetect"))
        jrow.addWidget(self.java_path, 1)
        find_btn = QPushButton(translate.t("btn.auto"))
        find_btn.setStyleSheet(s_btn(theme.BG2, theme.FG, theme.BG3))
        find_btn.clicked.connect(self._find_java)
        jrow.addWidget(find_btn)
        br_btn = QPushButton(translate.t("btn.browse"))
        br_btn.setStyleSheet(s_btn(theme.BG2, theme.FG, theme.BG3))
        br_btn.clicked.connect(self._browse_java)
        jrow.addWidget(br_btn)
        gj.addLayout(jrow, 0, 1)

        gj.addWidget(QLabel(translate.t("menu.default_jvm")), 1, 0)
        self.default_flags = QPlainTextEdit(
            self.settings.get("default_jvm_flags", ""))
        self.default_flags.setPlaceholderText(
            translate.t("menu.default_jvm_ph"))
        gj.addWidget(self.default_flags, 2, 0, 1, 2)
        gj.setRowStretch(3, 1)
        self.tabs.addTab(jv, translate.t("menu.tab_jvm"))

        pf = QWidget()
        gp = QGridLayout(pf)
        gp.setContentsMargins(14, 14, 14, 14)
        gp.setSpacing(8)
        gp.addWidget(QLabel(translate.t("menu.default_gc")), 0, 0)
        self.gc_box = QComboBox()
        self.gc_box.addItems(["G1GC", "ZGC", "Parallel", "Serial"])
        self.gc_box.setCurrentText(self.settings.get("gc", "G1GC"))
        gp.addWidget(self.gc_box, 0, 1)
        gp.addWidget(QLabel(translate.t("menu.jvm_flags")), 1, 0)
        self.jvm = QPlainTextEdit(self.settings.get("jvm_flags", ""))
        gp.addWidget(self.jvm, 2, 0, 1, 2)
        gp.setRowStretch(3, 1)
        self.tabs.addTab(pf, translate.t("menu.tab_perf"))

        ev = QWidget()
        gv = QVBoxLayout(ev)
        gv.setContentsMargins(14, 14, 14, 14)
        gv.setSpacing(8)
        gv.addWidget(QLabel(translate.t("menu.env_overrides")))
        self.env = QPlainTextEdit()
        self.env.setPlaceholderText(translate.t("menu.env_ph"))
        self.env.setPlainText(self.settings.get("env_vars", ""))
        gv.addWidget(self.env, 1)
        self.tabs.addTab(ev, translate.t("menu.tab_env"))

        wp = QWidget()
        gw = QGridLayout(wp)
        gw.setContentsMargins(14, 14, 14, 14)
        gw.setSpacing(8)
        gw.addWidget(QLabel(translate.t("menu.wrapper")), 0, 0)
        self.wrapper = QLineEdit(self.settings.get("wrapper_command", ""))
        self.wrapper.setPlaceholderText(translate.t("menu.wrapper_ph"))
        gw.addWidget(self.wrapper, 0, 1)
        gw.setRowStretch(1, 1)
        self.tabs.addTab(wp, translate.t("menu.tab_wrapper"))

        ab = QWidget()
        ga = QVBoxLayout(ab)
        ga.setContentsMargins(14, 14, 14, 14)
        ga.setSpacing(6)
        hw = hardware.get()
        for label, value in (
            (translate.t("menu.about_launcher"),
             f"{translate.t('app.title')} {APP_VERSION}"),
            (translate.t("menu.about_hardware"), hw.summary()),
            (translate.t("menu.about_platform"),
             f"{platform.system()} {platform.release()}"),
            (translate.t("menu.about_python"),
             platform.python_version()),
            (translate.t("menu.about_mc_root"), str(MC_ROOT)),
            (translate.t("menu.about_config"), str(XERIA_ROOT)),
        ):
            ga.addWidget(QLabel(f"<b>{label}:</b> {value}"))
        link = QLabel(
            f"<b>{translate.t('menu.about_github')}:</b> "
            f"<a href='{GITHUB_URL}'>{GITHUB_URL}</a>")
        link.setOpenExternalLinks(True)
        ga.addWidget(link)
        ga.addStretch()
        self.tabs.addTab(ab, translate.t("menu.tab_about"))

        self.theme_box.currentIndexChanged.connect(self._save_all)
        self.accent_box.currentTextChanged.connect(self._save_all)
        self.check_interval.currentIndexChanged.connect(self._save_all)
        self.java_path.textChanged.connect(self._save_all)
        self.default_flags.textChanged.connect(self._save_all)
        self.gc_box.currentTextChanged.connect(self._save_all)
        self.jvm.textChanged.connect(self._save_all)
        self.env.textChanged.connect(self._save_all)
        self.wrapper.textChanged.connect(self._save_all)

    def restyle(self):
        from core import theme as _theme
        self.tabs.setStyleSheet(s_tabs())
        for w in self.findChildren(QLabel):
            ss = w.styleSheet()
            if "link" in ss or "href" in w.text():
                continue
            w.setStyleSheet(
                f"background:transparent;color:{_theme.FG};"
                f"font-family:\"{_theme.UI_FONT}\";font-size:10pt")
        for w in self.findChildren(QPushButton):
            w.setStyleSheet(s_btn(_theme.BG2, _theme.FG, _theme.BG3))
        for w in self.findChildren(QComboBox):
            w.setStyleSheet(s_combo())
        for w in self.findChildren(QPlainTextEdit):
            w.setStyleSheet(s_textedit())
        for w in self.findChildren(QLineEdit):
            w.setStyleSheet(s_entry())

    def _save_all(self, *a):
        self.settings.set("theme", self.theme_box.currentData())
        self.settings.set("accent", self.accent_box.currentText())
        self.settings.set(
            "auto_check_interval",
            int(self.check_interval.currentData() or 0))
        self.settings.set("java_path", self.java_path.text().strip())
        self.settings.set("default_jvm_flags",
                          self.default_flags.toPlainText().strip())
        self.settings.set("gc", self.gc_box.currentText())
        self.settings.set("jvm_flags", self.jvm.toPlainText().strip())
        self.settings.set("env_vars", self.env.toPlainText().strip())
        self.settings.set("wrapper_command", self.wrapper.text().strip())
        self.settings.save()
        self.theme_changed.emit(
            self.theme_box.currentData(),
            self.accent_box.currentText())

    def _find_java(self):
        javas = find_javas()
        if not javas:
            QMessageBox.information(
                self, translate.t("menu.no_java"),
                translate.t("menu.no_java_msg"))
            return
        items = [f"{label} — {path}" for path, (label, _) in javas]
        choice, ok = QInputDialog.getItem(
            self, translate.t("menu.browse_java_title"),
            translate.t("menu.browse_java_installs"),
            items, 0, False)
        if ok and choice:
            idx = items.index(choice)
            self.java_path.setText(javas[idx][0])

    def _browse_java(self):
        path, _ = QFileDialog.getOpenFileName(
            self, translate.t("menu.select_java_file"), str(Path.home()),
            "Java (java)" if not IS_WIN else "Java (*.exe)")
        if path:
            self.java_path.setText(path)
