"""
Launcher window.

This is where you:
  1. Pick how many viewers you want.
  2. Assign each viewer to a window number (viewers sharing a window
     number get grouped into the same window's grid; give every viewer
     its own unique number for one-viewer-per-window).
  3. Configure each viewer's search / sort / file domain / hotkeys.
  4. Hit Launch.

Hotkeys are global once launched - they work no matter which window is
focused, because they're tied to the viewer, not the window.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QSpinBox, QHeaderView, QMessageBox, QFileDialog,
    QPlainTextEdit, QDockWidget, QLineEdit
)

from models import AppConfig, ViewerConfig, WindowConfig
from config_store import load_config, save_config, DEFAULT_CONFIG_PATH
from hydrus_api import HydrusClient, HydrusAPIError
from hotkey_manager import HotkeyManager
from settings_dialog import SettingsDialog
from ui_common import ViewerSetupDialog
from viewer_window import ViewerWindow


WINDOW_COL, LABEL_COL, TAGS_COL, CONFIGURE_COL, REMOVE_COL = range(5)


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hydrus Multi-Viewer - Setup")
        self.resize(760, 560)

        self.config: AppConfig = load_config()
        self.hotkey_manager: HotkeyManager | None = None
        self.open_windows: list[ViewerWindow] = []

        self._build_menu()
        self._build_ui()
        self._reload_table()

    # ------------------------------------------------------------------
    def _build_menu(self) -> None:
        menu = self.menuBar()

        file_menu = menu.addMenu("&File")
        save_act = file_menu.addAction("Save Layout")
        save_act.triggered.connect(self._save_layout)
        load_act = file_menu.addAction("Load Layout")
        load_act.triggered.connect(self._load_layout)
        file_menu.addSeparator()
        save_as_act = file_menu.addAction("Save Layout As…")
        save_as_act.triggered.connect(self._save_layout_as)
        open_act = file_menu.addAction("Open Layout…")
        open_act.triggered.connect(self._open_layout)

        settings_menu = menu.addMenu("&Settings")
        api_act = settings_menu.addAction("Hydrus API Settings…")
        api_act.triggered.connect(self._open_settings)

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Number of viewers:"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 64)
        self.count_spin.setValue(max(1, len(self.config.viewers)))
        top_row.addWidget(self.count_spin)
        apply_count_btn = QPushButton("Apply Count")
        apply_count_btn.clicked.connect(self._apply_count)
        top_row.addWidget(apply_count_btn)
        top_row.addStretch(1)
        settings_btn = QPushButton("Hydrus API Settings…")
        settings_btn.clicked.connect(self._open_settings)
        top_row.addWidget(settings_btn)
        layout.addLayout(top_row)

        help_label = QLabel(
            "Give two viewers the same <b>Window #</b> to put them together in one window "
            "(side by side, in a grid). Give a viewer a unique number to put it in its own window."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Window #", "Viewer label", "Tags (preview)", "Configure", "Remove"])
        self.table.horizontalHeader().setSectionResizeMode(TAGS_COL, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, stretch=1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Viewer")
        add_btn.clicked.connect(self._add_viewer_row)
        btn_row.addWidget(add_btn)
        btn_row.addStretch(1)
        launch_btn = QPushButton("Launch")
        launch_btn.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        launch_btn.clicked.connect(self._launch)
        btn_row.addWidget(launch_btn)
        layout.addLayout(btn_row)

        # simple log dock for hotkey activity / connection issues
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(120)
        dock = QDockWidget("Activity Log", self)
        dock.setWidget(self.log_edit)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    # -- table <-> config sync -------------------------------------------

    def _reload_table(self) -> None:
        self.table.setRowCount(0)
        for i, viewer in enumerate(self.config.viewers):
            # viewers with no window assigned yet default to their own unique window number
            default_number = self._window_number_for(viewer) if viewer.window_id else i + 1
            self._append_row(viewer, default_number)
        self.count_spin.blockSignals(True)
        self.count_spin.setValue(max(1, len(self.config.viewers)))
        self.count_spin.blockSignals(False)

    def _window_number_for(self, viewer: ViewerConfig) -> int:
        win = self.config.window_by_id(viewer.window_id)
        if win is None:
            return len(self.config.viewers)
        # derive a stable display number from window order
        for i, w in enumerate(self.config.windows):
            if w.id == win.id:
                return i + 1
        return 1

    def _append_row(self, viewer: ViewerConfig, window_number: int) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        win_spin = QSpinBox()
        win_spin.setRange(1, 64)
        win_spin.setValue(window_number)
        self.table.setCellWidget(row, WINDOW_COL, win_spin)

        label_edit = QLineEdit(viewer.label)
        self.table.setCellWidget(row, LABEL_COL, label_edit)

        tags_preview = QTableWidgetItem(", ".join(viewer.tags) or "(all files)")
        tags_preview.setFlags(tags_preview.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, TAGS_COL, tags_preview)

        configure_btn = QPushButton("Search / Hotkeys…")
        configure_btn.clicked.connect(lambda _, v=viewer, r=row: self._configure_viewer(v, r))
        self.table.setCellWidget(row, CONFIGURE_COL, configure_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda _, v=viewer: self._remove_viewer(v))
        self.table.setCellWidget(row, REMOVE_COL, remove_btn)

    def _configure_viewer(self, viewer: ViewerConfig, row: int) -> None:
        # keep label in sync with whatever's in the row's text field first
        label_widget = self.table.cellWidget(row, LABEL_COL)
        if isinstance(label_widget, QLineEdit):
            viewer.label = label_widget.text().strip() or viewer.label

        domains = self._known_file_domains()
        dlg = ViewerSetupDialog(viewer, domains, self)
        if dlg.exec():
            dlg.apply()
            self.table.item(row, TAGS_COL).setText(", ".join(viewer.tags) or "(all files)")

    def _known_file_domains(self) -> list[str]:
        try:
            client = HydrusClient(self.config.settings.api_url, self.config.settings.api_key, timeout=5)
            return [name for name, _key in client.file_domains()]
        except Exception:
            return []

    def _apply_count(self) -> None:
        target = self.count_spin.value()
        current = len(self.config.viewers)
        if target == current:
            return
        if target > current:
            for i in range(current, target):
                self.config.viewers.append(ViewerConfig(label=f"Viewer {i + 1}"))
        else:
            if QMessageBox.question(
                self, "Remove viewers",
                f"This will remove {current - target} viewer(s) from the bottom of the list (and any hotkeys/search settings on them). Continue?"
            ) != QMessageBox.StandardButton.Yes:
                self.count_spin.setValue(current)
                return
            removed_ids = {v.id for v in self.config.viewers[target:]}
            self.config.viewers = self.config.viewers[:target]
            for w in self.config.windows:
                w.viewer_ids = [vid for vid in w.viewer_ids if vid not in removed_ids]
        self._reload_table()

    def _add_viewer_row(self) -> None:
        self.config.viewers.append(ViewerConfig(label=f"Viewer {len(self.config.viewers) + 1}"))
        self._reload_table()

    def _remove_viewer(self, viewer: ViewerConfig) -> None:
        self.config.viewers = [v for v in self.config.viewers if v.id != viewer.id]
        for w in self.config.windows:
            w.viewer_ids = [vid for vid in w.viewer_ids if vid != viewer.id]
        self._reload_table()

    # -- settings ---------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.config.settings, self)
        if dlg.exec():
            dlg.apply()

    # -- save / load --------------------------------------------------

    def _sync_table_into_config(self) -> None:
        """Read window# and label fields out of the table back into self.config."""
        window_number_to_viewers: dict[int, list[str]] = {}
        for row in range(self.table.rowCount()):
            viewer = self.config.viewers[row]
            win_spin: QSpinBox = self.table.cellWidget(row, WINDOW_COL)
            label_edit: QLineEdit = self.table.cellWidget(row, LABEL_COL)
            viewer.label = label_edit.text().strip() or viewer.label
            window_number_to_viewers.setdefault(win_spin.value(), []).append(viewer.id)

        # rebuild WindowConfig list preserving order of first appearance of each window number
        new_windows: list[WindowConfig] = []
        seen_numbers = sorted(window_number_to_viewers.keys())
        old_windows_by_id = {w.id: w for w in self.config.windows}
        for n in seen_numbers:
            vids = window_number_to_viewers[n]
            # try to reuse an existing WindowConfig id if one of these viewers already had one, for stability
            existing_id = None
            for vid in vids:
                v = self.config.viewer_by_id(vid)
                if v and v.window_id in old_windows_by_id:
                    existing_id = v.window_id
                    break
            wc = WindowConfig(id=existing_id or WindowConfig().id, title=f"Viewer Window {n}", viewer_ids=vids)
            new_windows.append(wc)
            for vid in vids:
                v = self.config.viewer_by_id(vid)
                if v:
                    v.window_id = wc.id

        self.config.windows = new_windows

    def _save_layout(self, path: str | None = None) -> None:
        self._sync_table_into_config()
        save_config(self.config, path or DEFAULT_CONFIG_PATH)
        self._log(f"Saved layout to {path or DEFAULT_CONFIG_PATH}")

    def _load_layout(self, path: str | None = None) -> None:
        self.config = load_config(path or DEFAULT_CONFIG_PATH)
        self._reload_table()
        self._log(f"Loaded layout from {path or DEFAULT_CONFIG_PATH}")

    def _save_layout_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Layout As", "", "JSON files (*.json)")
        if path:
            self._save_layout(path)

    def _open_layout(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Layout", "", "JSON files (*.json)")
        if path:
            self._load_layout(path)

    # -- launch -------------------------------------------------------

    def _log(self, message: str) -> None:
        self.log_edit.appendPlainText(message)

    def _launch(self) -> None:
        self._sync_table_into_config()
        self._save_layout()

        if not self.config.settings.api_url:
            QMessageBox.warning(self, "No API URL", "Set your Hydrus API URL/key first (Settings menu).")
            return

        client = HydrusClient(self.config.settings.api_url, self.config.settings.api_key)
        try:
            client.verify_access_key()
        except HydrusAPIError as e:
            if QMessageBox.question(
                self, "Hydrus connection failed",
                f"Couldn't verify your Hydrus API connection:\n{e}\n\nLaunch anyway?"
            ) != QMessageBox.StandardButton.Yes:
                return

        domains = self._known_file_domains()

        if self.hotkey_manager:
            self.hotkey_manager.shutdown()
        self.hotkey_manager = HotkeyManager(self.config)
        self.hotkey_manager.fired.connect(self._log)
        self.hotkey_manager.error.connect(self._log)
        self.hotkey_manager.rebuild()

        for w in self.open_windows:
            w.close()
        self.open_windows = []

        for window_config in self.config.windows:
            if not window_config.viewer_ids:
                continue
            win = ViewerWindow(window_config, self.config, client, self.hotkey_manager, domains)
            win.run_all_searches()
            win.show()
            self.open_windows.append(win)

        if self.open_windows:
            self._log("Viewer windows launched clean (no UI). Press F1 in a window to show controls, F11 to fullscreen, Esc to leave fullscreen.")
        else:
            QMessageBox.information(self, "Nothing to launch", "Add at least one viewer first.")

    def closeEvent(self, event) -> None:
        if self.hotkey_manager:
            self.hotkey_manager.shutdown()
        for w in self.open_windows:
            w.close()
        super().closeEvent(event)
