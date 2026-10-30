from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from core import auth, theme, translate
from ui.helpers import s_plus_btn, s_popup_menu

ROW_GAP = 0
ROW_PAD_V = 16
LIST_FONT_SIZE = 10


class _AccountItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        row = option.rect.adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            accent_col = QColor(theme.ACCENT)
            accent_col.setAlpha(60 if selected else 30)
            painter.setBrush(accent_col)
            painter.drawRoundedRect(row, 8, 8)

        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if text:
            font = QFont(theme.UI_FONT, LIST_FONT_SIZE)
            font.setWeight(QFont.Weight.Light)

            if selected:
                painter.setPen(QPen(QColor(theme.FG)))
                font.setWeight(QFont.Weight.Medium)
            else:
                active = bool(index.data(Qt.ItemDataRole.UserRole + 1))
                painter.setPen(QPen(QColor(theme.ACCENT if active else theme.GRAY)))

            painter.setFont(font)
            fm = painter.fontMetrics()
            r = row.adjusted(10, ROW_PAD_V // 2, -10, -ROW_PAD_V // 2)
            ty = r.top() + (r.height() - fm.height()) // 2 + fm.ascent()
            elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, r.width())
            painter.drawText(r.left(), ty, elided)

        painter.restore()

    def sizeHint(self, option, index):
        fm = option.fontMetrics
        return QSize(0, fm.height() + ROW_PAD_V + ROW_GAP)


