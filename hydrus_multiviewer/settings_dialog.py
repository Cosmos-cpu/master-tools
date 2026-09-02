from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QDialogButtonBox,
    QLabel, QHBoxLayout, QSpinBox
)

from models import AppSettings
from hydrus_api import HydrusClient, HydrusAPIError


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hydrus API Settings")
        self.settings = settings
        self.resize(460, 200)

        layout = QFormLayout(self)

        self.url_edit = QLineEdit(settings.api_url)
        self.url_edit.setPlaceholderText("http://127.0.0.1:45869")
        layout.addRow("Hydrus API URL:", self.url_edit)

        self.key_edit = QLineEdit(settings.api_key)
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("64-char access key from Hydrus > services > review services")
        layout.addRow("API Access Key:", self.key_edit)

        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(0, 3600000)
        self.refresh_spin.setSingleStep(1000)
        self.refresh_spin.setValue(settings.refresh_interval_ms)
        self.refresh_spin.setSuffix(" ms (0 = manual refresh only)")
        layout.addRow("Auto re-search interval:", self.refresh_spin)

        test_row = QHBoxLayout()
        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._test)
        self.test_result = QLabel("")
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, stretch=1)
        layout.addRow(test_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _test(self) -> None:
        client = HydrusClient(self.url_edit.text().strip(), self.key_edit.text().strip())
        try:
            info = client.verify_access_key()
            self.test_result.setText(f"OK - permissions: {info.get('basic_permissions')}")
        except HydrusAPIError as e:
            self.test_result.setText(f"Failed: {e}")

    def apply(self) -> None:
        self.settings.api_url = self.url_edit.text().strip()
        self.settings.api_key = self.key_edit.text().strip()
        self.settings.refresh_interval_ms = self.refresh_spin.value()
