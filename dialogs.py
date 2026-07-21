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
            QDialog { background: #1e1e1e; }
            QLabel { color: #ccc; }
            QLineEdit, QTextEdit, QSpinBox, QComboBox, QTimeEdit {
                background: #2b2b2b;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 6px;
                color: #eee;
            }
            QPushButton { background: #00e5ff; color: #1a1a1a; border: none; border-radius: 6px; padding: 8px 16px; font-weight: bold; }
            QPushButton:hover { background: #00bcd4; }
        """)
        layout = QFormLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        self.title_edit = QLineEdit(task_data[1])
        self.desc_edit = QTextEdit()
        self.desc_edit.setMaximumHeight(80)
        self.desc_edit.setText(task_data[2] if task_data[2] else "")
        self.due_spin = QSpinBox()
        self.due_spin.setRange(1,31)
        self.due_spin.setValue(task_data[3])
        self.start_spin = QSpinBox()
        self.start_spin.setRange(1,30)
        self.start_spin.setValue(task_data[6])
        self.time_edit = QTimeEdit()
        self.time_edit.setTime(QTime.fromString(task_data[7], "HH:mm"))

        interval = task_data[8] if len(task_data) > 8 else 1
        interval_options = [0, 1, 2, 3, 6, 12]
        self.recur_combo = QComboBox()
        self.recur_combo.addItems(["Once (no repeat)", "1 month", "2 months", "3 months", "6 months", "12 months"])
        if interval in interval_options:
            self.recur_combo.setCurrentIndex(interval_options.index(interval))
        else:
            self.recur_combo.setCurrentIndex(1)

        current_due = task_data[9] if len(task_data) > 9 else datetime.datetime.now().strftime("%Y-%m")
        try:
            y, m = map(int, current_due.split("-"))
        except:
            y, m = datetime.datetime.now().year, datetime.datetime.now().month
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2024, 2035)
        self.year_spin.setValue(y)
        self.month_combo = QComboBox()
        self.month_combo.addItems([f"{i:02d}" for i in range(1, 13)])
        self.month_combo.setCurrentIndex(m - 1)

        layout.addRow("Title:", self.title_edit)
        layout.addRow("Description:", self.desc_edit)
        layout.addRow("Due Day:", self.due_spin)
        layout.addRow("Alert Start (days before):", self.start_spin)
        layout.addRow("Alarm Time:", self.time_edit)
        layout.addRow("Recurrence:", self.recur_combo)

        month_layout = QHBoxLayout()
        month_layout.addWidget(QLabel("Year:"))
        month_layout.addWidget(self.year_spin)
        month_layout.addWidget(QLabel("Month:"))
        month_layout.addWidget(self.month_combo)
        layout.addRow("Start Reminder In:", month_layout)

        btn_box = QHBoxLayout()
        btn_save = QPushButton("💾 Save")
        btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_save)
        btn_box.addWidget(btn_cancel)
        layout.addRow(btn_box)

    def get_data(self):
        interval_list = [0, 1, 2, 3, 6, 12]
        interval = interval_list[self.recur_combo.currentIndex()]
        due_month = f"{self.year_spin.value():04d}-{int(self.month_combo.currentText()):02d}"
        return (
            self.task_id,
            self.title_edit.text().strip(),
            self.desc_edit.toPlainText().strip(),
            self.due_spin.value(),
            self.start_spin.value(),
            self.time_edit.time().toString("HH:mm"),
            interval,
            due_month
        )