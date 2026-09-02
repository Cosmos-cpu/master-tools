"""
Config loading/saving for the Hydrus Tag Viewer.

Everything the app needs to know lives in a single JSON file (config.json,
next to this script by default). The Settings dialog (opened with Esc)
edits this same structure and writes it straight back to disk.
"""

import json
import os

DEFAULT_CONFIG = {
    # Where your Hydrus client's "Client API" is listening.
    # Hydrus -> services -> manage services -> add -> "Client API"
    "hydrus_api_url": "http://127.0.0.1:45869",

    # The 64-char hex access key Hydrus gives you for this program.
    # Needs at least "Search for Files" and "Edit File Tags" permissions.
    "hydrus_api_key": "",

    # The human-readable name of the *local* tag service tags get added to.
    # This is whatever you called it in Hydrus (default is "my tags").
    "tag_service_name": "my tags",

    # The tags this viewer searches for. One tag (or system predicate) per
    # entry. Example: ["character:samus aran", "-rating:worksafe"]
    "search_tags": ["system:everything"],

    # Where THIS app's own little HTTP API (for adding tags / navigating)
    # will listen. Change the port if 9876 is already taken on your machine.
    "local_api_host": "127.0.0.1",
    "local_api_port": 9876,

    # Open in fullscreen as soon as the app starts.
    "start_fullscreen": False,
}


def load_config(path: str) -> dict:
    """Load config.json, creating it with defaults if it doesn't exist yet.
    Unknown/missing keys are filled in from DEFAULT_CONFIG so old config
    files keep working after this script gets new options."""
    if not os.path.exists(path):
        save_config(path, DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"config file at {path} is not valid JSON: {e}"
            ) from e

    merged = dict(DEFAULT_CONFIG)
    merged.update(data or {})
    return merged


def save_config(path: str, config: dict) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)
