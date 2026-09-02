import sys

from PyQt6.QtWidgets import QApplication

from launcher import LauncherWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Hydrus Multi-Viewer")
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
