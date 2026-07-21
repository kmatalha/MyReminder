import datetime
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QTextEdit, QSpinBox,
    QComboBox, QTimeEdit, QHBoxLayout, QLabel, QPushButton
)
from PyQt6.QtCore import Qt, QTime

class EditTaskDialog(QDialog):
    def __init__(self, task_data, parent=None):
        super().__init__(parent)
        self.task_id = task_data[0]
        self.setWindowTitle("✏️ Edit Task")
        self.setMinimumWidth(450)
        self.setStyleSheet("""
            QDialog {
                background: rgba(20, 20, 30, 0.95);
                border-radius: 24px;
                border: 1px solid rgba(168, 85, 247, 0.2);
            }
            QLabel { color: #ccc; }
            QLineEdit, QTextEdit, QSpinBox, QComboBox, QTimeEdit {
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 12px;
                padding: 8px 12px;
                color: #eee;
            }
            QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus {
                border-color: #a855f7;
            }
            QPushButton {
                background: rgba(168, 85, 247, 0.2);
                color: #c084fc;
                border: 1px solid rgba(168, 85, 247, 0.3);
                border-radius: 40px;
                padding: 8px 20px;
                font-weight: 600;
            }
            QPushButton:hover { background: rgba(168, 85, 247, 0.3); }
            QPushButton#cancelBtn { background: transparent; border-color: rgba(255,255,255,0.1); color: #aaa; }
            QPushButton#cancelBtn:hover { background: rgba(255,255,255,0.05); }
        """)
        # ... rest of EditTaskDialog unchanged