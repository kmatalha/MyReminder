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
    QMenu, QFileDialog, QCheckBox, QTimeEdit, QGroupBox, QScrollArea, QComboBox
)
from PyQt6.QtCore import Qt, QTimer, QTime, pyqtSignal, QObject, QSharedMemory
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
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
    painter.setBrush(QColor("#0d7377"))
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
        # Migrate paid_month to current_due_month if not set
        self.cursor.execute("SELECT id, paid_month FROM tasks WHERE current_due_month IS NULL")
        rows = self.cursor.fetchall()
        now = datetime.datetime.now()
        for row in rows:
            tid, paid_month = row
            if paid_month and paid_month != "":
                # paid_month is like "YYYY-MM" -> next due = paid_month + 1 month
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

    def add_task(self, title, description, due_day, start_days_before, alarm_time, recurrence_interval):
        now = datetime.datetime.now()
        current_due = now.strftime("%Y-%m")
        self.cursor.execute(
            """INSERT INTO tasks 
               (title, description, due_day, start_days_before, alarm_time, recurrence_interval, current_due_month)
               VALUES (?,?,?,?,?,?,?)""",
            (title, description, due_day, start_days_before, alarm_time, recurrence_interval, current_due)
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def update_task(self, task_id, title, description, due_day, start_days_before, alarm_time, recurrence_interval):
        self.cursor.execute("""
            UPDATE tasks 
            SET title=?, description=?, due_day=?, start_days_before=?, alarm_time=?, recurrence_interval=?
            WHERE id=?
        """, (title, description, due_day, start_days_before, alarm_time, recurrence_interval, task_id))
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
        # year_month is the month for which it is being paid (should equal current_due_month)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Advance current_due_month by recurrence_interval
        self.cursor.execute("SELECT current_due_month, recurrence_interval FROM tasks WHERE id=?", (task_id,))
        row = self.cursor.fetchone()
        if not row:
            return
        due_month_str, interval = row
        try:
            y, m = map(int, due_month_str.split("-"))
            # Add interval months
            for _ in range(interval):
                m += 1
                if m > 12:
                    m = 1
                    y += 1
            new_due = f"{y:04d}-{m:02d}"
        except:
            # fallback: current month + interval
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
        # Store payment in history (using the month that was just paid)
        self.cursor.execute(
            "INSERT INTO paid_history (task_id, year_month, paid_timestamp) VALUES (?,?,?)",
            (task_id, due_month_str, now_str)
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

# ===================== ALARM POPUP =====================
class AlarmPopup(QDialog):
    def __init__(self, tasks, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self.task_frames = {}
        self.parent_app = parent
        self.setWindowTitle("⏰ Reminder")
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        self.setStyleSheet("""
            QDialog { background-color: #2b2b2b; border: 2px solid #ff5555; border-radius: 12px; }
            QLabel { color: white; }
            QPushButton { background-color: #444; color: white; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background-color: #555; }
        """)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b style='color:#ffaa00;'>🔔 Reminders</b>"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        for task in tasks:
            tid, title, *_ = task
            frame = QGroupBox(f"📌 {title}")
            frame.setStyleSheet("QGroupBox { color: #00bcd4; font-weight: bold; }")
            btn_layout = QHBoxLayout()
            btn_paid = QPushButton("✔ Paid")
            btn_snooze_today = QPushButton("🔕 Today")
            btn_snooze = QPushButton("⏱ Snooze (5m)")
            btn_dismiss = QPushButton("❌ Dismiss")
            btn_paid.clicked.connect(lambda checked, t=tid: self.handle_paid(t))
            btn_snooze_today.clicked.connect(lambda checked, t=tid: self.handle_snooze_today(t))
            btn_snooze.clicked.connect(lambda checked, t=tid: self.handle_snooze(t))
            btn_dismiss.clicked.connect(lambda checked, t=tid: self.handle_dismiss(t))
            btn_layout.addWidget(btn_paid)
            btn_layout.addWidget(btn_snooze_today)
            btn_layout.addWidget(btn_snooze)
            btn_layout.addWidget(btn_dismiss)
            frame.setLayout(btn_layout)
            self.content_layout.addWidget(frame)
            self.task_frames[tid] = frame
        scroll.setWidget(content)
        layout.addWidget(scroll)
        btn_dismiss_all = QPushButton("🔇 Dismiss All")
        btn_dismiss_all.setStyleSheet("background-color: #aa3333;")
        btn_dismiss_all.clicked.connect(self.handle_dismiss_all)
        layout.addWidget(btn_dismiss_all)
        self.adjustSize()
        self.setMinimumWidth(500)

    def remove_task(self, task_id):
        frame = self.task_frames.pop(task_id, None)
        if frame:
            self.content_layout.removeWidget(frame)
            frame.deleteLater()
        if not self.task_frames:
            self.close_ok()

    def handle_paid(self, task_id):
        # Get current due month for history
        self.parent_app.db.mark_paid(task_id, None)  # mark_paid will compute new due
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
            # If current_due is None (should not happen), skip
            if not current_due:
                continue
            # Check if task is due this month or overdue
            if current_ym < current_due:
                # Not yet due
                continue
            # Check snooze
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
                # Normal alarm: check alarm time
                try:
                    ah, am = map(int, alarm_time.split(":"))
                except:
                    ah, am = 9, 0
                if now.hour != ah or now.minute != am:
                    continue
            # Check day window
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
        self.setWindowTitle("Edit Task")
        self.setStyleSheet("background-color: #2b2b2b; color: white;")
        layout = QFormLayout(self)
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
        self.recur_combo = QComboBox()
        self.recur_combo.addItems(["1 month", "2 months", "3 months", "6 months", "12 months"])
        # map text to interval
        interval = task_data[8] if len(task_data) > 8 else 1
        index_map = {1:0, 2:1, 3:2, 6:3, 12:4}
        self.recur_combo.setCurrentIndex(index_map.get(interval, 0))
        layout.addRow("Title:", self.title_edit)
        layout.addRow("Description:", self.desc_edit)
        layout.addRow("Due Day:", self.due_spin)
        layout.addRow("Start days before:", self.start_spin)
        layout.addRow("Alarm Time:", self.time_edit)
        layout.addRow("Recurrence:", self.recur_combo)
        btn_box = QHBoxLayout()
        btn_save = QPushButton("Save")
        btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_save)
        btn_box.addWidget(btn_cancel)
        layout.addRow(btn_box)

    def get_data(self):
        interval = [1,2,3,6,12][self.recur_combo.currentIndex()]
        return (
            self.task_id,
            self.title_edit.text().strip(),
            self.desc_edit.toPlainText().strip(),
            self.due_spin.value(),
            self.start_spin.value(),
            self.time_edit.time().toString("HH:mm"),
            interval
        )

# ===================== MAIN WINDOW =====================
class MyReminderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = DatabaseManager()
        self.setWindowTitle("My Reminder")
        self.resize(900, 650)
        self.setWindowIcon(create_app_icon())
        self.setStyleSheet(self._style())
        self.alarm_active = set()
        self.alarm_popup = None

        # Tray
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(create_app_icon())
        tray_menu = QMenu()
        tray_menu.addAction("Show", self.show_window)
        tray_menu.addAction("Exit", self.quit_app)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.show()
        if self.db.get_setting("auto_start") == "1":
            enable_startup()

        central = QWidget()
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0,0,0,0)
        sidebar = QWidget()
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.addWidget(QLabel("My Reminder"))
        self.btn_dash = QPushButton("📊 Dashboard")
        self.btn_hist = QPushButton("📅 My Reminders")
        self.btn_add = QPushButton("➕ Add Task")
        self.btn_sett = QPushButton("⚙ Settings")
        for btn in (self.btn_dash, self.btn_hist, self.btn_add, self.btn_sett):
            btn.setCheckable(True)
            sb_layout.addWidget(btn)
        sb_layout.addStretch()

        self.stack = QStackedWidget()
        self.stack.addWidget(self._dashboard_page())
        self.stack.addWidget(self._history_page())
        self.stack.addWidget(self._add_task_page())
        self.stack.addWidget(self._settings_page())

        main_layout.addWidget(sidebar)
        main_layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.btn_dash.setChecked(True)
        self.btn_dash.clicked.connect(lambda: self.switch_page(0))
        self.btn_hist.clicked.connect(lambda: self.switch_page(1))
        self.btn_add.clicked.connect(lambda: self.switch_page(2))
        self.btn_sett.clicked.connect(lambda: self.switch_page(3))

        self.checker = AlarmChecker(self.db, self)
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_dashboard)
        self.refresh_timer.start(60000)
        self.refresh_dashboard()

    def _style(self):
        return """
            QMainWindow { background-color: #1e1e1e; }
            QWidget { color: #ddd; font-family: "Segoe UI"; }
            QGroupBox { border: 1px solid #555; border-radius: 8px; margin-top: 10px; padding-top: 15px; color: #ffaa00; }
            QLineEdit, QTextEdit, QSpinBox, QComboBox, QTimeEdit {
                background: #2b2b2b; border: 1px solid #555; border-radius: 6px; padding: 6px; color: white;
            }
            QListWidget { background: #2b2b2b; border: 1px solid #555; border-radius: 6px; }
            QPushButton { background-color: #0d7377; color: white; border-radius: 6px; padding: 8px 14px; }
            QPushButton:hover { background-color: #0a9aa3; }
        """

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
        layout = QVBoxLayout(page)
        self.dash_list = QListWidget()
        self.dash_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.dash_list.customContextMenuRequested.connect(self._dash_context_menu)
        self.dash_list.itemDoubleClicked.connect(self._edit_selected)
        layout.addWidget(QLabel("📋 Upcoming Reminders"))
        layout.addWidget(self.dash_list)
        return page

    def refresh_dashboard(self):
        self.dash_list.clear()
        tasks = self.db.get_all_tasks()
        now = datetime.datetime.now()
        current_ym = now.strftime("%Y-%m")
        for t in tasks:
            tid, title, desc, due_day, paid_month, snooze, start_before, alarm_time, interval, current_due = t
            w = QWidget()
            h = QHBoxLayout(w)
            # Show due info
            title_lbl = QLabel(f"{title} (Due: {due_day}, Alarm: {alarm_time})")
            title_lbl.setWordWrap(True)
            status = QLabel()
            if current_due and current_due > current_ym:
                status.setText("✔ Paid")
                status.setStyleSheet("color: #88ff88;")
            else:
                # Overdue or due
                if current_due and current_due < current_ym:
                    status.setText("⚠ Overdue")
                    status.setStyleSheet("color: #ff4444;")
                    title_lbl.setStyleSheet("color: #ff4444; font-weight: bold;")
                else:
                    status.setText("🔔 Due")
                    status.setStyleSheet("color: #ffaa00;")
            # Check snooze
            if snooze:
                try:
                    dt = datetime.datetime.strptime(snooze, "%Y-%m-%d %H:%M:%S")
                    if now < dt:
                        status.setText(f"Snoozed {dt.strftime('%H:%M')}")
                        status.setStyleSheet("color: #ffcc00;")
                except:
                    pass
            h.addWidget(title_lbl, 1)
            h.addWidget(status)
            item = QListWidgetItem()
            item.setSizeHint(w.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, tid)
            self.dash_list.addItem(item)
            self.dash_list.setItemWidget(item, w)

    def _dash_context_menu(self, pos):
        item = self.dash_list.itemAt(pos)
        if not item:
            return
        tid = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu()
        paid_action = menu.addAction("✔ Paid")
        menu.addSeparator()
        edit_action = menu.addAction("Edit")
        delete_action = menu.addAction("Delete")
        action = menu.exec(self.dash_list.viewport().mapToGlobal(pos))
        if action == paid_action:
            self._mark_paid(tid)
        elif action == edit_action:
            self._edit_task(tid)
        elif action == delete_action:
            self._delete_task(tid)

    def _edit_selected(self, item):
        tid = item.data(Qt.ItemDataRole.UserRole)
        self._edit_task(tid)

    def _mark_paid(self, tid):
        self.db.mark_paid(tid, None)  # None for year_month (will be determined from current_due)
        self.refresh_dashboard()

    def _edit_task(self, tid):
        tasks = self.db.get_all_tasks()
        task = next((t for t in tasks if t[0] == tid), None)
        if not task:
            return
        dlg = EditTaskDialog(task, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            # data: (id, title, desc, due_day, start_before, alarm_time, interval)
            self.db.update_task(data[0], data[1], data[2], data[3], data[4], data[5], data[6])
            self.refresh_dashboard()

    def _delete_task(self, tid):
        r = QMessageBox.question(self, "Delete", "Delete this task?")
        if r == QMessageBox.StandardButton.Yes:
            self.db.delete_task(tid)
            self.refresh_dashboard()

    def _history_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.hist_list = QListWidget()
        layout.addWidget(QLabel("📆 Payment History by Month"))
        layout.addWidget(self.hist_list)
        return page

    def _load_history(self):
        self.hist_list.clear()
        for ym, titles in self.db.get_paid_history_grouped_by_month():
            self.hist_list.addItem(f"📅 {ym}: {titles}")

    def _add_task_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.inp_title = QLineEdit()
        self.inp_desc = QTextEdit()
        self.inp_desc.setMaximumHeight(80)
        self.inp_due = QSpinBox()
        self.inp_due.setRange(1,31)
        self.inp_due.setValue(20)
        self.inp_start = QSpinBox()
        self.inp_start.setRange(1,30)
        self.inp_start.setValue(12)
        self.inp_time = QTimeEdit()
        self.inp_time.setTime(QTime(9,0))
        self.inp_recur = QComboBox()
        self.inp_recur.addItems(["1 month", "2 months", "3 months", "6 months", "12 months"])
        form.addRow("Title:", self.inp_title)
        form.addRow("Description:", self.inp_desc)
        form.addRow("Due Date (day):", self.inp_due)
        form.addRow("Start days before:", self.inp_start)
        form.addRow("Alarm time:", self.inp_time)
        form.addRow("Recurrence:", self.inp_recur)
        btn = QPushButton("Add Task")
        btn.clicked.connect(self._add_task)
        layout.addLayout(form)
        layout.addWidget(btn)
        layout.addStretch()
        return page

    def _add_task(self):
        title = self.inp_title.text().strip()
        if not title:
            QMessageBox.warning(self, "Error", "Title required!")
            return
        interval = [1,2,3,6,12][self.inp_recur.currentIndex()]
        self.db.add_task(
            title,
            self.inp_desc.toPlainText().strip(),
            self.inp_due.value(),
            self.inp_start.value(),
            self.inp_time.time().toString("HH:mm"),
            interval
        )
        QMessageBox.information(self, "Success", "Task added!")
        self.inp_title.clear()
        self.inp_desc.clear()
        self.switch_page(0)

    def _settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        w = QWidget()
        sl = QVBoxLayout(w)

        g = QGroupBox("🚀 Windows Startup")
        self.chk_startup = QCheckBox("Start with Windows")
        self.chk_startup.setChecked(self.db.get_setting("auto_start") == "1")
        self.chk_startup.stateChanged.connect(lambda s: (enable_startup() if s else disable_startup(), self.db.set_setting("auto_start", "1" if s else "0")))
        g.setLayout(QHBoxLayout())
        g.layout().addWidget(self.chk_startup)
        sl.addWidget(g)

        g = QGroupBox("🔔 Alarm Sound")
        self.lbl_sound = QLabel(self.db.get_setting("alarm_sound_path") or "Not selected")
        btn = QPushButton("Browse...")
        btn.clicked.connect(self._choose_sound)
        h = QHBoxLayout()
        h.addWidget(QLabel("File:"))
        h.addWidget(self.lbl_sound)
        h.addWidget(btn)
        g.setLayout(h)
        sl.addWidget(g)

        g = QGroupBox("⏱ Default Snooze (min)")
        self.spin_snooze = QSpinBox()
        self.spin_snooze.setRange(1,60)
        self.spin_snooze.setValue(int(self.db.get_setting("default_snooze_minutes")))
        h = QHBoxLayout()
        h.addWidget(QLabel("Minutes:"))
        h.addWidget(self.spin_snooze)
        g.setLayout(h)
        sl.addWidget(g)

        g = QGroupBox("📬 Desktop Notifications")
        self.chk_notif = QCheckBox("Enable toast")
        self.chk_notif.setChecked(self.db.get_setting("desktop_notifications") == "1")
        g.setLayout(QHBoxLayout())
        g.layout().addWidget(self.chk_notif)
        sl.addWidget(g)

        btn_save = QPushButton("💾 Save Settings")
        btn_save.clicked.connect(self._save_settings)
        sl.addWidget(btn_save)

        g = QGroupBox("🗄 Backup / Restore")
        h = QHBoxLayout()
        h.addWidget(QPushButton("Backup", clicked=self._backup))
        h.addWidget(QPushButton("Restore", clicked=self._restore))
        g.setLayout(h)
        sl.addWidget(g)

        sl.addStretch()
        scroll.setWidget(w)
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