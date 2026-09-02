"""
A single window holding a grid of one or more ViewerWidgets.

These windows launch "clean" (no per-viewer buttons/labels, no status
bar) since they're meant to just show media. Press:
  F11     - toggle fullscreen
  F1      - toggle the controls back on (search/hotkey button, prev/next,
            timer button, position counter) if you need to tweak something
  Escape  - drop out of fullscreen
"""
from __future__ import annotations

import math

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMainWindow, QWidget, QGridLayout, QStatusBar

from models import WindowConfig, AppConfig
from hydrus_api import HydrusClient
from hotkey_manager import HotkeyManager
from viewer_widget import ViewerWidget


def _grid_dims(n: int) -> tuple[int, int]:
    """Return (rows, cols) that lay n items out roughly square."""
    if n <= 1:
        return (1, 1)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    return (rows, cols)


class ViewerWindow(QMainWindow):
    def __init__(self, window_config: WindowConfig, app_config: AppConfig,
                 client: HydrusClient, hotkey_manager: HotkeyManager,
                 file_domain_choices: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.window_config = window_config
        self.setWindowTitle(window_config.title)
        self.resize(900, 700)

        central = QWidget()
        grid = QGridLayout(central)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        central.setStyleSheet("background-color: black;")
        self.setCentralWidget(central)

        self.viewer_widgets: list[ViewerWidget] = []

        viewers = [app_config.viewer_by_id(vid) for vid in window_config.viewer_ids]
        viewers = [v for v in viewers if v is not None]
        rows, cols = _grid_dims(len(viewers))

        for i, vcfg in enumerate(viewers):
            r, c = divmod(i, cols)
            vw = ViewerWidget(vcfg, client, hotkey_manager, file_domain_choices, self)
            vw.status_changed.connect(self._on_status)
            grid.addWidget(vw, r, c)
            self.viewer_widgets.append(vw)

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        # launch clean: no per-viewer chrome, no status bar - just the media grid
        self._chrome_visible = False
        self._apply_chrome_visibility()

    def _on_status(self, message: str) -> None:
        # only worth showing if the chrome (and thus the status bar) is actually visible
        if self._chrome_visible:
            self.statusBar().showMessage(message, 6000)

    def run_all_searches(self) -> None:
        for vw in self.viewer_widgets:
            vw.run_search()

    # -- no-UI / fullscreen controls --------------------------------------

    def _apply_chrome_visibility(self) -> None:
        for vw in self.viewer_widgets:
            vw.set_chrome_visible(self._chrome_visible)
        self.statusBar().setVisible(self._chrome_visible)

    def toggle_chrome(self) -> None:
        self._chrome_visible = not self._chrome_visible
        self._apply_chrome_visibility()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_F11:
            self.toggle_fullscreen()
            return
        if key == Qt.Key.Key_F1:
            self.toggle_chrome()
            return
        if key == Qt.Key.Key_Escape and self.isFullScreen():
            self.showNormal()
            return
        super().keyPressEvent(event)

