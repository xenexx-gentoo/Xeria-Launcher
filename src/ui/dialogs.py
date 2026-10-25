from pathlib import Path

from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QEvent, QObject,
)
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QGridLayout, QTabWidget, QPlainTextEdit,
    QMessageBox, QInputDialog, QFileDialog, QFrame,
    QGraphicsOpacityEffect, QSizePolicy,
)

from core import theme
from core import translate
from core.java import find_javas, best_java
from core.jvm import default_jvm_flags
from core.paths import IS_WIN
from ui.helpers import (
    s_btn, s_btn_accent, s_entry, s_combo, s_textedit, s_tabs,
)


class _EscCloseFilter(QObject):
    def __init__(self, dialog, field):
        super().__init__(dialog)
        self._dialog = dialog
        self._field = field

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress \
                and event.key() == Qt.Key.Key_Escape:
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


class _ChoiceCard(QFrame):
    HEIGHT = 46

    def __init__(self, title, subtitle, accent, on_click, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setObjectName("choiceCard")
        self._accent = accent

        if accent:
            bg = theme.ACCENT
            fg_title = theme.on_accent()
            fg_sub = fg_title
            border = "none"
            hover = theme.ACCENT2
        else:
            bg = theme.BG2
            fg_title = theme.FG
            fg_sub = theme.GRAY
            border = f"1px solid {theme.BORDER}"
            hover = theme.BG3

        self._normal_css = (
            f"QFrame#choiceCard{{background:{bg};border:{border};"
            f"border-radius:0}}")
        self._hover_css = (
            f"QFrame#choiceCard{{background:{hover};border:{border};"
            f"border-radius:0}}")
        self.setStyleSheet(self._normal_css)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(0)

        t = QLabel(title)
        t.setFixedHeight(16)
        t.setStyleSheet(
            f"background:transparent;border:none;color:{fg_title};"
            f"font-size:10pt;font-weight:bold;"
            f"font-family:'{theme.UI_FONT}'")
        lay.addWidget(t)

        s = QLabel(subtitle)
        s.setFixedHeight(13)
        s.setStyleSheet(
            f"background:transparent;border:none;color:{fg_sub};"
            f"font-size:8pt;font-family:'{theme.UI_FONT}'")
        lay.addWidget(s)

    def enterEvent(self, event):
        self.setStyleSheet(self._hover_css)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._normal_css)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if callable(self._on_click):
                self._on_click()
        super().mousePressEvent(event)


class ChooseInstallDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle(translate.t("dialog.add_title"))
        self.setFixedSize(420, 310)
        self.setSizeGripEnabled(False)
        self.setStyleSheet(
            f"QDialog{{background:{theme.BG};color:{theme.FG};border:none}}")

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(0)

        title = QLabel(translate.t("dialog.add_title"))
        title.setFixedHeight(22)
        title.setStyleSheet(
            f"background:transparent;color:{theme.FG};"
            f"font-size:12pt;font-weight:bold;"
            f"font-family:'{theme.UI_FONT}'")
        v.addWidget(title)

        subtitle = QLabel(translate.t("dialog.add_sub"))
        subtitle.setFixedHeight(13)
        subtitle.setStyleSheet(
            f"background:transparent;color:{theme.GRAY};"
            f"font-size:8pt;font-family:'{theme.UI_FONT}'")
        v.addWidget(subtitle)

        v.addSpacing(8)

        for label_key, sub_key, key, accent in (
            ("dialog.modrinth", "dialog.modrinth_sub", "modrinth", True),
            ("dialog.blank", "dialog.blank_sub", "blank", False),
            ("dialog.local", "dialog.local_sub", "local", False),
            ("dialog.migrate", "dialog.migrate_sub", "migrate", False),
        ):
            card = _ChoiceCard(
                translate.t(label_key), translate.t(sub_key),
                accent,
                on_click=lambda k=key: self._pick(k),
                parent=self)
            v.addWidget(card)
            v.addSpacing(6)

        v.addStretch(1)
        fade_in(self)

    def _pick(self, c):
        self.choice = c
        self.accept()


