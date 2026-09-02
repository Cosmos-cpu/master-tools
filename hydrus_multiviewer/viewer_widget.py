"""
ViewerWidget: one self-contained media panel.

Each ViewerWidget owns its own Hydrus search (tags/sort/file domain),
its own position within the result list, and displays the current file
scaled to fit the panel (letterboxed, aspect ratio preserved) for both
images and video.
"""
from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import Qt, QUrl, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
    QSizePolicy, QMessageBox
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from models import ViewerConfig
from hydrus_api import HydrusClient, HydrusFile, HydrusAPIError
from hotkey_manager import HotkeyManager
from ui_common import ViewerSetupDialog

# Shared background pool for prefetching the next couple of posts so navigation feels instant.
_PREFETCH_EXECUTOR = ThreadPoolExecutor(max_workers=4)
PREFETCH_COUNT = 2


class ScaledImageLabel(QLabel):
    """QLabel that keeps its pixmap scaled to fit (contain), preserving aspect ratio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_pixmap: QPixmap | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(1, 1)
        self.setStyleSheet("background-color: #111;")

    def set_source_pixmap(self, pixmap: QPixmap) -> None:
        self._source_pixmap = pixmap
        self._rescale()

    def clear_image(self) -> None:
        self._source_pixmap = None
        self.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return
        scaled = self._source_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)


class ViewerWidget(QWidget):
    status_changed = pyqtSignal(str)

    def __init__(self, viewer_config: ViewerConfig, client: HydrusClient,
                 hotkey_manager: HotkeyManager, file_domain_choices: list[str] | None = None,
                 parent=None):
        super().__init__(parent)
        self.config = viewer_config
        self.client = client
        self.hotkeys = hotkey_manager
        self.file_domain_choices = file_domain_choices or []

        self.file_ids: list[int] = []
        self.index: int = -1
        self._metadata_cache: dict[int, HydrusFile] = {}
        self._image_cache: dict[int, QImage] = {}   # prefetched, decoded images ready to display instantly
        self._prefetch_inflight: set[int] = set()

        self._build_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer_tick)

        self._reset_display()

        self.hotkeys.local_action.connect(self._on_local_action)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)

        self.header_widget = QWidget()
        header = QHBoxLayout(self.header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(f"<b>{self.config.label}</b>")
        header.addWidget(self.title_label)
        self.position_label = QLabel("0 / 0")
        header.addWidget(self.position_label)
        header.addStretch(1)
        configure_btn = QPushButton("Search / Hotkeys…")
        configure_btn.clicked.connect(self._open_configure_dialog)
        header.addWidget(configure_btn)
        outer.addWidget(self.header_widget)

        # content area: stacked image label / video widget
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.image_label = ScaledImageLabel()
        self.stack.addWidget(self.image_label)

        self.video_widget = QVideoWidget()
        self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.setLoops(QMediaPlayer.Loops.Infinite)
        self.stack.addWidget(self.video_widget)

        outer.addWidget(self.stack, stretch=1)

        self.controls_widget = QWidget()
        controls = QHBoxLayout(self.controls_widget)
        controls.setContentsMargins(0, 0, 0, 0)
        prev_btn = QPushButton("◀ Prev")
        prev_btn.clicked.connect(self.show_prev)
        next_btn = QPushButton("Next ▶")
        next_btn.clicked.connect(self.show_next)
        random_btn = QPushButton("🔀 Random")
        random_btn.clicked.connect(self.show_random)
        self.play_pause_btn = QPushButton("▶ Start Timer")
        self.play_pause_btn.clicked.connect(self.toggle_timer)
        refresh_btn = QPushButton("⟳ Refresh Search")
        refresh_btn.clicked.connect(self.run_search)
        controls.addWidget(prev_btn)
        controls.addWidget(next_btn)
        controls.addWidget(random_btn)
        controls.addWidget(self.play_pause_btn)
        controls.addStretch(1)
        controls.addWidget(refresh_btn)
        outer.addWidget(self.controls_widget)

    def set_chrome_visible(self, visible: bool) -> None:
        """Show/hide everything except the media itself (used for fullscreen/no-UI mode)."""
        self.header_widget.setVisible(visible)
        self.controls_widget.setVisible(visible)

    # ------------------------------------------------------------------
    def _open_configure_dialog(self) -> None:
        dlg = ViewerSetupDialog(self.config, self.file_domain_choices, self)
        if dlg.exec():
            dlg.apply()
            self.title_label.setText(f"<b>{self.config.label}</b>")
            self.run_search()

    # -- search / navigation --------------------------------------------

    def run_search(self) -> None:
        self.timer.stop()
        try:
            file_service_key = None  # resolving name->key is done at the launcher level if needed
            self.file_ids = self.client.search_files(
                tags=self.config.tags,
                sort_type=self.config.sort_type,
                sort_asc=self.config.sort_asc,
                file_service_key=file_service_key,
            )
        except HydrusAPIError as e:
            self.file_ids = []
            self.status_changed.emit(str(e))
            QMessageBox.warning(self, "Search failed", f"{self.config.label}: {e}")
            self._reset_display()
            return
        self._metadata_cache.clear()
        self._image_cache.clear()
        self._prefetch_inflight.clear()
        self.index = 0 if self.file_ids else -1
        self._show_current()
        if self.file_ids and self.config.timer_autostart:
            self.start_timer()

    def show_next(self) -> None:
        if not self.file_ids:
            return
        self.index = (self.index + 1) % len(self.file_ids)
        self._show_current()

    def show_prev(self) -> None:
        if not self.file_ids:
            return
        self.index = (self.index - 1) % len(self.file_ids)
        self._show_current()

    def show_random(self) -> None:
        if not self.file_ids:
            return
        self.index = random.randrange(len(self.file_ids))
        self._show_current()

    # -- auto-advance timer ----------------------------------------------

    def start_timer(self) -> None:
        if not self.file_ids:
            return
        interval_ms = int(max(0.1, self.config.timer_interval_seconds) * 1000)
        self.timer.start(interval_ms)
        self._update_play_button()

    def stop_timer(self) -> None:
        self.timer.stop()
        self._update_play_button()

    def toggle_timer(self) -> None:
        if self.timer.isActive():
            self.stop_timer()
        else:
            self.start_timer()

    def _update_play_button(self) -> None:
        self.play_pause_btn.setText("⏸ Stop Timer" if self.timer.isActive() else "▶ Start Timer")

    def _on_timer_tick(self) -> None:
        self.show_next()
        # opt-in: after each auto-advance, stop and wait for a hotkey/Play press to continue
        if self.config.timer_stop_after_post:
            self.stop_timer()

    def _on_local_action(self, viewer_id: str, action_type: str) -> None:
        if viewer_id != self.config.id:
            return
        if action_type == "start_timer":
            self.start_timer()
        elif action_type == "stop_timer":
            self.stop_timer()
        elif action_type == "toggle_timer":
            self.toggle_timer()

    # -- prefetching -------------------------------------------------

    def _prefetch_next(self) -> None:
        """Kick off background fetches for the next couple of posts so navigation feels instant."""
        if not self.file_ids:
            return
        n = len(self.file_ids)
        for offset in range(1, PREFETCH_COUNT + 1):
            idx = (self.index + offset) % n
            file_id = self.file_ids[idx]
            if file_id in self._image_cache or file_id in self._prefetch_inflight:
                continue
            if file_id in self._metadata_cache and self._metadata_cache[file_id].is_video:
                continue  # nothing more to prefetch for video - it streams from the URL directly
            self._prefetch_inflight.add(file_id)
            _PREFETCH_EXECUTOR.submit(self._prefetch_one, file_id)

    def _prefetch_one(self, file_id: int) -> None:
        try:
            meta = self._metadata_cache.get(file_id)
            if meta is None:
                results = self.client.file_metadata([file_id])
                if results:
                    meta = results[0]
                    self._metadata_cache[file_id] = meta
            if meta and meta.is_image and file_id not in self._image_cache:
                data = self.client.file_bytes(file_id)
                img = QImage()
                if img.loadFromData(data) and not img.isNull():
                    self._image_cache[file_id] = img
        except Exception:
            pass  # best-effort - it'll just be fetched live (with a small delay) if this failed
        finally:
            self._prefetch_inflight.discard(file_id)

    # ------------------------------------------------------------------
    def _reset_display(self) -> None:
        self.position_label.setText("0 / 0")
        self.image_label.clear_image()
        self.media_player.stop()
        self.timer.stop()
        self._update_play_button()
        self.hotkeys.update_current_file(self.config.id, None)

    def _get_metadata(self, file_id: int) -> HydrusFile | None:
        if file_id in self._metadata_cache:
            return self._metadata_cache[file_id]
        try:
            results = self.client.file_metadata([file_id])
        except HydrusAPIError as e:
            self.status_changed.emit(str(e))
            return None
        if not results:
            return None
        self._metadata_cache[file_id] = results[0]
        return results[0]

    def _show_current(self) -> None:
        self.media_player.stop()
        if self.index < 0 or not self.file_ids:
            self._reset_display()
            return

        self.position_label.setText(f"{self.index + 1} / {len(self.file_ids)}")
        file_id = self.file_ids[self.index]
        meta = self._get_metadata(file_id)
        if meta is None:
            return

        self.hotkeys.update_current_file(self.config.id, meta)

        if meta.is_video:
            self.stack.setCurrentWidget(self.video_widget)
            self.media_player.setSource(QUrl(self.client.file_url(file_id)))
            self.media_player.play()
        else:
            self.stack.setCurrentWidget(self.image_label)
            cached_img = self._image_cache.get(file_id)
            if cached_img is not None:
                pix = QPixmap.fromImage(cached_img)
            else:
                try:
                    data = self.client.file_bytes(file_id)
                except HydrusAPIError as e:
                    self.status_changed.emit(str(e))
                    return
                pix = QPixmap()
                pix.loadFromData(data)
            self.image_label.set_source_pixmap(pix)

        # now that the current post is up, warm the cache for what's coming next
        self._prefetch_next()

    # -- external control (used by hotkeys once you wire real actions) ---

    def current_file(self) -> HydrusFile | None:
        if self.index < 0 or not self.file_ids:
            return None
        return self._metadata_cache.get(self.file_ids[self.index])
