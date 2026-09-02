"""
The settings dialog that pops up when you press Esc.

Lets you edit everything in config.json without hand-editing the file:
Hydrus connection details, which tags to search for, the local API's
host/port, and whether to start in fullscreen.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from hydrus_client import HydrusClient, HydrusClientError


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        self._config = config

        outer = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.api_url_edit = QLineEdit(config.get("hydrus_api_url", ""))
        self.api_url_edit.setPlaceholderText("http://127.0.0.1:45869")

        self.api_key_edit = QLineEdit(config.get("hydrus_api_key", ""))
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("64-character hex access key")

        self.tag_service_edit = QLineEdit(config.get("tag_service_name", "my tags"))
        self.tag_service_edit.setPlaceholderText("my tags")

        self.tags_edit = QPlainTextEdit()
        self.tags_edit.setPlainText("\n".join(config.get("search_tags", [])))
        self.tags_edit.setPlaceholderText(
            "One tag (or system predicate) per line, e.g.\n"
            "character:samus aran\n"
            "-rating:worksafe\n"
            "system:limit=256"
        )
        self.tags_edit.setFixedHeight(110)

        self.host_edit = QLineEdit(config.get("local_api_host", "127.0.0.1"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(int(config.get("local_api_port", 9876)))

        self.fullscreen_check = QCheckBox()
        self.fullscreen_check.setChecked(bool(config.get("start_fullscreen", False)))

        form.addRow("Hydrus API URL:", self.api_url_edit)
        form.addRow("Hydrus API access key:", self.api_key_edit)
        form.addRow("Tag service name:", self.tag_service_edit)
        form.addRow("Search tags:", self.tags_edit)
        form.addRow("Local API host:", self.host_edit)
        form.addRow("Local API port:", self.port_spin)
        form.addRow("Start in fullscreen:", self.fullscreen_check)

        outer.addLayout(form)

        note = QLabel(
            "Changing the local API host/port takes effect after you restart the app. "
            "Everything else applies immediately on Save."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 11px;")
        outer.addWidget(note)

        test_btn = QPushButton("Test Hydrus connection")
        test_btn.clicked.connect(self._test_connection)
        outer.addWidget(test_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save_clicked)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _test_connection(self):
        client = HydrusClient(self.api_url_edit.text().strip(), self.api_key_edit.text().strip())
        try:
            info = client.verify()
        except HydrusClientError as e:
            QMessageBox.critical(self, "Connection failed", str(e))
            return
        perms = info.get("basic_permissions", [])
        QMessageBox.information(
            self,
            "Connection OK",
            f"Connected to Hydrus.\n\nName: {info.get('name', '?')}\nPermissions: {perms}",
        )

    def _on_save_clicked(self):
        if not self.api_url_edit.text().strip():
            QMessageBox.warning(self, "Missing field", "Please enter a Hydrus API URL.")
            return
        tags = self._parsed_tags()
        if not tags:
            QMessageBox.warning(
                self, "No search tags",
                "Add at least one search tag (e.g. 'system:everything' to browse everything)."
            )
            return
        self.accept()

    def _parsed_tags(self):
        return [line.strip() for line in self.tags_edit.toPlainText().splitlines() if line.strip()]

    def get_config(self):
        """Returns a brand-new config dict reflecting whatever is in the form."""
        new_config = dict(self._config)
        new_config.update({
            "hydrus_api_url": self.api_url_edit.text().strip(),
            "hydrus_api_key": self.api_key_edit.text().strip(),
            "tag_service_name": self.tag_service_edit.text().strip() or "my tags",
            "search_tags": self._parsed_tags(),
            "local_api_host": self.host_edit.text().strip() or "127.0.0.1",
            "local_api_port": self.port_spin.value(),
            "start_fullscreen": self.fullscreen_check.isChecked(),
        })
        return new_config
