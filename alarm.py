import datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QGroupBox
)
from PyQt6.QtCore import Qt, QTimer, QObject
from sound import play_alarm_sound, stop_alarm_sound

class AlarmPopup(QDialog):
    def __init__(self, tasks, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self.task_frames = {}
        self.parent_app = parent
        self.setWindowTitle("⏰ Reminder")
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        self.setMinimumWidth(500)
        self.setStyleSheet("""
            QDialog {
                background: #1e1e1e;
                border: 2px solid #ff5555;
                border-radius: 12px;
            }
            QLabel { color: #eee; }
            QGroupBox {
                border: 1px solid #333;
                border-radius: 8px;
                margin-top: 8px;
                padding: 12px;
                background: #252525;
            }
            QGroupBox::title { color: #00e5ff; font-weight: bold; }
            QPushButton {
                background: #3a3a3a;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background: #4a4a4a; }
            QPushButton#paidBtn { background: #2e7d32; }
            QPushButton#paidBtn:hover { background: #388e3c; }
            QPushButton#snoozeBtn { background: #b26a00; }
            QPushButton#snoozeBtn:hover { background: #cc7a00; }
            QPushButton#dismissBtn { background: #7f0000; }
            QPushButton#dismissBtn:hover { background: #990000; }
        """)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel("<b style='color:#ffb300; font-size:16px;'>🔔 Reminders</b>")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(8)

        for task in tasks:
            tid, title, *_ = task
            frame = QGroupBox(f"📌 {title}")
            inner = QVBoxLayout(frame)
            status_lbl = QLabel("🔔 Due now")
            status_lbl.setStyleSheet("color: #ffb300; font-weight: bold;")
            inner.addWidget(status_lbl)

            btn_layout = QHBoxLayout()
            btn_paid = QPushButton("✔ Paid")
            btn_paid.setObjectName("paidBtn")
            btn_snooze_today = QPushButton("🔕 Today")
            btn_snooze = QPushButton("⏱ Snooze (5m)")
            btn_snooze.setObjectName("snoozeBtn")
            btn_dismiss = QPushButton("❌ Dismiss")
            btn_dismiss.setObjectName("dismissBtn")

            btn_paid.clicked.connect(lambda checked, t=tid: self.handle_paid(t))
            btn_snooze_today.clicked.connect(lambda checked, t=tid: self.handle_snooze_today(t))
            btn_snooze.clicked.connect(lambda checked, t=tid: self.handle_snooze(t))
            btn_dismiss.clicked.connect(lambda checked, t=tid: self.handle_dismiss(t))

            btn_layout.addWidget(btn_paid)
            btn_layout.addWidget(btn_snooze_today)
            btn_layout.addWidget(btn_snooze)
            btn_layout.addWidget(btn_dismiss)
            inner.addLayout(btn_layout)
            self.content_layout.addWidget(frame)
            self.task_frames[tid] = (frame, status_lbl)

        scroll.setWidget(content)
        layout.addWidget(scroll)

        btn_dismiss_all = QPushButton("🔇 Dismiss All")
        btn_dismiss_all.setStyleSheet("background: #7f0000; padding: 10px; font-weight: bold;")
        btn_dismiss_all.clicked.connect(self.handle_dismiss_all)
        layout.addWidget(btn_dismiss_all)

        self.adjustSize()

    def remove_task(self, task_id):
        if task_id in self.task_frames:
            frame, _ = self.task_frames.pop(task_id)
            self.content_layout.removeWidget(frame)
            frame.deleteLater()
        if not self.task_frames:
            self.close_ok()

    def handle_paid(self, task_id):
        self.parent_app.db.mark_paid(task_id)
        self.parent_app.alarm_active.discard(task_id)
        self.remove_task(task_id)

    def handle_snooze_today(self, task_id):
        end = datetime.datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
        self.parent_app.db.set_snooze(task_id, end)
        self.parent_app.alarm_active.discard(task_id)
        self.remove_task(task_id)

    def handle_snooze(self, task_id, minutes=5):
        until = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
        self.parent_app.db.set_snooze(task_id, until)
        self.parent_app.alarm_active.discard(task_id)
        self.remove_task(task_id)

    def handle_dismiss(self, task_id):
        self.handle_snooze_today(task_id)

    def handle_dismiss_all(self):
        now = datetime.datetime.now()
        end = now.replace(hour=23, minute=59, second=59, microsecond=0)
        for tid in list(self.task_frames.keys()):
            self.parent_app.db.set_snooze(tid, end)
            self.parent_app.alarm_active.discard(tid)
            self.remove_task(tid)
        self.close_ok()

    def close_ok(self):
        stop_alarm_sound()
        self.parent_app.alarm_popup = None
        self.parent_app.refresh_dashboard()
        self.close()

    def closeEvent(self, event):
        self.handle_dismiss_all()
        event.accept()


class AlarmChecker(QObject):
    def __init__(self, db, main_window):
        super().__init__()
        self.db = db
        self.main_window = main_window
        self.timer = QTimer()
        self.timer.timeout.connect(self.check)
        self.timer.start(10000)

    def check(self):
        if self.main_window.alarm_popup is not None:
            return
        now = datetime.datetime.now()
        today = now.day
        current_ym = now.strftime("%Y-%m")
        tasks = self.db.get_all_tasks()
        triggered = []
        for t in tasks:
            tid, _, _, due_day, _, snooze, start_before, alarm_time, interval, current_due = t
            if not current_due or current_due == "9999-12":
                continue
            if current_ym < current_due:
                continue

            expired_snooze = False
            if snooze:
                try:
                    snooze_dt = datetime.datetime.strptime(snooze, "%Y-%m-%d %H:%M:%S")
                    if now < snooze_dt:
                        continue
                    else:
                        expired_snooze = True
                except:
                    pass

            if not expired_snooze:
                try:
                    ah, am = map(int, alarm_time.split(":"))
                    if not (0 <= ah < 24 and 0 <= am < 60):
                        raise ValueError
                except:
                    ah, am = 9, 0
                if now.hour != ah or now.minute != am:
                    continue

            start_day = max(1, due_day - start_before)
            if today < start_day or today > due_day:
                continue

            if tid in self.main_window.alarm_active:
                continue

            if snooze:
                self.db.clear_snooze(tid)

            self.main_window.alarm_active.add(tid)
            triggered.append(t)

        if triggered:
            self.main_window.show_alarm(triggered)