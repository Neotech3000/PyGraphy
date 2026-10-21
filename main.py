import sys

from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
)


class PyGraphyWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("PyGraphy")
        self.resize(1100, 700)

        heading = QLabel("Welcome to PyGraphy!")
        self.setCentralWidget(heading)

        self.statusBar().showMessage("Ready")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = PyGraphyWindow()
    window.show()

    sys.exit(app.exec())