import sqlite3
import datetime
import os
from utils import get_app_dir

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
            try:
                dt = datetime.datetime.strptime(at, "%H:%M")
                normalized = dt.strftime("%H:%M")
                if normalized != at:
                    self.cursor.execute("UPDATE tasks SET alarm_time=? WHERE id=?", (normalized, tid))
            except (ValueError, TypeError):
                self.cursor.execute("UPDATE tasks SET alarm_time='09:00' WHERE id=?", (tid,))
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
        try:
            dt = datetime.datetime.strptime(alarm_time, "%H:%M")
            alarm_time = dt.strftime("%H:%M")
        except:
            alarm_time = "09:00"
        self.cursor.execute(
            """INSERT INTO tasks 
               (title, description, due_day, start_days_before, alarm_time, recurrence_interval, current_due_month)
               VALUES (?,?,?,?,?,?,?)""",
            (title, description, due_day, start_days_before, alarm_time, recurrence_interval, due_month)
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def update_task(self, task_id, title, description, due_day, start_days_before, alarm_time, recurrence_interval, due_month):
        try:
            dt = datetime.datetime.strptime(alarm_time, "%H:%M")
            alarm_time = dt.strftime("%H:%M")
        except:
            alarm_time = "09:00"
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
        """Revert the last payment for this task (set due month to last paid month)."""
        # Get the most recent history entry for this task
        self.cursor.execute(
            "SELECT year_month FROM paid_history WHERE task_id=? ORDER BY paid_timestamp DESC LIMIT 1",
            (task_id,)
        )
        row = self.cursor.fetchone()
        if not row:
            # No history – just set current_due_month to current month
            current = datetime.datetime.now().strftime("%Y-%m")
            self.cursor.execute("UPDATE tasks SET current_due_month=? WHERE id=?", (current, task_id))
            self.conn.commit()
            return
        last_paid_month = row[0]
        # Delete that history entry
        self.cursor.execute(
            "DELETE FROM paid_history WHERE task_id=? AND year_month=? AND paid_timestamp = (SELECT paid_timestamp FROM paid_history WHERE task_id=? ORDER BY paid_timestamp DESC LIMIT 1)",
            (task_id, last_paid_month, task_id)
        )
        # Set current_due_month to that month
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