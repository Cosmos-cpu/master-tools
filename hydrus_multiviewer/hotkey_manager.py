"""
Global hotkey manager.

Hotkeys are registered at the OS level (via the `keyboard` library), so
they fire no matter which of your viewer windows currently has focus -
that's what makes "window A is focused but I hit window B's hotkey"
behave correctly. There is nothing window-specific about a hotkey; it's
tied to a *viewer*, and viewers just happen to live inside windows.

Each hotkey's action is generic on purpose: it fires an HTTP request to
a URL you configure, with an optional method/body/headers. Placeholders
{api_url} {api_key} {file_id} {hash} get filled in from the viewer's
currently displayed file at the moment the hotkey is pressed.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

try:
    import keyboard  # global OS-level hotkeys
    KEYBOARD_AVAILABLE = True
    KEYBOARD_IMPORT_ERROR = ""
except Exception as e:  # pragma: no cover - platform dependent
    keyboard = None
    KEYBOARD_AVAILABLE = False
    KEYBOARD_IMPORT_ERROR = str(e)

import requests

from models import AppConfig, HotkeyBinding
from hydrus_api import HydrusFile


class HotkeyManager(QObject):
    fired = pyqtSignal(str)          # human readable log line, e.g. "Next (Viewer 1) -> 200 OK"
    error = pyqtSignal(str)
    local_action = pyqtSignal(str, str)   # viewer_id, action_type - for start/stop/toggle timer etc.

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self._current_file: dict[str, Optional[HydrusFile]] = {}
        self._registered_combos: list[str] = []
        self._executor = ThreadPoolExecutor(max_workers=4)

    # -- state kept up to date by viewer widgets ---------------------------

    def update_current_file(self, viewer_id: str, file: Optional[HydrusFile]) -> None:
        self._current_file[viewer_id] = file

    # -- (re)binding all hotkeys from the current config -------------------

    def rebuild(self) -> None:
        self.unbind_all()
        if not KEYBOARD_AVAILABLE:
            self.error.emit(
                "Global hotkeys unavailable: the 'keyboard' package could not be loaded "
                f"({KEYBOARD_IMPORT_ERROR}). On Linux this usually needs root/uinput access; "
                "hotkeys are not supported on macOS with this library. The viewers will still work."
            )
            return
        for viewer in self.config.viewers:
            for hk in viewer.hotkeys:
                if not hk.key_combo.strip():
                    continue
                try:
                    keyboard.add_hotkey(
                        hk.key_combo.strip(),
                        self._make_callback(viewer.id, hk),
                        suppress=False,
                    )
                    self._registered_combos.append(hk.key_combo.strip())
                except Exception as e:
                    self.error.emit(f"Could not bind hotkey '{hk.key_combo}' ({hk.name}): {e}")

    def unbind_all(self) -> None:
        if KEYBOARD_AVAILABLE:
            for combo in self._registered_combos:
                try:
                    keyboard.remove_hotkey(combo)
                except Exception:
                    pass
        self._registered_combos.clear()

    # -- firing --------------------------------------------------------

    def _make_callback(self, viewer_id: str, hk: HotkeyBinding):
        action_type = hk.action_type or "http"

        def _cb():
            if action_type == "http":
                self._executor.submit(self._fire, viewer_id, hk)
            else:
                # local actions (timer control etc.) - emitting is thread-safe;
                # Qt auto-queues this onto the receiving widget's (GUI) thread.
                self.local_action.emit(viewer_id, action_type)
                self.fired.emit(f"[{hk.name}] {action_type} -> {viewer_id}")

        return _cb

    def _fill(self, template: str, viewer_id: str) -> str:
        file = self._current_file.get(viewer_id)
        return (
            template.replace("{api_url}", self.config.settings.api_url)
            .replace("{api_key}", self.config.settings.api_key)
            .replace("{file_id}", str(file.file_id) if file else "")
            .replace("{hash}", file.hash if file else "")
        )

    def _fire(self, viewer_id: str, hk: HotkeyBinding) -> None:
        try:
            url = self._fill(hk.url, viewer_id)
            headers = {k: self._fill(v, viewer_id) for k, v in hk.headers.items()}
            body_text = self._fill(hk.body, viewer_id) if hk.body.strip() else None

            kwargs = {"headers": headers, "timeout": 10}
            if body_text:
                try:
                    kwargs["json"] = json.loads(body_text)
                except json.JSONDecodeError:
                    kwargs["data"] = body_text

            resp = requests.request(hk.method.upper() or "GET", url, **kwargs)
            self.fired.emit(f"[{hk.name}] {hk.method.upper()} {url} -> {resp.status_code}")
        except Exception as e:
            self.error.emit(f"[{hk.name}] hotkey action failed: {e}")

    def shutdown(self) -> None:
        self.unbind_all()
        self._executor.shutdown(wait=False, cancel_futures=True)
