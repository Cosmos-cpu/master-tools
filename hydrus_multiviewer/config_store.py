"""Load/save AppConfig to a JSON file on disk."""
from __future__ import annotations

import json
import os

from models import AppConfig

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config(path: str = DEFAULT_CONFIG_PATH) -> AppConfig:
    if not os.path.exists(path):
        return AppConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AppConfig.from_dict(data)
    except Exception:
        # corrupt/old file - fall back to a blank config rather than crash on launch
        return AppConfig()


def save_config(config: AppConfig, path: str = DEFAULT_CONFIG_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=2)
