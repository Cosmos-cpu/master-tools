"""
Data models for the Hydrus Multi-Viewer app.

Everything here is a plain dataclass that can be turned into JSON
(via to_dict / from_dict) so the whole layout + hotkey setup can be
saved to disk and reloaded later.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field, asdict
from typing import Any


# ---------------------------------------------------------------------------
# id helpers
# ---------------------------------------------------------------------------

_counter = itertools.count(1)


def next_id() -> str:
    return f"id{next(_counter)}"


# ---------------------------------------------------------------------------
# Hotkey binding
# ---------------------------------------------------------------------------

@dataclass
class HotkeyBinding:
    """
    One hotkey tied to one viewer.

    `action_type` controls what pressing the combo does:
        "http"          - fire an HTTP request (the original, generic action;
                           fill in real Hydrus endpoints whenever you're ready).
        "start_timer"   - start this viewer's auto-advance timer.
        "stop_timer"    - stop this viewer's auto-advance timer.
        "toggle_timer"  - start it if stopped, stop it if running.

    For "http", placeholders you can use inside `url` and `body`, filled in
    at fire time using whatever file is currently showing in the bound
    viewer:
        {api_url}      - the global Hydrus API base URL
        {api_key}      - the global Hydrus API access key
        {file_id}      - current file's numeric id (if known)
        {hash}         - current file's sha256 hash (if known)
    """
    id: str = field(default_factory=next_id)
    name: str = "New Hotkey"
    key_combo: str = ""          # e.g. "ctrl+alt+1"  (as used by the `keyboard` lib)
    action_type: str = "http"    # "http" | "start_timer" | "stop_timer" | "toggle_timer"
    method: str = "GET"          # GET / POST / PATCH / DELETE ... (only used when action_type == "http")
    url: str = ""                # supports {api_url} {api_key} {file_id} {hash}
    body: str = ""                # optional JSON body template, same placeholders
    headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "HotkeyBinding":
        return HotkeyBinding(**d)


ACTION_TYPE_CHOICES: list[tuple[str, str]] = [
    ("HTTP Call", "http"),
    ("Start Timer", "start_timer"),
    ("Stop Timer", "stop_timer"),
    ("Toggle Timer", "toggle_timer"),
]


# ---------------------------------------------------------------------------
# Viewer config
# ---------------------------------------------------------------------------

@dataclass
class ViewerConfig:
    """
    One media viewer. A "viewer" is a single file-display panel: it runs
    its own Hydrus search, holds its own current position in the result
    list, and has its own hotkeys. Multiple viewers can live in the same
    window (a grid), or each in its own window.
    """
    id: str = field(default_factory=next_id)
    label: str = "Viewer"
    window_id: str = ""              # which WindowConfig.id this viewer belongs to
    tags: list[str] = field(default_factory=list)      # hydrus search tags
    file_domain: str = ""            # display name of file domain; "" = combined local
    sort_type: int = 2               # hydrus file_sort_type int, default = import time
    sort_asc: bool = False
    hotkeys: list[HotkeyBinding] = field(default_factory=list)

    # auto-advance timer (all opt-in; a fresh viewer just behaves as before)
    timer_interval_seconds: float = 5.0
    timer_autostart: bool = False        # start the timer automatically once a search loads
    timer_stop_after_post: bool = False  # opt-in: after advancing once, stop and wait for a hotkey/Play press

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["hotkeys"] = [h.to_dict() for h in self.hotkeys]
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "ViewerConfig":
        d = dict(d)
        hotkeys = [HotkeyBinding.from_dict(h) for h in d.pop("hotkeys", [])]
        vc = ViewerConfig(**d)
        vc.hotkeys = hotkeys
        return vc


# ---------------------------------------------------------------------------
# Window config
# ---------------------------------------------------------------------------

@dataclass
class WindowConfig:
    id: str = field(default_factory=next_id)
    title: str = "Viewer Window"
    # ordered list of ViewerConfig ids that live in this window (grid, left->right, top->bottom)
    viewer_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "WindowConfig":
        return WindowConfig(**d)


# ---------------------------------------------------------------------------
# Global app settings
# ---------------------------------------------------------------------------

@dataclass
class AppSettings:
    api_url: str = "http://127.0.0.1:45869"
    api_key: str = ""
    # how often (ms) a viewer re-polls its search for new/changed results (0 = never, manual only)
    refresh_interval_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "AppSettings":
        return AppSettings(**d)


# ---------------------------------------------------------------------------
# Top level app config
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    settings: AppSettings = field(default_factory=AppSettings)
    viewers: list[ViewerConfig] = field(default_factory=list)
    windows: list[WindowConfig] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "settings": self.settings.to_dict(),
            "viewers": [v.to_dict() for v in self.viewers],
            "windows": [w.to_dict() for w in self.windows],
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "AppConfig":
        settings = AppSettings.from_dict(d.get("settings", {}))
        viewers = [ViewerConfig.from_dict(v) for v in d.get("viewers", [])]
        windows = [WindowConfig.from_dict(w) for w in d.get("windows", [])]
        return AppConfig(settings=settings, viewers=viewers, windows=windows)

    # convenience -----------------------------------------------------
    def viewer_by_id(self, vid: str) -> ViewerConfig | None:
        for v in self.viewers:
            if v.id == vid:
                return v
        return None

    def window_by_id(self, wid: str) -> WindowConfig | None:
        for w in self.windows:
            if w.id == wid:
                return w
        return None


# Hydrus file_sort_type choices shown in the UI: (label, value)
SORT_TYPE_CHOICES: list[tuple[str, int]] = [
    ("File size", 0),
    ("Duration", 1),
    ("Import time", 2),
    ("Filetype", 3),
    ("Random", 4),
    ("Width", 5),
    ("Height", 6),
    ("Ratio", 7),
    ("Number of pixels", 8),
    ("Number of tags", 9),
    ("Number of media views", 10),
    ("Total media viewtime", 11),
    ("Approximate bitrate", 12),
    ("Has audio", 13),
    ("Modified time", 14),
    ("Framerate", 15),
    ("Number of frames", 16),
    ("Last viewed time", 18),
    ("Archive timestamp", 19),
]
