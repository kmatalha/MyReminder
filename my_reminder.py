import sys
import os
import sqlite3
import datetime
import struct
import wave
import io
import winreg
import csv
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QVBoxLayout, QHBoxLayout,
    QWidget, QLabel, QPushButton, QListWidget, QListWidgetItem, QFormLayout,
    QSpinBox, QLineEdit, QTextEdit, QMessageBox, QDialog, QSystemTrayIcon,
    QMenu, QFileDialog, QCheckBox, QTimeEdit, QGroupBox, QScrollArea, QComboBox,
    QFrame
)
from PyQt6.QtCore import Qt, QTimer, QTime, QObject, QSharedMemory
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
import winsound

# ===================== SINGLE INSTANCE =====================
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
    icon_path = os.path.join(get_app_dir(), "app.ico")
    if os.path.exists(icon_path):
        return QIcon(icon_path)
    # fallback generated icon
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#a855f7"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    painter.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "MR")
    painter.end()
    return QIcon(pixmap)

def enable_startup():
    try:
        exe_path = sys.executable
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, "MyReminder", 0, winreg.REG_SZ, exe_path)
        winreg.CloseKey(key)
        return True
    except Exception as e:
        QMessageBox.critical(None, "Startup Error", f"Failed to set startup: {str(e)}")
        return False

def disable_startup():
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.DeleteValue(key, "MyReminder")
        winreg.CloseKey(key)
        return True
    except:
        return True

