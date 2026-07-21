import sys
import os
from PyQt6.QtCore import QSharedMemory
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PyQt6.QtCore import Qt

SHARED_MEM_KEY = "MyReminderAppSingleInstance"

def is_already_running():
    shared_mem = QSharedMemory(SHARED_MEM_KEY)
    if shared_mem.attach():
        return True
    if not shared_mem.create(1):
        return True
    return False

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def create_app_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#00e5ff"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    painter.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "MR")
    painter.end()
    return QIcon(pixmap)