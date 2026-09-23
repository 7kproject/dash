import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCursor

from MainWindow import MainWindow


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = MainWindow()

    # Plein écran sans bordure qui s'adapte automatiquement à toute la largeur et hauteur
    ex.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    ex.showMaximized()
    ex.showFullScreen()

    app.setOverrideCursor(QCursor(Qt.BlankCursor))
    sys.exit(app.exec_())

