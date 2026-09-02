"""
The main viewer window.

- Shows the current Hydrus post full-size (image, animated gif, or video).
- Left/Right arrow keys move to the previous/next post in the search results.
- Esc opens the Settings dialog (config.json).
- F11 toggles fullscreen.
- A tiny HTTP API (see local_api.py) lets other programs add tags to the
  current post or move forward/backward, exactly like the keyboard does.
"""

import os
import queue
import tempfile

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QThread, Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QMovie, QPixmap
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtWidgets import (
    QDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config import load_config, save_config
from hydrus_client import HydrusClient, HydrusClientError, extract_tag_list
from local_api import action_queue, start_local_api
from settings_dialog import SettingsDialog


class FetchWorker(QThread):
    """Fetches metadata + raw bytes for one file_id off the GUI thread,
    so a slow/large file never freezes the window."""

    finished_ok = pyqtSignal(int, dict, bytes)
    finished_err = pyqtSignal(int, str)

    def __init__(self, client, file_id):
        super().__init__()
        self.client = client
        self.file_id = file_id

    def run(self):
        try:
            meta_list = self.client.get_file_metadata([self.file_id])
            metadata = meta_list[0] if meta_list else {}
            data = self.client.get_file_bytes(self.file_id)
            self.finished_ok.emit(self.file_id, metadata, data)
        except HydrusClientError as e:
            self.finished_err.emit(self.file_id, str(e))
        except Exception as e:  # noqa: BLE001 - surface anything unexpected too
            self.finished_err.emit(self.file_id, f"Unexpected error: {e}")


class MainWindow(QMainWindow):
    def __init__(self, config_path):
        super().__init__()
        self.config_path = config_path
        self.config = load_config(config_path)

        self.client = self._build_client()
        self.tag_service_key_cache = None

        self.file_ids = []
        self.metadata_cache = {}
        self.current_index = -1
        self.current_file_id = None
        self.current_metadata = None

        self._worker = None
        self._temp_dir = tempfile.mkdtemp(prefix="hydrus_viewer_")
        self._temp_files = []
        self._gif_buffer = None  # must outlive the QMovie using it
        self._current_movie = None
        self._current_pixmap = None

        self._build_ui()

        # Drain requests coming in from the local HTTP API.
        self._action_timer = QTimer(self)
        self._action_timer.timeout.connect(self._drain_action_queue)
        self._action_timer.start(50)

        start_local_api(self.config["local_api_host"], self.config["local_api_port"])

        if self.config.get("start_fullscreen"):
            self.showFullScreen()

        if self.config.get("search_tags"):
            self.run_search(self.config["search_tags"])
        else:
            self._show_message("Press Esc to open Settings and enter some search tags.")

    # ---------------------------------------------------------------- UI

    def _build_ui(self):
        self.setWindowTitle("Hydrus Tag Viewer")

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: black;")

        self.video_widget = QVideoWidget()
        self.player = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.player.setVideoOutput(self.video_widget)
        self.player.setMuted(False)
        # Loop videos so you don't have to keep restarting them.
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.image_label)
        self.stack.addWidget(self.video_widget)

        self.info_bar = QLabel("")
        self.info_bar.setStyleSheet(
            "background-color: #1a1a1a; color: #ddd; padding: 4px 8px; font-size: 12px;"
        )
        self.info_bar.setWordWrap(True)
        self.info_bar.setMaximumHeight(48)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.stack, stretch=1)
        layout.addWidget(self.info_bar)
        self.setCentralWidget(central)

        self.setFocusPolicy(Qt.StrongFocus)
        self.resize(1280, 800)

    def _build_client(self):
        return HydrusClient(self.config.get("hydrus_api_url", ""), self.config.get("hydrus_api_key", ""))

    # ----------------------------------------------------------- keys

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self.open_settings()
        elif key == Qt.Key_F11:
            self.toggle_fullscreen()
        elif key == Qt.Key_Right:
            self.go_next()
        elif key == Qt.Key_Left:
            self.go_previous()
        else:
            super().keyPressEvent(event)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def open_settings(self):
        was_fullscreen = self.isFullScreen()
        if was_fullscreen:
            self.showNormal()

        dlg = SettingsDialog(self.config, self)
        if dlg.exec_() == QDialog.Accepted:
            new_config = dlg.get_config()
            tags_changed = new_config.get("search_tags") != self.config.get("search_tags")
            api_changed = (
                new_config.get("hydrus_api_url") != self.config.get("hydrus_api_url")
                or new_config.get("hydrus_api_key") != self.config.get("hydrus_api_key")
            )
            local_api_changed = (
                new_config.get("local_api_host") != self.config.get("local_api_host")
                or new_config.get("local_api_port") != self.config.get("local_api_port")
            )

            self.config = new_config
            save_config(self.config_path, self.config)

            if api_changed:
                self.client = self._build_client()
                self.tag_service_key_cache = None

            if tags_changed:
                self.run_search(self.config["search_tags"])

            if local_api_changed:
                QMessageBox.information(
                    self, "Restart required",
                    "The local API host/port changed. Restart the app for that to take effect."
                )

        if was_fullscreen:
            self.showFullScreen()

    # --------------------------------------------------------- search

    def run_search(self, tags):
        self._show_message(f"Searching for: {', '.join(tags)} ...")
        try:
            file_ids = self.client.search_files(tags)
        except HydrusClientError as e:
            QMessageBox.critical(self, "Search failed", str(e))
            self._show_message("Search failed. Press Esc to check your settings.")
            return

        self.file_ids = file_ids
        self.metadata_cache = {}
        self.current_index = -1
        self.current_file_id = None
        self.current_metadata = None

        if not self.file_ids:
            self._show_message("No files matched those tags. Press Esc to change them.")
            return

        self.load_index(0)

    # ------------------------------------------------------- navigation

    def go_next(self):
        self.navigate("next")

    def go_previous(self):
        self.navigate("previous")

    def navigate(self, direction):
        if not self.file_ids:
            return False
        if direction == "next":
            if self.current_index + 1 >= len(self.file_ids):
                return False
            self.load_index(self.current_index + 1)
            return True
        if direction == "previous":
            if self.current_index - 1 < 0:
                return False
            self.load_index(self.current_index - 1)
            return True
        return False

    def load_index(self, index):
        if not self.file_ids:
            return
        index = max(0, min(index, len(self.file_ids) - 1))
        self.current_index = index
        file_id = self.file_ids[index]

        self._show_message(f"Loading file {index + 1}/{len(self.file_ids)} ...")

        worker = FetchWorker(self.client, file_id)
        worker.finished_ok.connect(self._on_file_loaded)
        worker.finished_err.connect(self._on_file_error)
        worker.finished_ok.connect(worker.deleteLater)
        worker.finished_err.connect(worker.deleteLater)
        self._worker = worker  # keep a reference alive
        worker.start()

    def _on_file_loaded(self, file_id, metadata, data):
        self.current_file_id = file_id
        self.current_metadata = metadata
        self.metadata_cache[file_id] = metadata
        self._display_media(metadata, data)
        self._update_info_bar()

    def _on_file_error(self, file_id, error_text):
        self._show_message(f"Could not load file {file_id}: {error_text}")

    # ------------------------------------------------------- rendering

    def _display_media(self, metadata, data):
        mime = (metadata or {}).get("mime", "") or ""
        ext = (metadata or {}).get("ext", "") or ""

        self.player.stop()

        if mime == "image/gif":
            self._show_gif(data)
        elif mime.startswith("image/"):
            self._show_image(data)
        elif mime.startswith("video/") or mime.startswith("audio/"):
            self._show_video(data, ext)
        else:
            self._show_message(f"Unsupported file type for inline preview: {mime or 'unknown'}")

    def _clear_gif(self):
        """Stop and release any currently-playing animated GIF before we
        show something else. Just calling setMovie(None) detaches the movie
        from the label but doesn't stop its internal frame timer, so do
        that explicitly to avoid leaking a running QMovie/QBuffer."""
        movie = self.image_label.movie()
        if movie is not None:
            movie.stop()
        self.image_label.setMovie(None)
        self._current_movie = None
        if self._gif_buffer is not None:
            self._gif_buffer.close()
            self._gif_buffer = None

    def _show_image(self, data):
        self._clear_gif()
        pix = QPixmap()
        pix.loadFromData(data)
        self._current_pixmap = pix
        self.image_label.setPixmap(self._scaled_pixmap(pix))
        self.stack.setCurrentWidget(self.image_label)

    def _show_gif(self, data):
        self._clear_gif()
        self._gif_buffer = QBuffer()
        self._gif_buffer.setData(QByteArray(data))
        self._gif_buffer.open(QIODevice.ReadOnly)
        movie = QMovie()
        movie.setDevice(self._gif_buffer)
        movie.setCacheMode(QMovie.CacheAll)
        self.image_label.setPixmap(QPixmap())
        self.image_label.setMovie(movie)
        self.stack.setCurrentWidget(self.image_label)
        movie.start()
        self._current_movie = movie  # keep alive

    def _show_video(self, data, ext):
        self._clear_gif()
        if not ext:
            ext = ".bin"
        if not ext.startswith("."):
            ext = "." + ext

        fd, path = tempfile.mkstemp(suffix=ext, dir=self._temp_dir)
        with os.fdopen(fd, "wb") as f:
            f.write(data)

        self._temp_files.append(path)
        # Keep only the current + previous temp file around, clean up the rest.
        while len(self._temp_files) > 2:
            old = self._temp_files.pop(0)
            try:
                os.remove(old)
            except OSError:
                pass

        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        self.stack.setCurrentWidget(self.video_widget)
        self.player.play()

    def _on_media_status_changed(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self.player.setPosition(0)
            self.player.play()

    def _scaled_pixmap(self, pix):
        target = self.image_label.size()
        if pix.isNull() or target.width() <= 0 or target.height() <= 0:
            return pix
        return pix.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.stack.currentWidget() is self.image_label and getattr(self, "_current_pixmap", None):
            if not self._current_pixmap.isNull() and self.image_label.movie() is None:
                self.image_label.setPixmap(self._scaled_pixmap(self._current_pixmap))

    def _show_message(self, text):
        self.player.stop()
        self._clear_gif()
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText(text)
        self.stack.setCurrentWidget(self.image_label)

    def _update_info_bar(self):
        if self.current_metadata is None:
            self.info_bar.setText("")
            return
        tags = extract_tag_list(self.current_metadata)
        tags_text = ", ".join(tags) if tags else "(no tags)"
        position = f"{self.current_index + 1} / {len(self.file_ids)}"
        mime = self.current_metadata.get("mime", "?")
        self.info_bar.setText(f"[{position}]  file_id={self.current_file_id}  mime={mime}\n{tags_text}")

    # --------------------------------------------------- local HTTP API

    def _drain_action_queue(self):
        while True:
            try:
                req = action_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_action(req)

    def _handle_action(self, req):
        try:
            if req.kind == "status":
                req.result = self._status_dict()
            elif req.kind == "add_tags":
                self._add_tags_to_current(req.payload["tags"])
                req.result = {
                    "success": True,
                    "file_id": self.current_file_id,
                    "tags_added": req.payload["tags"],
                }
            elif req.kind == "navigate":
                ok = self.navigate(req.payload["direction"])
                req.result = {
                    "success": ok,
                    "index": self.current_index,
                    "total": len(self.file_ids),
                    "file_id": self.current_file_id,
                }
            elif req.kind == "search":
                self.run_search(req.payload["tags"])
                req.result = {"success": True, "count": len(self.file_ids)}
            else:
                req.result = {"success": False, "error": f"Unknown action '{req.kind}'"}
        except Exception as e:  # noqa: BLE001 - always answer the HTTP request
            req.result = {"success": False, "error": str(e)}
        finally:
            req.event.set()

    def _status_dict(self):
        tags = extract_tag_list(self.current_metadata) if self.current_metadata else []
        return {
            "success": True,
            "file_id": self.current_file_id,
            "index": self.current_index,
            "total": len(self.file_ids),
            "mime": (self.current_metadata or {}).get("mime"),
            "tags": tags,
            "search_tags": self.config.get("search_tags", []),
        }

    def _get_tag_service_key(self):
        if self.tag_service_key_cache:
            return self.tag_service_key_cache
        name = self.config.get("tag_service_name", "my tags")
        key = self.client.get_tag_service_key(name)
        if not key:
            raise RuntimeError(
                f"Could not find a tag service named '{name}' in Hydrus. "
                "Check the name in Settings (Esc) - it must match exactly."
            )
        self.tag_service_key_cache = key
        return key

    def _add_tags_to_current(self, tags):
        if self.current_file_id is None:
            raise RuntimeError("No post is currently being viewed.")
        tag_service_key = self._get_tag_service_key()
        self.client.add_tags(self.current_file_id, tag_service_key, tags)
        # Refresh our local metadata so the on-screen tag list updates too.
        try:
            meta_list = self.client.get_file_metadata([self.current_file_id])
            if meta_list:
                self.current_metadata = meta_list[0]
                self.metadata_cache[self.current_file_id] = self.current_metadata
                self._update_info_bar()
        except HydrusClientError:
            pass  # tags were still added successfully; the on-screen list just won't refresh yet

    # --------------------------------------------------------- cleanup

    def closeEvent(self, event):
        self.player.stop()
        self._clear_gif()
        for path in self._temp_files:
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            os.rmdir(self._temp_dir)
        except OSError:
            pass
        super().closeEvent(event)
