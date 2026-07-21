import sys
import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QVBoxLayout, QHBoxLayout,
    QWidget, QLabel, QPushButton, QListWidget, QListWidgetItem, QFormLayout,
    QSpinBox, QLineEdit, QTextEdit, QMessageBox, QSystemTrayIcon,
    QMenu, QFileDialog, QCheckBox, QTimeEdit, QGroupBox, QScrollArea, QComboBox,
    QFrame
)
from PyQt6.QtCore import Qt, QTimer, QTime
from PyQt6.QtGui import QIcon, QAction

from utils import is_already_running, create_app_icon, get_app_dir
from db import DatabaseManager
from sound import play_alarm_sound, stop_alarm_sound
from alarm import AlarmChecker, AlarmPopup
from dialogs import EditTaskDialog

# ===================== AUTO-START =====================
def enable_startup():
    import winreg
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
    import winreg
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

        # System Tray
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

        # Central widget
        central = QWidget()
        central.setObjectName("mainWindow")
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(180)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setSpacing(8)
        sb_layout.setContentsMargins(12, 20, 12, 20)

        title_lbl = QLabel("📌 Remind")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #00e5ff;")
        sb_layout.addWidget(title_lbl)
        sb_layout.addSpacing(16)

        self.btn_dash = self._nav_button("📊", "Dashboard", 0)
        self.btn_hist = self._nav_button("📅", "History", 1)
        self.btn_add = self._nav_button("➕", "Add", 2)
        self.btn_sett = self._nav_button("⚙", "Settings", 3)

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
            QMainWindow, QWidget#mainWindow { background: #121212; }
            QWidget#sidebar {
                background: #1a1a1a;
                border-right: 1px solid #2a2a2a;
            }
            QPushButton#navBtn {
                text-align: left;
                padding: 10px 14px;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 500;
                color: #aaa;
                background: transparent;
            }
            QPushButton#navBtn:hover { background: #2a2a2a; color: #eee; }
            QPushButton#navBtn:checked {
                background: #00e5ff;
                color: #121212;
                font-weight: bold;
            }
            QScrollArea { border: none; background: transparent; }
            QLabel { color: #ddd; }
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
                padding: 4px;
            }
            QListWidget::item { border: none; padding: 2px; }
            QListWidget::item:selected { background: #2a2a2a; }
            QGroupBox {
                border: 1px solid #333;
                border-radius: 10px;
                margin-top: 10px;
                padding-top: 14px;
                background: #1a1a1a;
            }
            QGroupBox::title { color: #00e5ff; }
            QLineEdit, QTextEdit, QSpinBox, QComboBox, QTimeEdit {
                background: #252525;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 6px;
                color: #eee;
            }
            QPushButton {
                background: #00e5ff;
                color: #121212;
                border: none;
                border-radius: 6px;
                padding: 8px 14px;
                font-weight: bold;
            }
            QPushButton:hover { background: #00bcd4; }
            QPushButton:pressed { background: #00838f; }
            QPushButton#danger { background: #c62828; color: white; }
            QPushButton#danger:hover { background: #b71c1c; }
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
        page.setStyleSheet("background: #121212;")
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("📋 Dashboard")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #eee;")
        layout.addWidget(header)

        self.dash_list = QListWidget()
        self.dash_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; }
            QListWidget::item { border: none; padding: 2px; }
        """)
        self.dash_list.setSpacing(6)
        layout.addWidget(self.dash_list)
        return page

    def refresh_dashboard(self):
        self.dash_list.clear()
        tasks = self.db.get_all_tasks()
        now = datetime.datetime.now()
        current_ym = now.strftime("%Y-%m")

        for t in tasks:
            tid, title, desc, due_day, paid_month, snooze, start_before, alarm_time, interval, current_due = t

            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background: #1e1e1e;
                    border-radius: 10px;
                    padding: 12px 16px;
                    border: 1px solid #2a2a2a;
                }
                QFrame:hover { border-color: #00e5ff; }
            """)
            card_layout = QHBoxLayout(card)
            card_layout.setSpacing(12)

            # Left: title + details
            info = QVBoxLayout()
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet("font-size: 15px; font-weight: 600; color: #eee;")
            info.addWidget(title_lbl)

            due_str = f"Due: {due_day}  •  Alarm: {alarm_time}"
            info.addWidget(QLabel(due_str))

            # Status indicator
            status_text = ""
            status_color = ""
            if current_due == "9999-12":
                status_text = "Done"
                status_color = "#4caf50"
            elif current_due and current_due > current_ym:
                status_text = "Upcoming"
                status_color = "#4fc3f7"
            else:
                if current_due and current_due < current_ym:
                    status_text = "Overdue"
                    status_color = "#ff5252"
                else:
                    status_text = "Due"
                    status_color = "#ffb300"

            if snooze:
                try:
                    dt = datetime.datetime.strptime(snooze, "%Y-%m-%d %H:%M:%S")
                    if now < dt:
                        status_text = f"Snoozed {dt.strftime('%H:%M')}"
                        status_color = "#ffca28"
                except:
                    pass

            status_lbl = QLabel(f"● {status_text}")
            status_lbl.setStyleSheet(f"color: {status_color}; font-weight: bold; font-size: 13px;")
            info.addWidget(status_lbl)

            # Actions
            actions = QHBoxLayout()
            actions.setSpacing(6)

            # Toggle Paid/Unpaid
            is_paid = (current_due and current_due > current_ym) or (current_due == "9999-12")
            if is_paid:
                btn_pay = QPushButton("↩ Unpaid")
                btn_pay.setStyleSheet("background: #7f0000; color: white; padding: 4px 10px; font-size: 12px;")
                btn_pay.clicked.connect(lambda checked, t=tid: self._toggle_unpaid(t))
            else:
                btn_pay = QPushButton("✔ Paid")
                btn_pay.setStyleSheet("background: #2e7d32; color: white; padding: 4px 10px; font-size: 12px;")
                btn_pay.clicked.connect(lambda checked, t=tid: self._toggle_paid(t))

            btn_edit = QPushButton("✏️")
            btn_edit.setStyleSheet("background: #00695c; color: white; padding: 4px 10px; font-size: 12px;")
            btn_edit.clicked.connect(lambda checked, t=tid: self._edit_task(t))

            btn_delete = QPushButton("🗑")
            btn_delete.setObjectName("danger")
            btn_delete.setStyleSheet("background: #c62828; color: white; padding: 4px 10px; font-size: 12px;")
            btn_delete.clicked.connect(lambda checked, t=tid: self._delete_task(t))

            actions.addWidget(btn_pay)
            actions.addWidget(btn_edit)
            actions.addWidget(btn_delete)
            actions.addStretch()

            info.addLayout(actions)

            card_layout.addLayout(info, 1)
            card_layout.addWidget(status_lbl, alignment=Qt.AlignmentFlag.AlignTop)

            item = QListWidgetItem()
            item.setSizeHint(card.sizeHint())
            self.dash_list.addItem(item)
            self.dash_list.setItemWidget(item, card)

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
        page.setStyleSheet("background: #121212;")
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("📆 Payment History")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #eee;")
        layout.addWidget(header)

        self.hist_list = QListWidget()
        self.hist_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; }
            QListWidget::item { border: none; padding: 6px; background: #1e1e1e; border-radius: 6px; margin-bottom: 2px; }
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
        page.setStyleSheet("background: #121212;")
        layout = QVBoxLayout(page)
        layout.setSpacing(16)
        layout.setContentsMargins(30, 30, 30, 30)

        header = QLabel("➕ New Reminder")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #eee;")
        layout.addWidget(header)

        form_widget = QWidget()
        form_widget.setStyleSheet("background: #1e1e1e; border-radius: 12px; padding: 20px;")
        form_layout = QFormLayout(form_widget)
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.inp_title = QLineEdit()
        self.inp_title.setPlaceholderText("e.g., Rent")
        self.inp_desc = QTextEdit()
        self.inp_desc.setMaximumHeight(70)
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
        btn_add.setStyleSheet("font-size: 15px; padding: 10px; background: #00e5ff;")
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
        page.setStyleSheet("background: #121212;")
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("⚙ Settings")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #eee;")
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        sl = QVBoxLayout(content)
        sl.setSpacing(12)

        # Startup
        g = QGroupBox("🚀 Startup")
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
        h = QHBoxLayout(g)
        self.lbl_sound = QLabel(self.db.get_setting("alarm_sound_path") or "Not selected")
        self.lbl_sound.setStyleSheet("color: #aaa;")
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._choose_sound)
        btn_test = QPushButton("🔊 Test")
        btn_test.clicked.connect(self._test_sound)
        h.addWidget(QLabel("File:"))
        h.addWidget(self.lbl_sound, 1)
        h.addWidget(btn_browse)
        h.addWidget(btn_test)
        sl.addWidget(g)

        # Snooze
        g = QGroupBox("⏱ Default Snooze")
        h = QHBoxLayout(g)
        self.spin_snooze = QSpinBox()
        self.spin_snooze.setRange(1,60)
        self.spin_snooze.setValue(int(self.db.get_setting("default_snooze_minutes")))
        h.addWidget(QLabel("Minutes:"))
        h.addWidget(self.spin_snooze)
        sl.addWidget(g)

        # Notifications
        g = QGroupBox("📬 Notifications")
        h = QHBoxLayout(g)
        self.chk_notif = QCheckBox("Enable toast")
        self.chk_notif.setStyleSheet("color: #eee;")
        self.chk_notif.setChecked(self.db.get_setting("desktop_notifications") == "1")
        h.addWidget(self.chk_notif)
        sl.addWidget(g)

        # Save
        btn_save = QPushButton("💾 Save Settings")
        btn_save.setStyleSheet("padding: 10px; font-size: 14px;")
        btn_save.clicked.connect(self._save_settings)
        sl.addWidget(btn_save)

        # Backup / Restore
        g = QGroupBox("🗄 Backup & Restore")
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