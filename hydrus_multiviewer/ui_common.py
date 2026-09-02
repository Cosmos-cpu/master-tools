"""Reusable widgets shared between the launcher and the in-window 'edit search' dialogs."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPlainTextEdit,
    QComboBox, QCheckBox, QPushButton, QTableWidget, QTableWidgetItem,
    QDialog, QDialogButtonBox, QLineEdit, QHeaderView, QMessageBox, QDoubleSpinBox
)

from models import ViewerConfig, HotkeyBinding, SORT_TYPE_CHOICES, ACTION_TYPE_CHOICES


class SearchEditWidget(QWidget):
    """Tags (one per line) + sort type + sort direction + file domain."""

    def __init__(self, viewer: ViewerConfig, file_domain_choices: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.viewer = viewer
        layout = QFormLayout(self)

        self.tags_edit = QPlainTextEdit()
        self.tags_edit.setPlaceholderText(
            "One tag / system predicate per line, e.g.\n"
            "character:samus aran\n"
            "system:height > 900\n"
            "-system:inbox"
        )
        self.tags_edit.setPlainText("\n".join(viewer.tags))
        self.tags_edit.setFixedHeight(110)
        layout.addRow("Tags / search:", self.tags_edit)

        self.sort_combo = QComboBox()
        for label, value in SORT_TYPE_CHOICES:
            self.sort_combo.addItem(label, value)
        idx = next((i for i, (_, v) in enumerate(SORT_TYPE_CHOICES) if v == viewer.sort_type), 2)
        self.sort_combo.setCurrentIndex(idx)
        layout.addRow("Sort by:", self.sort_combo)

        self.sort_asc_check = QCheckBox("Ascending order")
        self.sort_asc_check.setChecked(viewer.sort_asc)
        layout.addRow("", self.sort_asc_check)

        self.file_domain_combo = QComboBox()
        self.file_domain_combo.setEditable(True)
        self.file_domain_combo.addItem("(combined local file domains)")
        for name in (file_domain_choices or []):
            self.file_domain_combo.addItem(name)
        if viewer.file_domain:
            i = self.file_domain_combo.findText(viewer.file_domain)
            if i >= 0:
                self.file_domain_combo.setCurrentIndex(i)
            else:
                self.file_domain_combo.setEditText(viewer.file_domain)
        layout.addRow("File domain:", self.file_domain_combo)

    def apply_to(self, viewer: ViewerConfig) -> None:
        raw = self.tags_edit.toPlainText()
        viewer.tags = [line.strip() for line in raw.splitlines() if line.strip()]
        viewer.sort_type = self.sort_combo.currentData()
        viewer.sort_asc = self.sort_asc_check.isChecked()
        domain_text = self.file_domain_combo.currentText().strip()
        viewer.file_domain = "" if domain_text.startswith("(combined") else domain_text


class HotkeyEditDialog(QDialog):
    """Edit a single HotkeyBinding: combo, action type, and (for HTTP) method/url/body."""

    def __init__(self, hotkey: HotkeyBinding, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Hotkey")
        self.hotkey = hotkey
        layout = QFormLayout(self)

        self.name_edit = QLineEdit(hotkey.name)
        layout.addRow("Name:", self.name_edit)

        self.combo_edit = QLineEdit(hotkey.key_combo)
        self.combo_edit.setPlaceholderText("e.g. ctrl+alt+1  (see the 'keyboard' library syntax)")
        layout.addRow("Key combo:", self.combo_edit)

        self.action_combo = QComboBox()
        for label, value in ACTION_TYPE_CHOICES:
            self.action_combo.addItem(label, value)
        idx = next((i for i, (_, v) in enumerate(ACTION_TYPE_CHOICES) if v == (hotkey.action_type or "http")), 0)
        self.action_combo.setCurrentIndex(idx)
        self.action_combo.currentIndexChanged.connect(self._update_field_visibility)
        layout.addRow("Action:", self.action_combo)

        self.method_combo = QComboBox()
        self.method_combo.addItems(["GET", "POST", "PUT", "PATCH", "DELETE"])
        self.method_combo.setCurrentText(hotkey.method or "GET")
        self.method_row_label = QLabel("HTTP method:")
        layout.addRow(self.method_row_label, self.method_combo)

        self.url_edit = QLineEdit(hotkey.url)
        self.url_edit.setPlaceholderText("{api_url}/... - placeholders: {api_url} {api_key} {file_id} {hash}")
        self.url_row_label = QLabel("URL:")
        layout.addRow(self.url_row_label, self.url_edit)

        self.body_edit = QPlainTextEdit(hotkey.body)
        self.body_edit.setPlaceholderText('Optional JSON body, e.g. {"hash": "{hash}"}')
        self.body_edit.setFixedHeight(80)
        self.body_row_label = QLabel("Body:")
        layout.addRow(self.body_row_label, self.body_edit)

        self.action_hint = QLabel("")
        self.action_hint.setWordWrap(True)
        layout.addRow(self.action_hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self._update_field_visibility()

    def _update_field_visibility(self) -> None:
        is_http = self.action_combo.currentData() == "http"
        for w in (self.method_row_label, self.method_combo, self.url_row_label,
                  self.url_edit, self.body_row_label, self.body_edit):
            w.setVisible(is_http)
        hints = {
            "start_timer": "Starts this viewer's auto-advance timer.",
            "stop_timer": "Stops this viewer's auto-advance timer.",
            "toggle_timer": "Starts the timer if it's stopped, stops it if it's running.",
        }
        self.action_hint.setText(hints.get(self.action_combo.currentData(), ""))

    def apply(self) -> None:
        self.hotkey.name = self.name_edit.text().strip() or "Hotkey"
        self.hotkey.key_combo = self.combo_edit.text().strip()
        self.hotkey.action_type = self.action_combo.currentData()
        self.hotkey.method = self.method_combo.currentText()
        self.hotkey.url = self.url_edit.text().strip()
        self.hotkey.body = self.body_edit.toPlainText().strip()


class HotkeyTableWidget(QWidget):
    """A table of hotkeys for one viewer, with add/edit/remove."""

    def __init__(self, viewer: ViewerConfig, parent=None):
        super().__init__(parent)
        self.viewer = viewer
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Key combo", "Action", "Method", "URL"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit_selected)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Hotkey")
        add_btn.clicked.connect(self._add)
        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(self._edit_selected)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self._reload()

    def _reload(self) -> None:
        self.table.setRowCount(0)
        for hk in self.viewer.hotkeys:
            self._append_row(hk)

    def _append_row(self, hk: HotkeyBinding) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        action_label = next((label for label, v in ACTION_TYPE_CHOICES if v == (hk.action_type or "http")), "HTTP Call")
        self.table.setItem(row, 0, QTableWidgetItem(hk.name))
        self.table.setItem(row, 1, QTableWidgetItem(hk.key_combo))
        self.table.setItem(row, 2, QTableWidgetItem(action_label))
        self.table.setItem(row, 3, QTableWidgetItem(hk.method if (hk.action_type or "http") == "http" else ""))
        self.table.setItem(row, 4, QTableWidgetItem(hk.url if (hk.action_type or "http") == "http" else ""))

    def _add(self) -> None:
        hk = HotkeyBinding(name=f"Hotkey {len(self.viewer.hotkeys) + 1}")
        dlg = HotkeyEditDialog(hk, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.apply()
            self.viewer.hotkeys.append(hk)
            self._append_row(hk)

    def _selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _edit_selected(self) -> None:
        row = self._selected_row()
        if row < 0 or row >= len(self.viewer.hotkeys):
            return
        hk = self.viewer.hotkeys[row]
        dlg = HotkeyEditDialog(hk, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.apply()
            self._reload()

    def _remove_selected(self) -> None:
        row = self._selected_row()
        if row < 0 or row >= len(self.viewer.hotkeys):
            return
        if QMessageBox.question(self, "Remove hotkey", "Remove the selected hotkey?") == QMessageBox.StandardButton.Yes:
            del self.viewer.hotkeys[row]
            self._reload()


class TimerEditWidget(QWidget):
    """Auto-advance timer settings for one viewer. Everything here is opt-in."""

    def __init__(self, viewer: ViewerConfig, parent=None):
        super().__init__(parent)
        self.viewer = viewer
        layout = QFormLayout(self)

        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.5, 3600.0)
        self.interval_spin.setDecimals(1)
        self.interval_spin.setSuffix(" sec")
        self.interval_spin.setValue(viewer.timer_interval_seconds)
        layout.addRow("Advance every:", self.interval_spin)

        self.autostart_check = QCheckBox("Start automatically as soon as this viewer's search loads")
        self.autostart_check.setChecked(viewer.timer_autostart)
        layout.addRow("", self.autostart_check)

        self.stop_after_post_check = QCheckBox(
            "Stop after each post (opt-in) - once it advances, it stops; press Play "
            "or a 'Start/Toggle Timer' hotkey to advance to the next one"
        )
        self.stop_after_post_check.setChecked(viewer.timer_stop_after_post)
        self.stop_after_post_check.setWordWrap(True)
        layout.addRow("", self.stop_after_post_check)

        hint = QLabel(
            "Tip: add a hotkey with action 'Start Timer' / 'Toggle Timer' below to "
            "kick off (or resume) the timer from anywhere, even with the UI hidden."
        )
        hint.setWordWrap(True)
        layout.addRow(hint)

    def apply_to(self, viewer: ViewerConfig) -> None:
        viewer.timer_interval_seconds = self.interval_spin.value()
        viewer.timer_autostart = self.autostart_check.isChecked()
        viewer.timer_stop_after_post = self.stop_after_post_check.isChecked()


class ViewerSetupDialog(QDialog):
    """Combined 'edit search' + 'edit timer' + 'edit hotkeys' dialog for one viewer."""

    def __init__(self, viewer: ViewerConfig, file_domain_choices: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Configure: {viewer.label}")
        self.resize(540, 680)
        self.viewer = viewer
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>Search</b>"))
        self.search_widget = SearchEditWidget(viewer, file_domain_choices)
        layout.addWidget(self.search_widget)

        layout.addWidget(QLabel("<b>Auto-advance Timer</b>"))
        self.timer_widget = TimerEditWidget(viewer)
        layout.addWidget(self.timer_widget)

        layout.addWidget(QLabel("<b>Hotkeys</b>"))
        self.hotkey_widget = HotkeyTableWidget(viewer)
        layout.addWidget(self.hotkey_widget, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply(self) -> None:
        self.search_widget.apply_to(self.viewer)
        self.timer_widget.apply_to(self.viewer)