class AccountView(QWidget):
    def __init__(self, parent, settings, log):
        super().__init__(parent)
        self.settings = settings
        self._log = log
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(20)

        self.header = QFrame()
        self.header.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.header.setAutoFillBackground(False)
        self.header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.header.setStyleSheet(
            f"QFrame{{background:{theme.panel_glass(220)};border-radius:12px}}"
        )
        hdr = QHBoxLayout(self.header)
        hdr.setContentsMargins(14, 12, 14, 12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.title_lbl = QLabel(translate.t("header.account"))
        self.title_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.title_lbl.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.title_lbl.setStyleSheet(
            f"background:transparent;color:{theme.FG};"
            f"font-size:14pt;font-weight:300;"
            f"font-family:'{theme.UI_FONT}'"
        )
        title_col.addWidget(self.title_lbl)
        hdr.addLayout(title_col, 1)

        self.add_btn = QPushButton("+")
        self.add_btn.setStyleSheet(s_plus_btn())
        self.add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.add_btn.clicked.connect(self._on_add)
        hdr.addWidget(self.add_btn)
        v.addWidget(self.header)

        self.list_frame = QFrame()
        self.list_frame.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.list_frame.setAutoFillBackground(False)
        self.list_frame.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list_frame.setStyleSheet(
            f"QFrame{{background:{theme.panel_glass(210)};border-radius:12px}}"
        )
        lf = QVBoxLayout(self.list_frame)
        lf.setContentsMargins(10, 10, 10, 10)
        lf.setSpacing(0)

        self.list = QListWidget()
        self.list.setFont(QFont(theme.UI_FONT, LIST_FONT_SIZE))
        self.list.setWordWrap(False)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.viewport().setAutoFillBackground(False)
        self.list.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_ctx)
        self.list.setItemDelegate(_AccountItemDelegate(self.list))
        self.list.setSpacing(0)
        self.list.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.list.setStyleSheet(
            f"QListWidget{{background:transparent;color:{theme.FG};"
            f"padding:0}}"
            f"QListWidget::item{{padding:0;}}"
        )
        self.list.viewport().setAutoFillBackground(False)
        lf.addWidget(self.list, 1)
        v.addWidget(self.list_frame, 1)

    def _active_index(self):
        try:
            return int(self.settings.get("active_account", 0))
        except (TypeError, ValueError):
            return 0

    def refresh(self):
        self.list.blockSignals(True)
        self.list.clear()
        accs = self.settings.get_accounts()
        active = self._active_index()
        for i, a in enumerate(accs):
            name = a.get("name") or translate.t("account.unnamed")
            it = QListWidgetItem(name)
            it.setData(Qt.ItemDataRole.UserRole + 1, i == active)
            self.list.addItem(it)
        self.list.blockSignals(False)
        if accs:
            row = active if 0 <= active < len(accs) else 0
            self.list.setCurrentRow(row)

    def retranslate_ui(self):
        self.title_lbl.setText(translate.t("header.account"))
        self.refresh()

    def _unstick(self):
        self.setFocus()
        self.activateWindow()
        QApplication.processEvents()

    def restyle(self):
        self.header.setStyleSheet(
            f"QFrame{{background:{theme.panel_glass(220)};border-radius:12px}}"
        )
        self.list_frame.setStyleSheet(
            f"QFrame{{background:{theme.panel_glass(210)};border-radius:12px}}"
        )
        self.list.setStyleSheet(
            f"QListWidget{{background:transparent;color:{theme.FG};"
            f"padding:0}}"
            f"QListWidget::item{{padding:0;}}"
        )
        self.add_btn.setStyleSheet(s_plus_btn())
        self.title_lbl.setStyleSheet(
            f"background:transparent;color:{theme.FG};"
            f"font-size:14pt;font-weight:300;"
            f"font-family:'{theme.UI_FONT}'"
        )
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.title_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.title_lbl.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.refresh()

    def _on_ctx(self, pos: QPoint):
        it = self.list.itemAt(pos)
        if it is None:
            return
        row = self.list.row(it)
        accs = self.settings.get_accounts()
        if not (0 <= row < len(accs)):
            return
        self.list.setCurrentRow(row)
        acc = accs[row]
        active = self._active_index()

        m = QMenu(self)
        m.setStyleSheet(s_popup_menu())

        if row == active:
            a = m.addAction(translate.t("account.in_use"))
            a.setEnabled(False)
        else:
            m.addAction(translate.t("account.use"), self._use_current)

        m.addSeparator()
        if acc.get("type") == "online":
            m.addAction(translate.t("account.sign_out"), self._sign_out_current)
        m.addAction(translate.t("account.rename"), self._rename_current)
        m.addSeparator()
        m.addAction(translate.t("account.remove"), self._remove_current)
        m.exec(self.list.mapToGlobal(pos))

    def _use_current(self):
        row = self.list.currentRow()
        accs = self.settings.get_accounts()
        if not (0 <= row < len(accs)):
            return
        self.settings.set_active_account(row)
        self._log("ok", translate.t("console.now_using", name=accs[row].get("name")))
        self.refresh()
        self._unstick()

    def _sign_out_current(self):
        row = self.list.currentRow()
        accs = self.settings.get_accounts()
        if not (0 <= row < len(accs)):
            return
        if accs[row].get("type") != "online":
            return
        accs[row]["data"] = {}
        self.settings.set_accounts(accs)
        self._log("info", translate.t("console.signed_out", name=accs[row].get("name")))
        self.refresh()
        self._unstick()

    def _rename_current(self):
        row = self.list.currentRow()
        accs = self.settings.get_accounts()
        if not (0 <= row < len(accs)):
            return
        old = accs[row].get("name", "")
        name, ok = QInputDialog.getText(
            self,
            translate.t("account.rename_title"),
            translate.t("account.rename_prompt"),
            text=old,
        )
        if not ok or not name.strip():
            self._unstick()
            return
        accs[row]["name"] = name.strip()
        self.settings.set_accounts(accs)
        self.refresh()
        self._unstick()

    def _remove_current(self):
        row = self.list.currentRow()
        accs = self.settings.get_accounts()
        if not (0 <= row < len(accs)):
            return
        a = accs[row]
        if (
            QMessageBox.question(
                self,
                translate.t("account.remove_title"),
                translate.t("account.remove_confirm", name=a.get("name")),
            )
            != QMessageBox.StandardButton.Yes
        ):
            self._unstick()
            return
        del accs[row]
        self.settings.set_accounts(accs)
        active = self._active_index()
        if active >= len(accs):
            active = max(0, len(accs) - 1)
        self.settings.set_active_account(active)
        self._log("warn", translate.t("console.account_removed", name=a.get("name")))
        self.refresh()
        self._unstick()

    def _on_add(self):
        choice, ok = QInputDialog.getItem(
            self,
            translate.t("account.add_title"),
            translate.t("account.add_type"),
            [translate.t("account.type_online"), translate.t("account.type_offline")],
            0,
            False,
        )
        if not ok:
            self._unstick()
            return
        if choice == translate.t("account.type_offline"):
            self._add_offline()
        else:
            self._add_online()

    def _add_offline(self):
        name, ok = QInputDialog.getText(
            self,
            translate.t("account.offline_title"),
            translate.t("account.offline_prompt"),
        )
        if not ok or not name.strip():
            self._unstick()
            return
        name = name.strip()
        accs = self.settings.get_accounts()
        accs.append({"type": "offline", "name": name, "data": {}})
        self.settings.set_accounts(accs)
        self.settings.set_active_account(len(accs) - 1)
        self._log("ok", translate.t("console.account_added", name=name))
        self.refresh()
        self._unstick()

    def _add_online(self):
        self._log("info", translate.t("console.signin_start"))
        try:
            new = auth.sign_in_webview(parent=self, log=self._log)
        except Exception as e:  # noqa: BLE001
            self._log("error", translate.t("console.signin_failed", err=e))
            self._unstick()
            return
        if not new:
            self._log("warn", translate.t("console.signin_cancelled"))
            self._unstick()
            return
        accs = self.settings.get_accounts()
        accs.append(
            {
                "type": "online",
                "name": new.name,
                "data": new.to_dict(),
            }
        )
        self.settings.set_accounts(accs)
        self.settings.set_active_account(len(accs) - 1)
        self._log("ok", translate.t("console.signed_in", name=new.name))
        self.refresh()
        self._unstick()
