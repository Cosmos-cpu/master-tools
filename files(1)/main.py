#!/usr/bin/env python3
"""
Hydrus Tag Viewer
=================
A full-window image/video viewer that pulls posts straight from Hydrus
by tag search, lets you flip through them with the arrow keys, and
exposes a tiny local HTTP API so other scripts/programs can add tags to
(or navigate) whatever is currently on screen.

Run with:
    python3 main.py

First run will create a config.json next to this file - press Esc once
the window is open to fill in your Hydrus API URL/key and search tags.

See README.md for full setup instructions.
"""

import os
import sys

from PyQt5.QtWidgets import QApplication

from viewer import MainWindow

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Hydrus Tag Viewer")

    window = MainWindow(CONFIG_PATH)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