# ===================== SOUND =====================
def generate_beep_wav():
    sample_rate = 44100
    freq = 440
    duration_ms = 800
    samples = int(sample_rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for i in range(samples):
            val = int(32767.0 * 0.5 * (
                __import__('math').sin(2 * __import__('math').pi * freq * i / sample_rate)
            ))
            wav_file.writeframesraw(struct.pack('<h', val))
    buf.seek(0)
    return buf.read()

BEEP_WAV = generate_beep_wav()

def play_alarm_sound(file_path=None):
    try:
        winsound.PlaySound(None, winsound.SND_ASYNC)
        if file_path and os.path.exists(file_path):
            winsound.PlaySound(file_path, winsound.SND_ASYNC | winsound.SND_LOOP)
        else:
            winsound.PlaySound(BEEP_WAV, winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_LOOP)
    except:
        pass

def stop_alarm_sound():
    try:
        winsound.PlaySound(None, winsound.SND_ASYNC)
    except:
        pass

# ===================== DATABASE =====================
class DatabaseManager:
    def __init__(self):
        app_dir = get_app_dir()
        db_path = os.path.join(app_dir, "my_reminder.db")
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
        self._migrate_add_columns()
        self._migrate_existing_data()
        self._normalize_alarm_times()
        self._insert_settings_defaults()

    def _create_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                due_day INTEGER NOT NULL,
                paid_month TEXT,
                snooze_until TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS paid_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                year_month TEXT,
                paid_timestamp TEXT,
                FOREIGN KEY(task_id) REFERENCES tasks(id)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        self.conn.commit()

    def _migrate_add_columns(self):
        cols = [row[1] for row in self.cursor.execute("PRAGMA table_info(tasks)").fetchall()]
        if "start_days_before" not in cols:
            self.cursor.execute("ALTER TABLE tasks ADD COLUMN start_days_before INTEGER DEFAULT 12")
        if "alarm_time" not in cols:
            self.cursor.execute("ALTER TABLE tasks ADD COLUMN alarm_time TEXT DEFAULT '09:00'")
        if "recurrence_interval" not in cols:
            self.cursor.execute("ALTER TABLE tasks ADD COLUMN recurrence_interval INTEGER DEFAULT 1")
        if "current_due_month" not in cols:
            self.cursor.execute("ALTER TABLE tasks ADD COLUMN current_due_month TEXT")
        self.conn.commit()

    def _migrate_existing_data(self):
        self.cursor.execute("SELECT id, paid_month FROM tasks WHERE current_due_month IS NULL")
        rows = self.cursor.fetchall()
        now = datetime.datetime.now()
        for row in rows:
            tid, paid_month = row
            if paid_month and paid_month != "":
                try:
                    y, m = map(int, paid_month.split("-"))
                    if m == 12:
                        y += 1
                        m = 1
                    else:
                        m += 1
                    next_due = f"{y:04d}-{m:02d}"
                except:
                    next_due = now.strftime("%Y-%m")
            else:
                next_due = now.strftime("%Y-%m")
            self.cursor.execute("UPDATE tasks SET current_due_month=? WHERE id=?", (next_due, tid))
        self.conn.commit()

    def _normalize_alarm_times(self):
        self.cursor.execute("SELECT id, alarm_time FROM tasks")
        rows = self.cursor.fetchall()
        for tid, at in rows:
            normalized = self._normalize_time(at)
            if normalized != at:
                self.cursor.execute("UPDATE tasks SET alarm_time=? WHERE id=?", (normalized, tid))
        self.conn.commit()

    def _normalize_time(self, time_str):
        if not time_str:
            return "09:00"
        for fmt in ("%H:%M", "%I:%M %p", "%H:%M:%S", "%I:%M:%S %p"):
            try:
                dt = datetime.datetime.strptime(time_str, fmt)
                return dt.strftime("%H:%M")
            except ValueError:
                continue
        try:
            parts = time_str.split(":")
            if len(parts) == 2:
                h = int(parts[0])
                m = int(parts[1])
                if 0 <= h < 24 and 0 <= m < 60:
                    return f"{h:02d}:{m:02d}"
        except:
            pass
        return "09:00"

    def _insert_settings_defaults(self):
        defaults = {
            "alarm_sound_path": "",
            "default_snooze_minutes": "10",
            "desktop_notifications": "1",
            "auto_start": "0"
        }
        for key, val in defaults.items():
            self.cursor.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, val)
            )
        self.conn.commit()

    def get_setting(self, key):
        self.cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = self.cursor.fetchone()
        return row[0] if row else ""

    def set_setting(self, key, value):
        self.cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        self.conn.commit()

    def reset_settings(self):
        defaults = {
            "alarm_sound_path": "",
            "default_snooze_minutes": "10",
            "desktop_notifications": "1",
            "auto_start": "0"
        }
        for key, val in defaults.items():
            self.cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, val)
            )
        self.conn.commit()

    def add_task(self, title, description, due_day, start_days_before, alarm_time, recurrence_interval, due_month):
        alarm_time = self._normalize_time(alarm_time)
        self.cursor.execute(
            """INSERT INTO tasks 
               (title, description, due_day, start_days_before, alarm_time, recurrence_interval, current_due_month)
               VALUES (?,?,?,?,?,?,?)""",
            (title, description, due_day, start_days_before, alarm_time, recurrence_interval, due_month)
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def update_task(self, task_id, title, description, due_day, start_days_before, alarm_time, recurrence_interval, due_month):
        alarm_time = self._normalize_time(alarm_time)
        self.cursor.execute("""
            UPDATE tasks 
            SET title=?, description=?, due_day=?, start_days_before=?, alarm_time=?, recurrence_interval=?, current_due_month=?
            WHERE id=?
        """, (title, description, due_day, start_days_before, alarm_time, recurrence_interval, due_month, task_id))
        self.conn.commit()

    def delete_task(self, task_id):
        self.cursor.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.cursor.execute("DELETE FROM paid_history WHERE task_id=?", (task_id,))
        self.conn.commit()

    def clear_done_tasks(self):
        self.cursor.execute("DELETE FROM tasks WHERE current_due_month='9999-12'")
        self.conn.commit()

    def get_all_tasks(self):
        self.cursor.execute(
            """SELECT id, title, description, due_day, paid_month, snooze_until,
                      start_days_before, alarm_time, recurrence_interval, current_due_month
               FROM tasks"""
        )
        return self.cursor.fetchall()

    def mark_paid(self, task_id):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute("SELECT recurrence_interval, current_due_month FROM tasks WHERE id=?", (task_id,))
        row = self.cursor.fetchone()
        if not row:
            return
        interval, due_month_str = row
        self.cursor.execute(
            "INSERT INTO paid_history (task_id, year_month, paid_timestamp) VALUES (?,?,?)",
            (task_id, due_month_str, now_str)
        )
        if interval == 0:
            new_due = "9999-12"
        else:
            try:
                y, m = map(int, due_month_str.split("-"))
                for _ in range(interval):
                    m += 1
                    if m > 12:
                        m = 1
                        y += 1
                new_due = f"{y:04d}-{m:02d}"
            except:
                now = datetime.datetime.now()
                y, m = now.year, now.month
                for _ in range(interval):
                    m += 1
                    if m > 12:
                        m = 1
                        y += 1
                new_due = f"{y:04d}-{m:02d}"
        self.cursor.execute(
            "UPDATE tasks SET current_due_month=?, snooze_until=NULL WHERE id=?",
            (new_due, task_id)
        )
        self.conn.commit()

    def mark_unpaid(self, task_id):
        self.cursor.execute(
            "SELECT year_month FROM paid_history WHERE task_id=? ORDER BY paid_timestamp DESC LIMIT 1",
            (task_id,)
        )
        row = self.cursor.fetchone()
        if not row:
            current = datetime.datetime.now().strftime("%Y-%m")
            self.cursor.execute("UPDATE tasks SET current_due_month=? WHERE id=?", (current, task_id))
            self.conn.commit()
            return
        last_paid_month = row[0]
        self.cursor.execute(
            "DELETE FROM paid_history WHERE task_id=? AND year_month=? AND paid_timestamp = (SELECT paid_timestamp FROM paid_history WHERE task_id=? ORDER BY paid_timestamp DESC LIMIT 1)",
            (task_id, last_paid_month, task_id)
        )
        self.cursor.execute("UPDATE tasks SET current_due_month=? WHERE id=?", (last_paid_month, task_id))
        self.conn.commit()

    def set_snooze(self, task_id, until_dt):
        self.cursor.execute(
            "UPDATE tasks SET snooze_until=? WHERE id=?",
            (until_dt.strftime("%Y-%m-%d %H:%M:%S"), task_id)
        )
        self.conn.commit()

    def clear_snooze(self, task_id):
        self.cursor.execute("UPDATE tasks SET snooze_until=NULL WHERE id=?", (task_id,))
        self.conn.commit()

    def get_paid_history_grouped_by_month(self):
        self.cursor.execute("""
            SELECT year_month, GROUP_CONCAT(title, ', ')
            FROM paid_history JOIN tasks ON paid_history.task_id = tasks.id
            GROUP BY year_month ORDER BY year_month DESC
        """)
        return self.cursor.fetchall()

    def get_paid_history_all(self):
        self.cursor.execute("""
            SELECT year_month, title, paid_timestamp
            FROM paid_history JOIN tasks ON paid_history.task_id = tasks.id
            ORDER BY paid_timestamp DESC
        """)
        return self.cursor.fetchall()

    def backup_database(self, target_path):
        self.conn.close()
        import shutil
        app_dir = get_app_dir()
        source = os.path.join(app_dir, "my_reminder.db")
        shutil.copy2(source, target_path)
        db_path = os.path.join(app_dir, "my_reminder.db")
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()

    def restore_database(self, source_path):
        self.conn.close()
        import shutil
        app_dir = get_app_dir()
        target = os.path.join(app_dir, "my_reminder.db")
        shutil.copy2(source_path, target)
        self.conn = sqlite3.connect(target, check_same_thread=False)
        self.cursor = self.conn.cursor()

# ===================== ALARM POPUP & CHECKER =====================
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
            QDialog { background: rgba(20,20,30,0.92); border: 1px solid rgba(168,85,247,0.3); border-radius: 24px; }
            QLabel { color: #eee; }
            QGroupBox { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; margin-top: 8px; padding: 12px; }
            QGroupBox::title { color: #c084fc; font-weight: 600; }
            QPushButton { background: rgba(255,255,255,0.06); color: white; border: 1px solid rgba(255,255,255,0.08); border-radius: 40px; padding: 8px 18px; font-weight: 600; font-size: 13px; }
            QPushButton:hover { background: rgba(255,255,255,0.12); }
            QPushButton#paidBtn { background: rgba(52,211,153,0.2); color: #34d399; border-color: rgba(52,211,153,0.3); }
            QPushButton#paidBtn:hover { background: rgba(52,211,153,0.3); }
            QPushButton#snoozeBtn { background: rgba(251,191,36,0.15); color: #fbbf24; border-color: rgba(251,191,36,0.2); }
            QPushButton#snoozeBtn:hover { background: rgba(251,191,36,0.25); }
            QPushButton#dismissBtn { background: rgba(248,113,113,0.15); color: #f87171; border-color: rgba(248,113,113,0.2); }
            QPushButton#dismissBtn:hover { background: rgba(248,113,113,0.25); }
        """)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20,20,20,20)
        header = QLabel("<b style='color:#c084fc; font-size:18px;'>🔔 Reminders</b>")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(10)
        for task in tasks:
            tid, title, *_ = task
            frame = QGroupBox(f"📌 {title}")
            inner = QVBoxLayout(frame)
            status_lbl = QLabel("🔔 Due now")
            status_lbl.setStyleSheet("color: #fbbf24; font-weight: bold;")
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
        btn_dismiss_all.setStyleSheet("QPushButton { background: rgba(248,113,113,0.15); color: #f87171; border: 1px solid rgba(248,113,113,0.2); padding: 12px; font-weight: bold; border-radius: 40px; } QPushButton:hover { background: rgba(248,113,113,0.25); }")
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
                    if len(alarm_time) == 5 and alarm_time[2] == ':':
                        ah, am = int(alarm_time[:2]), int(alarm_time[3:])
                    else:
                        parts = alarm_time.split(":")
                        if len(parts) == 2:
                            ah, am = int(parts[0]), int(parts[1])
                        else:
                            raise ValueError
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

# ===================== EDIT TASK DIALOG =====================
class EditTaskDialog(QDialog):
    def __init__(self, task_data, parent=None):
        super().__init__(parent)
        self.task_id = task_data[0]
        self.setWindowTitle("✏️ Edit Task")
        self.setMinimumWidth(450)
        self.setStyleSheet("""
            QDialog { background: rgba(20,20,30,0.95); border-radius: 24px; border: 1px solid rgba(168,85,247,0.2); }
            QLabel { color: #ccc; }
            QLineEdit, QTextEdit, QSpinBox, QComboBox, QTimeEdit { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 8px 12px; color: #eee; }
            QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus { border-color: #a855f7; }
            QPushButton { background: rgba(168,85,247,0.2); color: #c084fc; border: 1px solid rgba(168,85,247,0.3); border-radius: 40px; padding: 8px 20px; font-weight: 600; }
            QPushButton:hover { background: rgba(168,85,247,0.3); }
            QPushButton#cancelBtn { background: transparent; border-color: rgba(255,255,255,0.1); color: #aaa; }
            QPushButton#cancelBtn:hover { background: rgba(255,255,255,0.05); }
        """)
        layout = QFormLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20,20,20,20)

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
        try:
            self.time_edit.setTime(QTime.fromString(task_data[7], "HH:mm"))
        except:
            self.time_edit.setTime(QTime(9,0))

        interval = task_data[8] if len(task_data) > 8 else 1
        interval_options = [0,1,2,3,6,12]
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
        month_names = ["January", "February", "March", "April", "May", "June",
                       "July", "August", "September", "October", "November", "December"]
        self.month_combo = QComboBox()
        self.month_combo.addItems(month_names)
        self.month_combo.setCurrentIndex(m-1)

        layout.addRow("Title:", self.title_edit)
        layout.addRow("Description:", self.desc_edit)
        layout.addRow("Due Day:", self.due_spin)
        layout.addRow("Alert Start (days before):", self.start_spin)
        layout.addRow("Alarm Time:", self.time_edit)
        layout.addRow("Recurrence:", self.recur_combo)

        # Stylish date box
        date_box = QFrame()
        date_box.setStyleSheet("""
            QFrame {
                background: rgba(168, 85, 247, 0.08);
                border: 1px solid rgba(168, 85, 247, 0.2);
                border-radius: 12px;
                padding: 8px 12px;
            }
        """)
        date_layout = QHBoxLayout(date_box)
        date_layout.setContentsMargins(8, 4, 8, 4)
        date_layout.setSpacing(10)
        date_icon = QLabel("📅")
        date_icon.setStyleSheet("font-size: 18px;")
        date_layout.addWidget(date_icon)
        date_layout.addWidget(QLabel("Year:"))
        date_layout.addWidget(self.year_spin)
        date_layout.addWidget(QLabel("Month:"))
        date_layout.addWidget(self.month_combo)
        date_layout.addStretch()

        layout.addRow("Start Reminder In:", date_box)

        btn_box = QHBoxLayout()
        btn_save = QPushButton("💾 Save")
        btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("cancelBtn")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_save)
        btn_box.addWidget(btn_cancel)
        layout.addRow(btn_box)

    def get_data(self):
        interval_list = [0,1,2,3,6,12]
        interval = interval_list[self.recur_combo.currentIndex()]
        month_index = self.month_combo.currentIndex() + 1
        due_month = f"{self.year_spin.value():04d}-{month_index:02d}"
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

# ===================== MAIN WINDOW =====================
class MyReminderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = DatabaseManager()
        self.setWindowTitle("My Reminder")
        self.resize(1000, 700)
        self.setWindowIcon(create_app_icon())
        self.setStyleSheet(self._style())
        self.alarm_active = set()
        self.alarm_popup = None

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(create_app_icon())
        tray_menu = QMenu()
        tray_menu.addAction("📊 Show", self.show_window)
        tray_menu.addAction("🚪 Exit", self.quit_app)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.show()
        if self.db.get_setting("auto_start") == "1":
            enable_startup()

        central = QWidget()
        central.setObjectName("mainWindow")
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0,0,0,0)
        main_layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setSpacing(8)
        sb_layout.setContentsMargins(20,28,20,28)
        title_lbl = QLabel("✨ Remind")
        title_lbl.setStyleSheet("""
            font-size: 20px; font-weight: 700;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 #a855f7, stop:1 #ec4899);
            color: transparent;
        """)
        sb_layout.addWidget(title_lbl)
        sb_layout.addSpacing(24)
        self.btn_dash = self._nav_button("📊", "Dashboard", 0)
        self.btn_hist = self._nav_button("📅", "History", 1)
        self.btn_add = self._nav_button("➕", "New", 2)
        self.btn_sett = self._nav_button("⚙", "Settings", 3)
        sb_layout.addWidget(self.btn_dash)
        sb_layout.addWidget(self.btn_hist)
        sb_layout.addWidget(self.btn_add)
        sb_layout.addWidget(self.btn_sett)
        sb_layout.addStretch()

        self.stack = QStackedWidget()
        self.stack.addWidget(self._dashboard_page())
        self.stack.addWidget(self._history_page())
        self.stack.addWidget(self._add_task_page())
        self.stack.addWidget(self._settings_page())

        main_layout.addWidget(sidebar)
        main_layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.btn_dash.clicked.connect(lambda: self.switch_page(0))
        self.btn_hist.clicked.connect(lambda: self.switch_page(1))
        self.btn_add.clicked.connect(lambda: self.switch_page(2))
        self.btn_sett.clicked.connect(lambda: self.switch_page(3))

        self.switch_page(0)

        self.checker = AlarmChecker(self.db, self)
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_dashboard)
        self.refresh_timer.start(60000)
        self.refresh_dashboard()

    def _style(self):
        return """
            QMainWindow, QWidget#mainWindow { background: rgba(15,15,26,0.92); }
            QWidget#sidebar { background: rgba(255,255,255,0.04); border-right: 1px solid rgba(255,255,255,0.06); }
            QPushButton#navBtn { text-align: left; padding: 12px 16px; border: none; border-radius: 16px; font-size: 14px; font-weight: 500; color: rgba(255,255,255,0.6); background: transparent; }
            QPushButton#navBtn:hover { background: rgba(255,255,255,0.05); color: #fff; }
            QPushButton#navBtn:checked { background: rgba(168,85,247,0.25); color: #fff; border: 1px solid rgba(168,85,247,0.3); }
            QScrollArea { border: none; background: transparent; }
            QLabel { color: #ddd; }
            QListWidget { background: transparent; border: none; outline: none; padding: 4px; }
            QListWidget::item { border: none; padding: 2px; }
            QListWidget::item:selected { background: rgba(168,85,247,0.15); border-radius: 12px; }
            QGroupBox { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); border-radius: 16px; margin-top: 10px; padding-top: 14px; }
            QGroupBox::title { color: #c084fc; }
            QLineEdit, QTextEdit, QSpinBox, QComboBox, QTimeEdit { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 8px 12px; color: #eee; }
            QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus { border-color: #a855f7; }
            QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #a855f7, stop:1 #ec4899); color: #fff; border: none; border-radius: 40px; padding: 10px 20px; font-weight: 600; }
            QPushButton:hover { opacity: 0.9; }
            QPushButton:pressed { opacity: 0.7; }
            QPushButton#danger { background: rgba(248,113,113,0.15); color: #f87171; border: 1px solid rgba(248,113,113,0.2); }
            QPushButton#danger:hover { background: rgba(248,113,113,0.25); }
            QPushButton#minimal { padding: 4px 8px; font-size: 12px; border-radius: 30px; background: rgba(255,255,255,0.04); color: #aaa; border: 1px solid rgba(255,255,255,0.06); }
            QPushButton#minimal:hover { background: rgba(255,255,255,0.08); color: #fff; }
        """

    def _nav_button(self, icon, text, idx):
        btn = QPushButton(f"{icon}  {text}")
        btn.setObjectName("navBtn")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def switch_page(self, idx):
        self.stack.setCurrentIndex(idx)
        for btn in [self.btn_dash, self.btn_hist, self.btn_add, self.btn_sett]:
            btn.setChecked(False)
        [self.btn_dash, self.btn_hist, self.btn_add, self.btn_sett][idx].setChecked(True)
        if idx == 0:
            self.refresh_dashboard()
        elif idx == 1:
            self._load_history()

    def _dashboard_page(self):
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.setContentsMargins(20,20,20,20)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0,0,0,0)
        title = QLabel("📋 Dashboard")
        title.setStyleSheet("font-size: 20px; font-weight: 600; color: #fff;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        self.badge = QLabel("0 tasks")
        self.badge.setStyleSheet("background: rgba(168,85,247,0.15); color: #c084fc; padding: 2px 12px; border-radius: 30px; font-size: 12px; font-weight: 500; border: 1px solid rgba(168,85,247,0.2);")
        header_layout.addWidget(self.badge)
        layout.addWidget(header_widget)

        self.dash_list = QListWidget()
        self.dash_list.setStyleSheet("QListWidget { background: transparent; border: none; } QListWidget::item { border: none; padding: 2px; }")
        self.dash_list.setSpacing(4)
        layout.addWidget(self.dash_list)
        return page

    def refresh_dashboard(self):
        self.dash_list.clear()
        tasks = self.db.get_all_tasks()
        now = datetime.datetime.now()
        current_ym = now.strftime("%Y-%m")
        count = 0
        for t in tasks:
            tid, title, desc, due_day, paid_month, snooze, start_before, alarm_time, interval, current_due = t
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background: rgba(255,255,255,0.03);
                    border-radius: 12px;
                    padding: 6px 12px;
                    border: 1px solid rgba(255,255,255,0.04);
                }
                QFrame:hover {
                    background: rgba(255,255,255,0.06);
                    border-color: rgba(168,85,247,0.2);
                }
            """)
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(6, 4, 6, 4)
            card_layout.setSpacing(10)

            info = QVBoxLayout()
            info.setSpacing(0)
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet("font-size: 14px; font-weight: 500; color: #fff;")
            info.addWidget(title_lbl)
            meta = QLabel(f"Due: {due_day} • {alarm_time}")
            meta.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 11px;")
            info.addWidget(meta)

            status_frame = QFrame()
            status_frame.setStyleSheet("background: rgba(255,255,255,0.03); border-radius: 30px; padding: 2px 8px;")
            status_layout = QHBoxLayout(status_frame)
            status_layout.setContentsMargins(2,0,2,0)
            status_layout.setSpacing(4)
            dot = QLabel()
            dot.setFixedSize(8,8)
            dot.setStyleSheet("border-radius: 4px;")
            color = ""
            status_text = ""
            if current_due == "9999-12":
                status_text = "Done"
                color = "#34d399"
            elif current_due and current_due > current_ym:
                status_text = "Upcoming"
                color = "#60a5fa"
            else:
                if current_due and current_due < current_ym:
                    status_text = "Overdue"
                    color = "#f87171"
                else:
                    status_text = "Due"
                    color = "#fbbf24"
            if snooze:
                try:
                    dt = datetime.datetime.strptime(snooze, "%Y-%m-%d %H:%M:%S")
                    if now < dt:
                        status_text = f"Snoozed {dt.strftime('%H:%M')}"
                        color = "#fcd34d"
                except:
                    pass
            dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
            status_lbl = QLabel(status_text)
            status_lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 500;")
            status_layout.addWidget(dot)
            status_layout.addWidget(status_lbl)
            info.addWidget(status_frame)

            card_layout.addLayout(info, 1)

            actions = QHBoxLayout()
            actions.setSpacing(2)

            is_paid = (current_due and current_due > current_ym) or (current_due == "9999-12")
            if is_paid:
                btn_pay = QPushButton("↩")
                btn_pay.setToolTip("Unpaid")
                btn_pay.setStyleSheet("QPushButton { background: transparent; color: #f87171; border: none; padding: 4px 6px; font-size: 14px; } QPushButton:hover { background: rgba(248,113,113,0.15); border-radius: 6px; }")
                btn_pay.clicked.connect(lambda checked, t=tid: self._toggle_unpaid(t))
            else:
                btn_pay = QPushButton("✔")
                btn_pay.setToolTip("Paid")
                btn_pay.setStyleSheet("QPushButton { background: transparent; color: #34d399; border: none; padding: 4px 6px; font-size: 14px; } QPushButton:hover { background: rgba(52,211,153,0.15); border-radius: 6px; }")
                btn_pay.clicked.connect(lambda checked, t=tid: self._toggle_paid(t))

            btn_edit = QPushButton("✏")
            btn_edit.setToolTip("Edit")
            btn_edit.setStyleSheet("QPushButton { background: transparent; color: #aaa; border: none; padding: 4px 6px; font-size: 14px; } QPushButton:hover { background: rgba(255,255,255,0.05); border-radius: 6px; }")
            btn_edit.clicked.connect(lambda checked, t=tid: self._edit_task(t))

            btn_delete = QPushButton("🗑")
            btn_delete.setToolTip("Delete")
            btn_delete.setStyleSheet("QPushButton { background: transparent; color: #f87171; border: none; padding: 4px 6px; font-size: 14px; } QPushButton:hover { background: rgba(248,113,113,0.15); border-radius: 6px; }")
            btn_delete.clicked.connect(lambda checked, t=tid: self._delete_task(t))

            actions.addWidget(btn_pay)
            actions.addWidget(btn_edit)
            actions.addWidget(btn_delete)

            card_layout.addLayout(actions)

            item = QListWidgetItem()
            item.setSizeHint(card.sizeHint())
            self.dash_list.addItem(item)
            self.dash_list.setItemWidget(item, card)
            count += 1
        self.badge.setText(f"{count} tasks")

    def _toggle_paid(self, tid):
        self.db.mark_paid(tid)
        self.refresh_dashboard()

    def _toggle_unpaid(self, tid):
        self.db.mark_unpaid(tid)
        self.refresh_dashboard()

    def _edit_task(self, tid):
        tasks = self.db.get_all_tasks()
        task = next((t for t in tasks if t[0] == tid), None)
        if not task:
            return
        dlg = EditTaskDialog(task, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            self.db.update_task(data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7])
            self.refresh_dashboard()

    def _delete_task(self, tid):
        r = QMessageBox.question(self, "Delete", "Delete this task?")
        if r == QMessageBox.StandardButton.Yes:
            self.db.delete_task(tid)
            self.refresh_dashboard()

    def _history_page(self):
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.setContentsMargins(28,28,28,28)
        header = QLabel("📆 Payment History")
        header.setStyleSheet("font-size: 22px; font-weight: 600; color: #fff;")
        layout.addWidget(header)
        self.hist_list = QListWidget()
        self.hist_list.setStyleSheet("QListWidget { background: transparent; border: none; } QListWidget::item { border: none; padding: 6px; background: rgba(255,255,255,0.04); border-radius: 12px; margin-bottom: 2px; } QListWidget::item:hover { background: rgba(255,255,255,0.08); }")
        layout.addWidget(self.hist_list)
        return page

    def _load_history(self):
        self.hist_list.clear()
        for ym, titles in self.db.get_paid_history_grouped_by_month():
            self.hist_list.addItem(f"📅 {ym}: {titles}")

    def _add_task_page(self):
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.setContentsMargins(20,20,20,20)
        header = QLabel("➕ New Reminder")
        header.setStyleSheet("font-size: 20px; font-weight: 600; color: #fff; margin-bottom: 8px;")
        layout.addWidget(header)

        form_widget = QWidget()
        form_widget.setStyleSheet("background: rgba(255,255,255,0.04); border-radius: 16px; padding: 16px 20px;")
        form = QFormLayout(form_widget)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.inp_title = QLineEdit()
        self.inp_title.setPlaceholderText("e.g., Rent")
        self.inp_desc = QTextEdit()
        self.inp_desc.setMaximumHeight(60)
        self.inp_desc.setPlaceholderText("Optional notes")
        self.inp_due = QSpinBox()
        self.inp_due.setRange(1,31)
        self.inp_due.setValue(20)
        self.inp_start = QSpinBox()
        self.inp_start.setRange(1,30)
        self.inp_start.setValue(12)
        self.inp_time = QTimeEdit()
        self.inp_time.setTime(QTime(9,0))
        self.inp_recur = QComboBox()
        self.inp_recur.addItems(["Once", "1 month", "2 months", "3 months", "6 months", "12 months"])

        now = datetime.datetime.now()
        self.inp_year = QSpinBox()
        self.inp_year.setRange(2024, 2035)
        self.inp_year.setValue(now.year)
        month_names = ["January", "February", "March", "April", "May", "June",
                       "July", "August", "September", "October", "November", "December"]
        self.inp_month = QComboBox()
        self.inp_month.addItems(month_names)
        self.inp_month.setCurrentIndex(now.month-1)

        form.addRow("Title:", self.inp_title)
        form.addRow("Description:", self.inp_desc)
        form.addRow("Due Day:", self.inp_due)
        form.addRow("Alert (days before):", self.inp_start)
        form.addRow("Alarm Time:", self.inp_time)
        form.addRow("Recurrence:", self.inp_recur)

        # Stylish date box
        date_box = QFrame()
        date_box.setStyleSheet("""
            QFrame {
                background: rgba(168, 85, 247, 0.08);
                border: 1px solid rgba(168, 85, 247, 0.2);
                border-radius: 12px;
                padding: 8px 12px;
            }
        """)
        date_layout = QHBoxLayout(date_box)
        date_layout.setContentsMargins(8, 4, 8, 4)
        date_layout.setSpacing(10)
        date_icon = QLabel("📅")
        date_icon.setStyleSheet("font-size: 18px;")
        date_layout.addWidget(date_icon)
        date_layout.addWidget(QLabel("Year:"))
        date_layout.addWidget(self.inp_year)
        date_layout.addWidget(QLabel("Month:"))
        date_layout.addWidget(self.inp_month)
        date_layout.addStretch()

        form.addRow("Start Date:", date_box)

        btn_add = QPushButton("➕ Add Task")
        btn_add.setStyleSheet("font-size: 14px; padding: 8px;")
        btn_add.clicked.connect(self._add_task)
        form.addRow(btn_add)

        layout.addWidget(form_widget)
        layout.addStretch()
        return page

    def _add_task(self):
        title = self.inp_title.text().strip()
        if not title:
            QMessageBox.warning(self, "Error", "Title is required!")
            return
        interval_list = [0,1,2,3,6,12]
        interval = interval_list[self.inp_recur.currentIndex()]
        month_index = self.inp_month.currentIndex() + 1
        due_month = f"{self.inp_year.value():04d}-{month_index:02d}"
        self.db.add_task(
            title,
            self.inp_desc.toPlainText().strip(),
            self.inp_due.value(),
            self.inp_start.value(),
            self.inp_time.time().toString("HH:mm"),
            interval,
            due_month
        )
        QMessageBox.information(self, "Success", "Task added!")
        self.inp_title.clear()
        self.inp_desc.clear()
        self.switch_page(0)

    def _settings_page(self):
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QLabel("⚙ Settings")
        header.setStyleSheet("font-size: 22px; font-weight: 600; color: #fff; margin-bottom: 8px;")
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(16)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # Helper to create a card
        def create_card(title, icon):
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background: rgba(255,255,255,0.04);
                    border-radius: 16px;
                    border: 1px solid rgba(255,255,255,0.06);
                    padding: 16px 20px;
                }
                QFrame:hover {
                    background: rgba(255,255,255,0.06);
                    border-color: rgba(168,85,247,0.3);
                }
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(10)
            # Title row with icon
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0,0,0,0)
            icon_lbl = QLabel(icon)
            icon_lbl.setStyleSheet("font-size: 18px;")
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet("font-size: 15px; font-weight: 600; color: #eee;")
            title_row.addWidget(icon_lbl)
            title_row.addWidget(title_lbl)
            title_row.addStretch()
            card_layout.addLayout(title_row)
            # Content area (will be filled later)
            content_area = QWidget()
            content_area.setStyleSheet("background: transparent;")
            content_layout_inner = QVBoxLayout(content_area)
            content_layout_inner.setContentsMargins(0,0,0,0)
            content_layout_inner.setSpacing(8)
            card_layout.addWidget(content_area)
            return card, content_layout_inner

        # 1. Startup
        card, inner = create_card("Startup", "🚀")
        self.chk_startup = QCheckBox("Start with Windows")
        self.chk_startup.setStyleSheet("""
            QCheckBox {
                color: #ddd;
                font-size: 14px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid #555;
                background: rgba(255,255,255,0.05);
            }
            QCheckBox::indicator:checked {
                background: #a855f7;
                border-color: #a855f7;
            }
        """)
        self.chk_startup.setChecked(self.db.get_setting("auto_start") == "1")
        self.chk_startup.stateChanged.connect(lambda s: (enable_startup() if s else disable_startup(), self.db.set_setting("auto_start", "1" if s else "0")))
        inner.addWidget(self.chk_startup)
        content_layout.addWidget(card)

        # 2. Alarm Sound
        card, inner = create_card("Alarm Sound", "🔔")
        sound_row = QHBoxLayout()
        sound_row.setSpacing(10)
        self.lbl_sound = QLabel(self.db.get_setting("alarm_sound_path") or "Not selected")
        self.lbl_sound.setStyleSheet("color: #aaa; font-size: 13px;")
        btn_browse = QPushButton("Browse...")
        btn_browse.setStyleSheet("padding: 4px 12px; font-size: 12px; background: rgba(255,255,255,0.06); color: #ccc; border: 1px solid rgba(255,255,255,0.08); border-radius: 20px;")
        btn_browse.clicked.connect(self._choose_sound)
        btn_test = QPushButton("🔊 Test")
        btn_test.setStyleSheet("padding: 4px 12px; font-size: 12px; background: rgba(168,85,247,0.15); color: #c084fc; border: 1px solid rgba(168,85,247,0.2); border-radius: 20px;")
        btn_test.clicked.connect(self._test_sound)
        sound_row.addWidget(QLabel("File:"))
        sound_row.addWidget(self.lbl_sound, 1)
        sound_row.addWidget(btn_browse)
        sound_row.addWidget(btn_test)
        inner.addLayout(sound_row)
        content_layout.addWidget(card)

        # 3. Default Snooze
        card, inner = create_card("Default Snooze", "⏱")
        snooze_row = QHBoxLayout()
        snooze_row.setSpacing(10)
        snooze_row.addWidget(QLabel("Minutes:"))
        self.spin_snooze = QSpinBox()
        self.spin_snooze.setRange(1,60)
        self.spin_snooze.setValue(int(self.db.get_setting("default_snooze_minutes")))
        self.spin_snooze.setStyleSheet("""
            QSpinBox {
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px;
                padding: 4px 8px;
                color: #eee;
                width: 60px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 16px;
                border: none;
                background: transparent;
            }
        """)
        snooze_row.addWidget(self.spin_snooze)
        snooze_row.addStretch()
        inner.addLayout(snooze_row)
        content_layout.addWidget(card)

        # 4. Notifications
        card, inner = create_card("Notifications", "📬")
        self.chk_notif = QCheckBox("Enable toast notifications")
        self.chk_notif.setStyleSheet("""
            QCheckBox {
                color: #ddd;
                font-size: 14px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid #555;
                background: rgba(255,255,255,0.05);
            }
            QCheckBox::indicator:checked {
                background: #a855f7;
                border-color: #a855f7;
            }
        """)
        self.chk_notif.setChecked(self.db.get_setting("desktop_notifications") == "1")
        inner.addWidget(self.chk_notif)
        content_layout.addWidget(card)

        # 5. Save Settings button (as a card)
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: rgba(255,255,255,0.04);
                border-radius: 16px;
                border: 1px solid rgba(255,255,255,0.06);
                padding: 12px;
            }
        """)
        card_layout = QHBoxLayout(card)
        btn_save = QPushButton("💾 Save Settings")
        btn_save.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #a855f7, stop:1 #ec4899);
                color: white;
                border: none;
                border-radius: 40px;
                padding: 10px 24px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover { opacity: 0.9; }
        """)
        btn_save.clicked.connect(self._save_settings)
        card_layout.addWidget(btn_save)
        card_layout.addStretch()
        content_layout.addWidget(card)

        # 6. Maintenance (Clear Done)
        card, inner = create_card("Maintenance", "🧹")
        btn_clear_done = QPushButton("🗑 Clear Done Tasks")
        btn_clear_done.setStyleSheet("""
            QPushButton {
                background: rgba(248,113,113,0.12);
                color: #f87171;
                border: 1px solid rgba(248,113,113,0.2);
                border-radius: 40px;
                padding: 8px 16px;
                font-weight: 500;
                font-size: 13px;
            }
            QPushButton:hover { background: rgba(248,113,113,0.2); }
        """)
        btn_clear_done.clicked.connect(self._clear_done_tasks)
        inner.addWidget(btn_clear_done)
        content_layout.addWidget(card)

        # 7. Reset Settings
        card, inner = create_card("Reset", "🔄")
        btn_reset = QPushButton("↩ Reset All Settings to Default")
        btn_reset.setStyleSheet("""
            QPushButton {
                background: rgba(251,191,36,0.12);
                color: #fbbf24;
                border: 1px solid rgba(251,191,36,0.2);
                border-radius: 40px;
                padding: 8px 16px;
                font-weight: 500;
                font-size: 13px;
            }
            QPushButton:hover { background: rgba(251,191,36,0.2); }
        """)
        btn_reset.clicked.connect(self._reset_settings)
        inner.addWidget(btn_reset)
        content_layout.addWidget(card)

        # 8. Export CSV
        card, inner = create_card("Export", "📤")
        btn_export = QPushButton("📊 Export History as CSV")
        btn_export.setStyleSheet("""
            QPushButton {
                background: rgba(52,211,153,0.12);
                color: #34d399;
                border: 1px solid rgba(52,211,153,0.2);
                border-radius: 40px;
                padding: 8px 16px;
                font-weight: 500;
                font-size: 13px;
            }
            QPushButton:hover { background: rgba(52,211,153,0.2); }
        """)
        btn_export.clicked.connect(self._export_csv)
        inner.addWidget(btn_export)
        content_layout.addWidget(card)

        # 9. Backup & Restore
        card, inner = create_card("Backup & Restore", "🗄")
        backup_restore_row = QHBoxLayout()
        backup_restore_row.setSpacing(10)
        btn_backup = QPushButton("📤 Backup")
        btn_backup.setStyleSheet("padding: 8px 16px; font-size: 13px; background: rgba(255,255,255,0.06); color: #ccc; border: 1px solid rgba(255,255,255,0.08); border-radius: 20px;")
        btn_backup.clicked.connect(self._backup)
        btn_restore = QPushButton("📥 Restore")
        btn_restore.setStyleSheet("padding: 8px 16px; font-size: 13px; background: rgba(255,255,255,0.06); color: #ccc; border: 1px solid rgba(255,255,255,0.08); border-radius: 20px;")
        btn_restore.clicked.connect(self._restore)
        backup_restore_row.addWidget(btn_backup)
        backup_restore_row.addWidget(btn_restore)
        backup_restore_row.addStretch()
        inner.addLayout(backup_restore_row)
        content_layout.addWidget(card)

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        return page

    def _clear_done_tasks(self):
        r = QMessageBox.question(self, "Clear Done", "Delete all tasks marked as 'Done'? This cannot be undone.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            self.db.clear_done_tasks()
            self.refresh_dashboard()
            QMessageBox.information(self, "Done", "All 'Done' tasks have been cleared.")

    def _reset_settings(self):
        r = QMessageBox.question(self, "Reset Settings", "Reset all settings to default? This will remove your custom sound path, snooze minutes, and startup preference.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            self.db.reset_settings()
            self.chk_startup.setChecked(False)
            self.spin_snooze.setValue(10)
            self.chk_notif.setChecked(True)
            self.lbl_sound.setText("Not selected")
            QMessageBox.information(self, "Done", "Settings have been reset to defaults.")

    def _export_csv(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "payment_history.csv", "CSV Files (*.csv)")
        if not file_path:
            return
        try:
            data = self.db.get_paid_history_all()
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Year-Month", "Task", "Paid Timestamp"])
                writer.writerows(data)
            QMessageBox.information(self, "Export", f"History exported to {file_path}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to export: {str(e)}")

    def _choose_sound(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Sound", "", "Audio (*.mp3 *.wav)")
        if f:
            self.lbl_sound.setText(f)
            self.db.set_setting("alarm_sound_path", f)

    def _test_sound(self):
        path = self.db.get_setting("alarm_sound_path")
        play_alarm_sound(path)
        QTimer.singleShot(2000, stop_alarm_sound)

    def _save_settings(self):
        self.db.set_setting("default_snooze_minutes", str(self.spin_snooze.value()))
        self.db.set_setting("desktop_notifications", "1" if self.chk_notif.isChecked() else "0")
        QMessageBox.information(self, "Settings", "Saved!")

    def _backup(self):
        f, _ = QFileDialog.getSaveFileName(self, "Backup", "my_reminder_backup.db", "DB (*.db)")
        if f:
            self.db.backup_database(f)
            QMessageBox.information(self, "Done", "Backup successful!")

    def _restore(self):
        f, _ = QFileDialog.getOpenFileName(self, "Restore", "", "DB (*.db)")
        if f:
            r = QMessageBox.question(self, "Restore", "Replace current database?")
            if r == QMessageBox.StandardButton.Yes:
                self.db.restore_database(f)
                QMessageBox.information(self, "Done", "Restored. Restart app.")

    def show_alarm(self, tasks):
        if self.alarm_popup:
            return
        sound_path = self.db.get_setting("alarm_sound_path")
        play_alarm_sound(sound_path)
        self.alarm_popup = AlarmPopup(tasks, self)
        self.alarm_popup.show()

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage("My Reminder", "Running in background.", QSystemTrayIcon.MessageIcon.Information, 2000)

    def quit_app(self):
        stop_alarm_sound()
        self.tray_icon.hide()
        QApplication.quit()

# ===================== MAIN =====================
def main():
    if is_already_running():
        sys.exit(0)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(create_app_icon())
    win = MyReminderApp()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()