class ProfileDialog(QDialog):
    def __init__(self, parent, releases, settings, profile=None):
        super().__init__(parent)
        self.settings = settings
        self.profile = profile
        self.is_new = profile is None
        self.setWindowTitle(
            translate.t("dialog.profile_new") if self.is_new
            else translate.t("dialog.profile_edit", name=profile.name))
        self.setFixedSize(700, 640)
        self.setSizeGripEnabled(False)
        self.setStyleSheet(
            f"QDialog{{background:{theme.BG};color:{theme.FG}}}"
            f"QLabel{{background:{theme.BG};color:{theme.FG};"
            f"font-family:\"{theme.UI_FONT}\";font-size:10pt}}"
            + s_entry() + s_combo() + s_textedit() + s_tabs())

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)
        self.tabs = QTabWidget(self)
        v.addWidget(self.tabs, 1)

        t1 = QWidget()
        g1 = QGridLayout(t1)
        g1.setContentsMargins(14, 14, 14, 14)
        g1.setSpacing(8)
        g1.addWidget(QLabel(translate.t("dialog.name")), 0, 0)
        self.name = QLineEdit(profile.name if profile else "My Instance")
        g1.addWidget(self.name, 0, 1)
        g1.addWidget(QLabel(translate.t("dialog.version")), 1, 0)
        self.ver = QComboBox()
        ids = [x["id"] for x in releases]
        self.ver.addItems(ids)
        if profile and profile.version in ids:
            self.ver.setCurrentText(profile.version)
        g1.addWidget(self.ver, 1, 1)
        g1.addWidget(QLabel(translate.t("dialog.loader")), 2, 0)
        self.loader = QComboBox()
        for k in ("vanilla", "fabric", "forge", "neoforge", "quilt"):
            self.loader.addItem(translate.t(f"loader.{k}"), k)
        if profile:
            idx = self.loader.findData(profile.loader)
            if idx >= 0:
                self.loader.setCurrentIndex(idx)
        g1.addWidget(self.loader, 2, 1)
        g1.addWidget(QLabel(translate.t("dialog.ram")), 3, 0)
        self.ram = QComboBox()
        for label, val in (("2 GB", "2"), ("4 GB", "4"),
                           ("8 GB", "8"), ("16 GB", "16")):
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
        self.gc.addItem(
            translate.t("dialog.gc_global",
                        gc=settings.get("gc", "G1GC")), "")
        for g in ("G1GC", "ZGC", "Parallel", "Serial"):
            self.gc.addItem(translate.t("dialog.gc_override", gc=g), g)
        if profile and profile.override_gc:
            idx = self.gc.findData(profile.override_gc)
            if idx >= 0:
                self.gc.setCurrentIndex(idx)
        row.addWidget(self.gc)
        row.addStretch()
        g2.addLayout(row)
        g2.addWidget(QLabel(translate.t("dialog.jvm_flags")))
        self.jvm = QPlainTextEdit()
        auto = " ".join(default_jvm_flags(
            str(int(self.ram.currentData())),
            self.gc.currentData() or settings.get("gc", "G1GC")))
        user = profile.override_jvm_flags if profile else ""
        self.jvm.setPlainText((auto + " " + user).strip())
        g2.addWidget(self.jvm, 1)
        self.ram.currentIndexChanged.connect(self._refresh_jvm)
        self.gc.currentIndexChanged.connect(self._refresh_jvm)
        self._auto_str = auto
        self.tabs.addTab(t2, translate.t("dialog.tab_jvm"))

        t3 = QWidget()
        g3 = QVBoxLayout(t3)
        g3.setContentsMargins(14, 14, 14, 14)
        g3.setSpacing(8)
        g3.addWidget(QLabel(translate.t("dialog.env")))
        self.env = QPlainTextEdit()
        self.env.setPlaceholderText(translate.t("dialog.env_ph"))
        self.env.setPlainText(profile.override_env_vars if profile else "")
        g3.addWidget(self.env, 1)
        self.tabs.addTab(t3, translate.t("dialog.tab_env"))

        t4 = QWidget()
        g4 = QGridLayout(t4)
        g4.setContentsMargins(14, 14, 14, 14)
        g4.setSpacing(8)
        g4.addWidget(QLabel(translate.t("dialog.java")), 0, 0)
        jrow = QHBoxLayout()
        self.java_path = QLineEdit(
            profile.override_java_path if profile else "")
        try:
            resolved = best_java(
                "1.20.1", log=None,
                override=settings.get("java_path", ""))
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
        find_btn.setAutoDefault(False)
        find_btn.setDefault(False)
        find_btn.setStyleSheet(s_btn(theme.BG2, theme.FG, theme.BG3))
        find_btn.clicked.connect(self._find_java)
        jrow.addWidget(find_btn)
        browse_btn = QPushButton(translate.t("btn.browse"))
        browse_btn.setAutoDefault(False)
        browse_btn.setDefault(False)
        browse_btn.setStyleSheet(s_btn(theme.BG2, theme.FG, theme.BG3))
        browse_btn.clicked.connect(self._browse_java)
        jrow.addWidget(browse_btn)
        g4.addLayout(jrow, 0, 1)

        g4.addWidget(QLabel(translate.t("dialog.wrapper")), 1, 0)
        self.wrapper = QLineEdit(
            profile.override_wrapper if profile else "")
        self.wrapper.setPlaceholderText(translate.t("dialog.wrapper_ph"))
        g4.addWidget(self.wrapper, 1, 1)
        g4.setRowStretch(2, 1)
        self.tabs.addTab(t4, translate.t("dialog.tab_advanced"))

        btns = QHBoxLayout()
        btns.addStretch()
        c = QPushButton(translate.t("btn.cancel"))
        c.setAutoDefault(False)
        c.setDefault(False)
        c.setStyleSheet(s_btn(theme.BG2, theme.FG, theme.BG3))
        c.clicked.connect(self.reject)
        btns.addWidget(c)
        ok = QPushButton(
            translate.t("btn.create") if self.is_new
            else translate.t("btn.save"))
        ok.setAutoDefault(False)
        ok.setDefault(False)
        ok.setStyleSheet(s_btn_accent())
        ok.clicked.connect(self.accept)
        btns.addWidget(ok)
        v.addLayout(btns)
        self.name.selectAll()
        self.name.setFocus()
        fade_in(self)

    def _refresh_jvm(self):
        auto = " ".join(default_jvm_flags(
            str(int(self.ram.currentData())),
            self.gc.currentData() or self.settings.get("gc", "G1GC")))
        current = self.jvm.toPlainText()
        if getattr(self, "_auto_str", "") and current.startswith(
                self._auto_str):
            user_part = current[len(self._auto_str):].strip()
            self.jvm.setPlainText((auto + " " + user_part).strip())
        self._auto_str = auto

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

    def apply(self, profile):
        profile.version = self.ver.currentText()
        profile.ram = str(int(self.ram.currentData()))
        profile.loader = self.loader.currentData()
        profile.override_gc = self.gc.currentData() or ""
        profile.override_jvm_flags = self.jvm.toPlainText().strip()
        profile.override_env_vars = self.env.toPlainText().strip()
        profile.override_java_path = self.java_path.text().strip()
        profile.override_wrapper = self.wrapper.text().strip()

    def values(self):
        return (self.name.text().strip(), self.ver.currentText(),
                str(int(self.ram.currentData())),
                self.loader.currentData())


from browse.modpacks import ModpackSearchDialog  # noqa: E402,F401
