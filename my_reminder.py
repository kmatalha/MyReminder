import sys
import os
import sqlite3
import datetime
import struct
import wave
import io
import winreg
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QVBoxLayout, QHBoxLayout,
    QWidget, QLabel, QPushButton, QListWidget, QListWidgetItem, QFormLayout,
    QSpinBox, QLineEdit, QTextEdit, QMessageBox, QDialog, QSystemTrayIcon,
    QMenu, QFileDialog, QCheckBox, QTimeEdit, QGroupBox, QScrollArea, QComboBox,
    QFrame, QGridLayout, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QTime, QObject, QSharedMemory, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QPalette
import winsound

# ===================== SINGLE INSTANCE CHECK =====================
SHARED_MEM_KEY = "MyReminderAppSingleInstance"

def is_already_running():
    shared_mem = QSharedMemory(SHARED_MEM_KEY)
    if shared_mem.attach():
        return True
    if not shared_mem.create(1):
        return True
    return False

# ===================== APP DIRECTORY HELPER =====================
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

# ===================== ICON GENERATOR =====================
def create_app_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#00bcd4"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    painter.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "MR")
    painter.end()
    return QIcon(pixmap)

# ===================== AUTO-START MANAGER =====================
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

# ===================== DATABASE MANAGER =====================
class DatabaseManager:
    def __init__(self):
        app_dir = get_app_dir()
        db_path = os.path.join(app_dir, "my_reminder.db")
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
        self._migrate_add_columns()
        self._migrate_existing_data()
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

    def add_task(self, title, description, due_day, start_days_before, alarm_time, recurrence_interval, due_month):
        self.cursor.execute(
            """INSERT INTO tasks 
               (title, description, due_day, start_days_before, alarm_time, recurrence_interval, current_due_month)
               VALUES (?,?,?,?,?,?,?)""",
            (title, description, due_day, start_days_before, alarm_time, recurrence_interval, due_month)
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def update_task(self, task_id, title, description, due_day, start_days_before, alarm_time, recurrence_interval, due_month):
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

    def get_all_tasks(self):
        self.cursor.execute(
            """SELECT id, title, description, due_day, paid_month, snooze_until,
                      start_days_before, alarm_time, recurrence_interval, current_due_month
               FROM tasks"""
        )
        return self.cursor.fetchall()

    def mark_paid(self, task_id, year_month):
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

# ===================== BEEP SOUND GENERATOR =====================
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

# ===================== ALARM POPUP (UPGRADED UI) =====================
class AlarmPopup(QDialog):
    def __init__(self, tasks, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self.task_frames = {}
        self.parent_app = parent
        self.setWindowTitle("⏰ Reminder")
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        self.setMinimumWidth(600)
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #2b2b2b, stop:1 #1e1e1e);
                border: 2px solid #ff5555;
                border-radius: 16px;
            }
            QLabel { color: #eee; }
            QGroupBox {
                border: 1px solid #444;
                border-radius: 12px;
                margin-top: 12px;
                padding: 16px;
                background: #252525;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 16px;
                padding: 0 8px;
                color: #00bcd4;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton {
                background: #3a3a3a;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover { background: #4a4a4a; }
            QPushButton:pressed { background: #2a2a2a; }
            QPushButton#paidBtn { background: #2e7d32; }
            QPushButton#paidBtn:hover { background: #388e3c; }
            QPushButton#snoozeBtn { background: #b26a00; }
            QPushButton#snoozeBtn:hover { background: #cc7a00; }
            QPushButton#dismissBtn { background: #7f0000; }
            QPushButton#dismissBtn:hover { background: #990000; }
        """)
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("<b style='color:#ffb300; font-size:18px;'>🔔 Reminders</b>")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(12)

        for task in tasks:
            tid, title, *_ = task
            frame = QGroupBox(f"📌 {title}")
            frame.setObjectName("taskFrame")
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
        btn_dismiss_all.setStyleSheet("""
            QPushButton { background: #7f0000; padding: 12px; font-weight: bold; }
            QPushButton:hover { background: #990000; }
        """)
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
        self.parent_app.db.mark_paid(task_id, None)
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

# ===================== ALARM CHECKER =====================
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
        self.setMinimumWidth(500)
        self.setStyleSheet("""
            QDialog { background: #1e1e1e; }
            QLabel { color: #ccc; }
            QLineEdit, QTextEdit, QSpinBox, QComboBox, QTimeEdit {
                background: #2b2b2b;
                border: 1px solid #444;
                border-radius: 8px;
                padding: 8px;
                color: #eee;
            }
            QPushButton { background: #00bcd4; color: white; border: none; border-radius: 8px; padding: 10px 20px; font-weight: bold; }
            QPushButton:hover { background: #00acc1; }
        """)
        layout = QFormLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

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
        layout.addRow("Start days before:", self.start_spin)
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

# ===================== MAIN WINDOW (UPGRADED UI) =====================
class MyReminderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = DatabaseManager()
        self.setWindowTitle("My Reminder")
        self.resize(1100, 750)
        self.setWindowIcon(create_app_icon())
        self.setStyleSheet(self._global_style())
        self.alarm_active = set()
        self.alarm_popup = None

        # Tray
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

        # Main layout
        central = QWidget()
        central.setObjectName("mainWindow")
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setSpacing(12)
        sb_layout.setContentsMargins(16, 24, 16, 24)

        title_lbl = QLabel("📌 My Reminder")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #00bcd4;")
        sb_layout.addWidget(title_lbl)
        sb_layout.addSpacing(20)

        self.btn_dash = self._nav_button("📊 Dashboard", 0)
        self.btn_hist = self._nav_button("📅 History", 1)
        self.btn_add = self._nav_button("➕ Add Task", 2)
        self.btn_sett = self._nav_button("⚙ Settings", 3)

        sb_layout.addWidget(self.btn_dash)
        sb_layout.addWidget(self.btn_hist)
        sb_layout.addWidget(self.btn_add)
        sb_layout.addWidget(self.btn_sett)
        sb_layout.addStretch()

        # Stack
        self.stack = QStackedWidget()
        self.stack.addWidget(self._dashboard_page())
        self.stack.addWidget(self._history_page())
        self.stack.addWidget(self._add_task_page())
        self.stack.addWidget(self._settings_page())

        main_layout.addWidget(sidebar)
        main_layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # Connect buttons
        self.btn_dash.clicked.connect(lambda: self.switch_page(0))
        self.btn_hist.clicked.connect(lambda: self.switch_page(1))
        self.btn_add.clicked.connect(lambda: self.switch_page(2))
        self.btn_sett.clicked.connect(lambda: self.switch_page(3))

        self.switch_page(0)  # initial

        self.checker = AlarmChecker(self.db, self)
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_dashboard)
        self.refresh_timer.start(60000)
        self.refresh_dashboard()

    def _global_style(self):
        return """
            QMainWindow { background: #1a1a1a; }
            QWidget#mainWindow { background: #1a1a1a; }
            QWidget#sidebar {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #1e1e1e, stop:1 #2a2a2a);
                border-right: 1px solid #2a2a2a;
            }
            QPushButton#navBtn {
                text-align: left;
                padding: 12px 16px;
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 500;
                color: #aaa;
                background: transparent;
            }
            QPushButton#navBtn:hover { background: #2a2a2a; color: #eee; }
            QPushButton#navBtn:checked {
                background: #00bcd4;
                color: #1a1a1a;
                font-weight: bold;
            }
            QScrollArea { border: none; background: transparent; }
            QLabel { color: #ddd; }
            QListWidget {
                background: #1a1a1a;
                border: none;
                outline: none;
                padding: 8px;
            }
            QListWidget::item { border: none; padding: 4px; }
            QListWidget::item:selected { background: #2a2a2a; }
            QGroupBox {
                border: 1px solid #333;
                border-radius: 12px;
                margin-top: 12px;
                padding-top: 16px;
                background: #1e1e1e;
            }
            QGroupBox::title { color: #00bcd4; }
            QLineEdit, QTextEdit, QSpinBox, QComboBox, QTimeEdit {
                background: #252525;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
                padding: 8px;
                color: #eee;
            }
            QPushButton {
                background: #00bcd4;
                color: #1a1a1a;
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
                font-weight: bold;
            }
            QPushButton:hover { background: #00acc1; }
            QPushButton:pressed { background: #00838f; }
            QPushButton#danger { background: #c62828; color: white; }
            QPushButton#danger:hover { background: #b71c1c; }
        """

    def _nav_button(self, text, idx):
        btn = QPushButton(text)
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
        page.setStyleSheet("background: #1a1a1a;")
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        header = QLabel("📋 Upcoming Reminders")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #eee;")
        layout.addWidget(header)

        self.dash_list = QListWidget()
        self.dash_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; }
            QListWidget::item { border: none; padding: 4px; }
        """)
        self.dash_list.setSpacing(8)
        layout.addWidget(self.dash_list)
        return page

    def refresh_dashboard(self):
        self.dash_list.clear()
        tasks = self.db.get_all_tasks()
        now = datetime.datetime.now()
        current_ym = now.strftime("%Y-%m")

        for t in tasks:
            tid, title, desc, due_day, paid_month, snooze, start_before, alarm_time, interval, current_due = t

            # Card widget
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background: #252525;
                    border-radius: 12px;
                    padding: 16px;
                    border: 1px solid #333;
                }
                QFrame:hover { border-color: #00bcd4; }
            """)
            card_layout = QHBoxLayout(card)
            card_layout.setSpacing(16)

            # Left: title + info
            info_layout = QVBoxLayout()
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #eee;")
            info_layout.addWidget(title_lbl)

            details = f"Due day: {due_day}  •  Alarm: {alarm_time}"
            if interval == 0:
                details += "  •  Once"
            else:
                details += f"  •  Every {interval} month{'s' if interval>1 else ''}"
            detail_lbl = QLabel(details)
            detail_lbl.setStyleSheet("color: #aaa; font-size: 13px;")
            info_layout.addWidget(detail_lbl)

            # Status badge
            status_text = ""
            status_color = ""
            if current_due == "9999-12":
                status_text = "✅ Done"
                status_color = "#4caf50"
            elif current_due and current_due > current_ym:
                status_text = "📅 Upcoming"
                status_color = "#4fc3f7"
            else:
                if current_due and current_due < current_ym:
                    status_text = "⚠ Overdue"
                    status_color = "#ff5252"
                else:
                    status_text = "🔔 Due"
                    status_color = "#ffb300"

            if snooze:
                try:
                    dt = datetime.datetime.strptime(snooze, "%Y-%m-%d %H:%M:%S")
                    if now < dt:
                        status_text = f"⏰ Snoozed {dt.strftime('%H:%M')}"
                        status_color = "#ffca28"
                except:
                    pass

            status_lbl = QLabel(status_text)
            status_lbl.setStyleSheet(f"color: {status_color}; font-weight: bold; font-size: 14px;")
            info_layout.addWidget(status_lbl)

            # Actions
            action_layout = QHBoxLayout()
            btn_paid = QPushButton("✔ Paid")
            btn_paid.setStyleSheet("background: #2e7d32; color: white; padding: 6px 12px;")
            btn_paid.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_paid.clicked.connect(lambda checked, t=tid: self._mark_paid(t))

            btn_edit = QPushButton("✏️ Edit")
            btn_edit.setStyleSheet("background: #00695c; color: white; padding: 6px 12px;")
            btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_edit.clicked.connect(lambda checked, t=tid: self._edit_task(t))

            btn_delete = QPushButton("🗑 Delete")
            btn_delete.setObjectName("danger")
            btn_delete.setStyleSheet("background: #c62828; color: white; padding: 6px 12px;")
            btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_delete.clicked.connect(lambda checked, t=tid: self._delete_task(t))

            action_layout.addWidget(btn_paid)
            action_layout.addWidget(btn_edit)
            action_layout.addWidget(btn_delete)
            action_layout.addStretch()

            info_layout.addLayout(action_layout)

            card_layout.addLayout(info_layout, 1)
            card_layout.addWidget(status_lbl, alignment=Qt.AlignmentFlag.AlignTop)

            item = QListWidgetItem()
            item.setSizeHint(card.sizeHint())
            self.dash_list.addItem(item)
            self.dash_list.setItemWidget(item, card)

    def _history_page(self):
        page = QWidget()
        page.setStyleSheet("background: #1a1a1a;")
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        header = QLabel("📆 Payment History by Month")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #eee;")
        layout.addWidget(header)

        self.hist_list = QListWidget()
        self.hist_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; }
            QListWidget::item { border: none; padding: 8px; background: #252525; border-radius: 8px; margin-bottom: 4px; }
            QListWidget::item:hover { background: #2a2a2a; }
        """)
        layout.addWidget(self.hist_list)
        return page

    def _load_history(self):
        self.hist_list.clear()
        for ym, titles in self.db.get_paid_history_grouped_by_month():
            self.hist_list.addItem(f"📅 {ym}: {titles}")

    def _add_task_page(self):
        page = QWidget()
        page.setStyleSheet("background: #1a1a1a;")
        layout = QVBoxLayout(page)
        layout.setSpacing(24)
        layout.setContentsMargins(40, 40, 40, 40)

        header = QLabel("➕ New Reminder")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #eee;")
        layout.addWidget(header)

        form_widget = QWidget()
        form_widget.setStyleSheet("background: #252525; border-radius: 16px; padding: 24px;")
        form_layout = QFormLayout(form_widget)
        form_layout.setSpacing(16)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.inp_title = QLineEdit()
        self.inp_title.setPlaceholderText("e.g., Rent payment")
        self.inp_desc = QTextEdit()
        self.inp_desc.setMaximumHeight(80)
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
        self.inp_recur.addItems(["Once (no repeat)", "1 month", "2 months", "3 months", "6 months", "12 months"])

        now = datetime.datetime.now()
        self.inp_year = QSpinBox()
        self.inp_year.setRange(2024, 2035)
        self.inp_year.setValue(now.year)
        self.inp_month = QComboBox()
        self.inp_month.addItems([f"{i:02d}" for i in range(1, 13)])
        self.inp_month.setCurrentIndex(now.month - 1)

        form_layout.addRow("Title:", self.inp_title)
        form_layout.addRow("Description:", self.inp_desc)
        form_layout.addRow("Due Day:", self.inp_due)
        form_layout.addRow("Alert Start (days before):", self.inp_start)
        form_layout.addRow("Alarm Time:", self.inp_time)
        form_layout.addRow("Recurrence:", self.inp_recur)

        month_layout = QHBoxLayout()
        month_layout.addWidget(QLabel("Year:"))
        month_layout.addWidget(self.inp_year)
        month_layout.addWidget(QLabel("Month:"))
        month_layout.addWidget(self.inp_month)
        form_layout.addRow("Start Reminder In:", month_layout)

        btn_add = QPushButton("➕ Add Task")
        btn_add.setStyleSheet("font-size: 16px; padding: 12px; background: #00bcd4;")
        btn_add.clicked.connect(self._add_task)
        form_layout.addRow(btn_add)

        layout.addWidget(form_widget)
        layout.addStretch()
        return page

    def _add_task(self):
        title = self.inp_title.text().strip()
        if not title:
            QMessageBox.warning(self, "Error", "Title is required!")
            return
        interval_list = [0, 1, 2, 3, 6, 12]
        interval = interval_list[self.inp_recur.currentIndex()]
        due_month = f"{self.inp_year.value():04d}-{int(self.inp_month.currentText()):02d}"
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
        page.setStyleSheet("background: #1a1a1a;")
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        header = QLabel("⚙ Settings")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #eee;")
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        sl = QVBoxLayout(content)
        sl.setSpacing(16)

        # Startup
        g = QGroupBox("🚀 Windows Startup")
        g.setStyleSheet("QGroupBox { background: #252525; border-radius: 12px; padding: 16px; }")
        h = QHBoxLayout(g)
        self.chk_startup = QCheckBox("Start with Windows")
        self.chk_startup.setStyleSheet("color: #eee;")
        self.chk_startup.setChecked(self.db.get_setting("auto_start") == "1")
        self.chk_startup.stateChanged.connect(
            lambda s: (enable_startup() if s else disable_startup(),
                       self.db.set_setting("auto_start", "1" if s else "0"))
        )
        h.addWidget(self.chk_startup)
        sl.addWidget(g)

        # Sound
        g = QGroupBox("🔔 Alarm Sound")
        g.setStyleSheet("QGroupBox { background: #252525; border-radius: 12px; padding: 16px; }")
        h = QHBoxLayout(g)
        self.lbl_sound = QLabel(self.db.get_setting("alarm_sound_path") or "Not selected")
        self.lbl_sound.setStyleSheet("color: #aaa;")
        btn = QPushButton("Browse...")
        btn.clicked.connect(self._choose_sound)
        h.addWidget(QLabel("File:"))
        h.addWidget(self.lbl_sound, 1)
        h.addWidget(btn)
        sl.addWidget(g)

        # Snooze
        g = QGroupBox("⏱ Default Snooze (minutes)")
        g.setStyleSheet("QGroupBox { background: #252525; border-radius: 12px; padding: 16px; }")
        h = QHBoxLayout(g)
        self.spin_snooze = QSpinBox()
        self.spin_snooze.setRange(1,60)
        self.spin_snooze.setValue(int(self.db.get_setting("default_snooze_minutes")))
        h.addWidget(QLabel("Minutes:"))
        h.addWidget(self.spin_snooze)
        sl.addWidget(g)

        # Notifications
        g = QGroupBox("📬 Desktop Notifications")
        g.setStyleSheet("QGroupBox { background: #252525; border-radius: 12px; padding: 16px; }")
        h = QHBoxLayout(g)
        self.chk_notif = QCheckBox("Enable toast notifications")
        self.chk_notif.setStyleSheet("color: #eee;")
        self.chk_notif.setChecked(self.db.get_setting("desktop_notifications") == "1")
        h.addWidget(self.chk_notif)
        sl.addWidget(g)

        # Save
        btn_save = QPushButton("💾 Save Settings")
        btn_save.setStyleSheet("padding: 12px; font-size: 14px;")
        btn_save.clicked.connect(self._save_settings)
        sl.addWidget(btn_save)

        # Backup / Restore
        g = QGroupBox("🗄 Backup & Restore")
        g.setStyleSheet("QGroupBox { background: #252525; border-radius: 12px; padding: 16px; }")
        h = QHBoxLayout(g)
        h.addWidget(QPushButton("📤 Backup", clicked=self._backup))
        h.addWidget(QPushButton("📥 Restore", clicked=self._restore))
        sl.addWidget(g)

        sl.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        return page

    def _choose_sound(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Sound", "", "Audio (*.mp3 *.wav)")
        if f:
            self.lbl_sound.setText(f)
            self.db.set_setting("alarm_sound_path", f)

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

    def _mark_paid(self, tid):
        self.db.mark_paid(tid, None)
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