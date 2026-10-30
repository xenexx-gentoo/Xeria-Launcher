import platform
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
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

from core import hardware, theme, translate
from core.java import find_javas
from core.paths import IS_WIN, MC_ROOT, XERIA_ROOT
from ui.helpers import (
    glass_panel,
    s_btn,
    s_combo,
    s_entry,
    s_tabs,
    s_textedit,
)

GITHUB_URL = "https://github.com/xenexx-arch/Xeria-Launcher/tree/main"
APP_VERSION = "v2.504"


class MenuView(QWidget):
    back_requested = pyqtSignal()
    theme_changed = pyqtSignal(str, str)

    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self._about_labels = []
        self._about_link = None
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self.panel = QFrame()
        self.panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.panel.setAutoFillBackground(False)
        self.panel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.panel.setStyleSheet(
            f"QFrame{{background:{glass_panel(50)};border:none;border-radius:14px}}"
        )
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(14, 14, 14, 14)
        pv.setSpacing(8)

        self.tabs = QTabWidget(self.panel)
        self.tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.tabBar().setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.tabs.setStyleSheet(s_tabs())
        pv.addWidget(self.tabs, 1)
        v.addWidget(self.panel, 1)

        gen = QWidget()
        gen.setStyleSheet("QWidget{background:transparent;}")
        gg = QGridLayout(gen)
        gg.setContentsMargins(14, 14, 14, 14)
        gg.setSpacing(8)

        self.theme_lbl = QLabel(translate.t("menu.theme"))
        self.theme_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        gg.addWidget(self.theme_lbl, 0, 0)
        self.theme_box = QComboBox()
        self.theme_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.theme_box.setStyleSheet(s_combo())
        self.theme_box.addItem(translate.t("menu.theme_dark"), "dark")
        self.theme_box.addItem(translate.t("menu.theme_light"), "light")
        cur = str(self.settings.get("theme", "dark")).lower()
        idx = self.theme_box.findData(cur)
        if idx >= 0:
            self.theme_box.setCurrentIndex(idx)
        gg.addWidget(self.theme_box, 0, 1)

        self.accent_lbl = QLabel(translate.t("menu.accent"))
        self.accent_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        gg.addWidget(self.accent_lbl, 1, 0)
        self.accent_box = QComboBox()
        self.accent_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.accent_box.setStyleSheet(s_combo())
        for key in (
            "white",
            "blue",
            "purple",
            "green",
            "orange",
            "red",
            "pink",
            "cyan",
        ):
            self.accent_box.addItem(translate.t(f"menu.accent_{key}"), key.capitalize())
        cur_acc = self.settings.get("accent", "White")
        idx = self.accent_box.findData(cur_acc)
        if idx >= 0:
            self.accent_box.setCurrentIndex(idx)
        gg.addWidget(self.accent_box, 1, 1)

        self.check_lbl = QLabel(translate.t("menu.check_interval"))
        self.check_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        gg.addWidget(self.check_lbl, 2, 0)
        self.check_interval = QComboBox()
        self.check_interval.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.check_interval.setStyleSheet(s_combo())
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
        jv.setStyleSheet("QWidget{background:transparent;}")
        gj = QGridLayout(jv)
        gj.setContentsMargins(14, 14, 14, 14)
        gj.setSpacing(8)

        self.java_lbl = QLabel(translate.t("menu.java"))
        self.java_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        gj.addWidget(self.java_lbl, 0, 0)
        jrow = QHBoxLayout()
        stored_java = (self.settings.get("java_path", "") or "").strip()
        auto_java = ""
        try:
            detected = find_javas()
            if detected:
                for path, (label, major) in detected:
                    low = path.lower()
                    if (
                        "/usr/bin/java" in low
                        or "java_home" in low
                        or low.endswith("/.jdks/java")
                        or ("/bin/java" in low and "/runtime/" not in low)
                    ):
                        auto_java = path
                        break
                if not auto_java:
                    auto_java = detected[0][0]
        except Exception:  # noqa: BLE001
            auto_java = ""

        self.java_path = QLineEdit(stored_java)
        self.java_path.setStyleSheet(s_entry())
        self.java_path.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if auto_java:
            self.java_path.setPlaceholderText(
                translate.t("dialog.java_auto", path=auto_java)
            )
        else:
            self.java_path.setPlaceholderText(translate.t("dialog.java_autodetect"))
        jrow.addWidget(self.java_path, 1)

        self.find_btn = QPushButton(translate.t("btn.auto"))
        self.find_btn.setStyleSheet(s_btn(theme.BG2, theme.FG, theme.BG3))
        self.find_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.find_btn.clicked.connect(self._find_java)
        jrow.addWidget(self.find_btn)
        self.br_btn = QPushButton(translate.t("btn.browse"))
        self.br_btn.setStyleSheet(s_btn(theme.BG2, theme.FG, theme.BG3))
        self.br_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.br_btn.clicked.connect(self._browse_java)
        jrow.addWidget(self.br_btn)
        gj.addLayout(jrow, 0, 1)

        self.default_jvm_lbl = QLabel(translate.t("menu.default_jvm"))
        self.default_jvm_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        gj.addWidget(self.default_jvm_lbl, 1, 0)

        self.default_flags = QPlainTextEdit(self.settings.get("default_jvm_flags", ""))
        self.default_flags.setPlaceholderText(translate.t("menu.default_jvm_ph"))
        self.default_flags.setStyleSheet(s_textedit())
        self.default_flags.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.default_flags.viewport().setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        gj.addWidget(self.default_flags, 2, 0, 1, 2)
        gj.setRowStretch(3, 1)
        self.tabs.addTab(jv, translate.t("menu.tab_jvm"))

        pf = QWidget()
        pf.setStyleSheet("QWidget{background:transparent;}")
        gp = QGridLayout(pf)
        gp.setContentsMargins(14, 14, 14, 14)
        gp.setSpacing(8)
        self.gc_lbl = QLabel(translate.t("menu.default_gc"))
        self.gc_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        gp.addWidget(self.gc_lbl, 0, 0)
        self.gc_box = QComboBox()
        self.gc_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.gc_box.setStyleSheet(s_combo())
        self.gc_box.addItems(["G1GC", "ZGC", "Parallel", "Serial"])
        self.gc_box.setCurrentText(self.settings.get("gc", "G1GC"))
        gp.addWidget(self.gc_box, 0, 1)
        gp.setRowStretch(1, 1)
        self.tabs.addTab(pf, translate.t("menu.tab_perf"))

        ev = QWidget()
        ev.setStyleSheet("QWidget{background:transparent;}")
        gv = QVBoxLayout(ev)
        gv.setContentsMargins(14, 14, 14, 14)
        gv.setSpacing(8)
        self.env_lbl = QLabel(translate.t("menu.env_overrides"))
        self.env_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        gv.addWidget(self.env_lbl)
        self.env = QPlainTextEdit()
        self.env.setPlaceholderText(translate.t("menu.env_ph"))
        self.env.setPlainText(self.settings.get("env_vars", ""))
        self.env.setStyleSheet(s_textedit())
        self.env.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.env.viewport().setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        gv.addWidget(self.env, 1)
        self.tabs.addTab(ev, translate.t("menu.tab_env"))

        wp = QWidget()
        wp.setStyleSheet("QWidget{background:transparent;}")
        gw = QGridLayout(wp)
        gw.setContentsMargins(14, 14, 14, 14)
        gw.setSpacing(8)
        self.wrapper_lbl = QLabel(translate.t("menu.wrapper"))
        self.wrapper_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        gw.addWidget(self.wrapper_lbl, 0, 0)
        self.wrapper = QLineEdit(self.settings.get("wrapper_command", ""))
        self.wrapper.setPlaceholderText(translate.t("menu.wrapper_ph"))
        self.wrapper.setStyleSheet(s_entry())
        self.wrapper.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        gw.addWidget(self.wrapper, 0, 1)
        gw.setRowStretch(1, 1)
        self.tabs.addTab(wp, translate.t("menu.tab_wrapper"))

        ab = QWidget()
        ab.setStyleSheet("QWidget{background:transparent;}")
        self._about_layout = QVBoxLayout(ab)
        self._about_layout.setContentsMargins(14, 14, 14, 14)
        self._about_layout.setSpacing(6)
        self._build_about()
        self.tabs.addTab(ab, translate.t("menu.tab_about"))

        self.theme_box.currentIndexChanged.connect(self._save_all)
        self.accent_box.currentIndexChanged.connect(self._save_all)
        self.check_interval.currentIndexChanged.connect(self._save_all)
        self.gc_box.currentTextChanged.connect(self._save_all)
        self.wrapper.textChanged.connect(self._save_all)
        self.default_flags.textChanged.connect(self._save_all)

        def _make_debounce():
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(2000)
            t.timeout.connect(self._save_all)
            return t

        self._java_path_debounce = _make_debounce()
        self.java_path.textChanged.connect(self._java_path_debounce.start)
        self._env_debounce = _make_debounce()
        self.env.textChanged.connect(self._env_debounce.start)

        for _lbl in self.findChildren(QLabel):
            _lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            _lbl.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        for _btn in self.findChildren(QPushButton):
            _btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for _cb in self.findChildren(QComboBox):
            _cb.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _build_about(self):
        while self._about_layout.count():
            item = self._about_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._about_labels = []
        self._about_link = None

        hw = hardware.get()
        rows = [
            (
                translate.t("menu.about_launcher"),
                f"{translate.t('app.title')} {APP_VERSION}",
            ),
            (
                translate.t("menu.about_platform"),
                f"{platform.system()} {platform.release()}",
            ),
            (translate.t("menu.about_python"), platform.python_version()),
            (translate.t("menu.about_mc_root"), str(MC_ROOT)),
            (translate.t("menu.about_config"), str(XERIA_ROOT)),
        ]
        for label, value in rows:
            lbl = QLabel(f"<b>{label}:</b> {value}")
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lbl.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
            lbl.setStyleSheet("background:transparent;outline:none;")
            self._about_layout.addWidget(lbl)
            self._about_labels.append(lbl)

        hw_title = QLabel(f"<b>{translate.t('menu.about_hardware')}:</b>")
        hw_title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hw_title.setTextFormat(Qt.TextFormat.RichText)
        hw_title.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        hw_title.setStyleSheet("background:transparent;outline:none;")
        self._about_layout.addWidget(hw_title)
        self._about_labels.append(hw_title)

        for label, value in hw.summary_lines():
            lbl = QLabel(
                f"<span style='padding-left:18px;'>"
                f"&#8203;&#8203;&#8203;</span>"
                f"<b>{label}:</b> {value}"
            )
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lbl.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
            lbl.setStyleSheet("background:transparent;outline:none;margin-left:18px;")
            self._about_layout.addWidget(lbl)
            self._about_labels.append(lbl)

        link = QLabel(
            f"<b>{translate.t('menu.about_github')}:</b> "
            f"<a href='{GITHUB_URL}' "
            f"style='color:{theme.ACCENT};text-decoration:none;"
            f"font-weight:normal;'>{GITHUB_URL}</a>"
        )
        link.setTextFormat(Qt.TextFormat.RichText)
        link.setOpenExternalLinks(True)
        link.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        link.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        link.setStyleSheet(f"background:transparent;outline:none;color:{theme.FG};")
        try:
            pal = link.palette()
            pal.setColor(pal.ColorRole.Link, QColor(theme.ACCENT))
            link.setPalette(pal)
        except Exception:  # noqa: BLE001, S110
            pass
        self._about_layout.addWidget(link)
        self._about_link = link
        self._about_labels.append(link)

        self._about_layout.addStretch(1)

    def hideEvent(self, event):
        for attr in ("_java_path_debounce", "_env_debounce"):
            t = getattr(self, attr, None)
            if t is not None and t.isActive():
                t.stop()
                self._save_all()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.back_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def restyle(self):
        from core import theme as _theme

        self.panel.setStyleSheet(
            f"QFrame{{background:{glass_panel(50)};border:none;border-radius:14px}}"
        )
        self.tabs.setStyleSheet(s_tabs())
        self.tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for w in self.findChildren(QLabel):
            ss = w.styleSheet()
            if "link" in ss or "href" in w.text():
                continue
            w.setStyleSheet(
                f"background:transparent;color:{_theme.FG};"
                f'font-family:"{_theme.UI_FONT}";font-size:10pt;'
                f"outline:none;"
            )
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for w in self.findChildren(QPushButton):
            w.setStyleSheet(s_btn(_theme.BG2, _theme.FG, _theme.BG3))
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for w in self.findChildren(QComboBox):
            w.setStyleSheet(s_combo())
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for w in self.findChildren(QPlainTextEdit):
            w.setStyleSheet(s_textedit())
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            w.viewport().setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for w in self.findChildren(QLineEdit):
            w.setStyleSheet(s_entry())
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def retranslate_ui(self):
        self.tabs.setTabText(0, translate.t("menu.tab_general"))
        self.tabs.setTabText(1, translate.t("menu.tab_jvm"))
        self.tabs.setTabText(2, translate.t("menu.tab_perf"))
        self.tabs.setTabText(3, translate.t("menu.tab_env"))
        self.tabs.setTabText(4, translate.t("menu.tab_wrapper"))
        self.tabs.setTabText(5, translate.t("menu.tab_about"))
        self.theme_lbl.setText(translate.t("menu.theme"))
        self.accent_lbl.setText(translate.t("menu.accent"))
        self.check_lbl.setText(translate.t("menu.check_interval"))
        self.java_lbl.setText(translate.t("menu.java"))
        self.default_jvm_lbl.setText(translate.t("menu.default_jvm"))
        self.gc_lbl.setText(translate.t("menu.default_gc"))
        self.env_lbl.setText(translate.t("menu.env_overrides"))
        self.wrapper_lbl.setText(translate.t("menu.wrapper"))
        self.find_btn.setText(translate.t("btn.auto"))
        self.br_btn.setText(translate.t("btn.browse"))
        self.default_flags.setPlaceholderText(translate.t("menu.default_jvm_ph"))

        cur_theme = self.theme_box.currentData()
        self.theme_box.blockSignals(True)
        self.theme_box.clear()
        self.theme_box.addItem(translate.t("menu.theme_dark"), "dark")
        self.theme_box.addItem(translate.t("menu.theme_light"), "light")
        idx = self.theme_box.findData(cur_theme)
        if idx >= 0:
            self.theme_box.setCurrentIndex(idx)
        self.theme_box.blockSignals(False)

        cur_acc = self.accent_box.currentData()
        self.accent_box.blockSignals(True)
        self.accent_box.clear()
        for key in (
            "white",
            "blue",
            "purple",
            "green",
            "orange",
            "red",
            "pink",
            "cyan",
        ):
            self.accent_box.addItem(translate.t(f"menu.accent_{key}"), key.capitalize())
        idx = self.accent_box.findData(cur_acc)
        if idx >= 0:
            self.accent_box.setCurrentIndex(idx)
        self.accent_box.blockSignals(False)

        cur_int = self.check_interval.currentData()
        self.check_interval.blockSignals(True)
        self.check_interval.clear()
        for key, secs in (
            ("menu.interval_never", 0),
            ("menu.interval_hourly", 3600),
            ("menu.interval_daily", 86400),
            ("menu.interval_weekly", 604800),
            ("menu.interval_monthly", 2592000),
        ):
            self.check_interval.addItem(translate.t(key), secs)
        idx = self.check_interval.findData(cur_int)
        if idx >= 0:
            self.check_interval.setCurrentIndex(idx)
        self.check_interval.blockSignals(False)

        self._build_about()

    def _save_all(self, *a):
        self.settings.set("theme", self.theme_box.currentData())
        self.settings.set("accent", self.accent_box.currentData())
        self.settings.set(
            "auto_check_interval", int(self.check_interval.currentData() or 0)
        )
        self.settings.set("java_path", self.java_path.text().strip())
        self.settings.set("default_jvm_flags", self.default_flags.toPlainText().strip())
        self.settings.set("gc", self.gc_box.currentText())
        self.settings.set("env_vars", self.env.toPlainText().strip())
        self.settings.set("wrapper_command", self.wrapper.text().strip())

        self.settings.save()
        self.theme_changed.emit(
            self.theme_box.currentData(), self.accent_box.currentData()
        )

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
