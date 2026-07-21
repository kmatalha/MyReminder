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

        # Sidebar (glass)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setSpacing(8)
        sb_layout.setContentsMargins(20, 28, 20, 28)

        title_lbl = QLabel("✨ Remind")
        title_lbl.setStyleSheet("""
            font-size: 20px;
            font-weight: 700;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 #a855f7, stop:1 #ec4899);
            -webkit-background-clip: text;
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
            QMainWindow, QWidget#mainWindow {
                background: rgba(15, 15, 26, 0.92);
            }
            QWidget#sidebar {
                background: rgba(255,255,255,0.04);
                backdrop-filter: blur(16px);
                border-right: 1px solid rgba(255,255,255,0.06);
            }
            QPushButton#navBtn {
                text-align: left;
                padding: 12px 16px;
                border: none;
                border-radius: 16px;
                font-size: 14px;
                font-weight: 500;
                color: rgba(255,255,255,0.6);
                background: transparent;
            }
            QPushButton#navBtn:hover {
                background: rgba(255,255,255,0.05);
                color: #fff;
            }
            QPushButton#navBtn:checked {
                background: rgba(168, 85, 247, 0.25);
                color: #fff;
                border: 1px solid rgba(168, 85, 247, 0.3);
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
            QListWidget::item:selected { background: rgba(168, 85, 247, 0.15); border-radius: 12px; }
            QGroupBox {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 16px;
                margin-top: 10px;
                padding-top: 14px;
            }
            QGroupBox::title { color: #c084fc; }
            QLineEdit, QTextEdit, QSpinBox, QComboBox, QTimeEdit {
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
                padding: 8px 12px;
                color: #eee;
            }
            QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus {
                border-color: #a855f7;
            }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #a855f7, stop:1 #ec4899);
                color: #fff;
                border: none;
                border-radius: 40px;
                padding: 10px 20px;
                font-weight: 600;
            }
            QPushButton:hover { opacity: 0.9; }
            QPushButton:pressed { opacity: 0.7; }
            QPushButton#danger {
                background: rgba(248, 113, 113, 0.15);
                color: #f87171;
                border: 1px solid rgba(248, 113, 113, 0.2);
            }
            QPushButton#danger:hover { background: rgba(248, 113, 113, 0.25); }
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
        layout.setSpacing(12)
        layout.setContentsMargins(28, 28, 28, 28)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("📋 Dashboard")
        title.setStyleSheet("font-size: 22px; font-weight: 600; color: #fff;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        badge = QLabel("5 tasks")
        badge.setStyleSheet("""
            background: rgba(168, 85, 247, 0.15);
            color: #c084fc;
            padding: 4px 14px;
            border-radius: 40px;
            font-size: 13px;
            font-weight: 500;
            border: 1px solid rgba(168, 85, 247, 0.2);
        """)
        header_layout.addWidget(badge)
        layout.addWidget(header_widget)

        self.dash_list = QListWidget()
        self.dash_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; }
            QListWidget::item { border: none; padding: 2px; }
        """)
        self.dash_list.setSpacing(8)
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

            # Glass card
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background: rgba(255,255,255,0.04);
                    border-radius: 20px;
                    padding: 14px 20px;
                    border: 1px solid rgba(255,255,255,0.06);
                }
                QFrame:hover {
                    background: rgba(255,255,255,0.08);
                    border-color: rgba(168, 85, 247, 0.3);
                }
            """)
            card_layout = QHBoxLayout(card)
            card_layout.setSpacing(16)

            # Info
            info = QVBoxLayout()
            info.setSpacing(2)
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet("font-size: 16px; font-weight: 600; color: #fff;")
            info.addWidget(title_lbl)

            meta = QLabel(f"📅 Due: {due_day}  •  ⏰ {alarm_time}")
            meta.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 13px;")
            info.addWidget(meta)

            # Status pill
            pill = QFrame()
            pill.setStyleSheet("""
                QFrame {
                    background: rgba(255,255,255,0.04);
                    border-radius: 40px;
                    padding: 4px 12px 4px 8px;
                    border: 1px solid rgba(255,255,255,0.06);
                }
            """)
            pill_layout = QHBoxLayout(pill)
            pill_layout.setContentsMargins(4, 2, 8, 2)
            pill_layout.setSpacing(6)

            dot = QLabel()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet("border-radius: 5px;")

            status_text = ""
            color = ""
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

            dot.setStyleSheet(f"background: {color}; border-radius: 5px;")
            status_lbl = QLabel(status_text)
            status_lbl.setStyleSheet(f"color: {color}; font-weight: 500; font-size: 13px;")
            pill_layout.addWidget(dot)
            pill_layout.addWidget(status_lbl)
            info.addWidget(pill)

            card_layout.addLayout(info, 1)

            # Actions
            actions = QHBoxLayout()
            actions.setSpacing(6)

            # Toggle Paid/Unpaid
            is_paid = (current_due and current_due > current_ym) or (current_due == "9999-12")
            if is_paid:
                btn_pay = QPushButton("↩ Unpaid")
                btn_pay.setStyleSheet("""
                    QPushButton {
                        background: rgba(248, 113, 113, 0.15);
                        color: #f87171;
                        border: 1px solid rgba(248, 113, 113, 0.2);
                        border-radius: 40px;
                        padding: 4px 14px;
                        font-size: 12px;
                        font-weight: 600;
                    }
                    QPushButton:hover { background: rgba(248, 113, 113, 0.25); }
                """)
                btn_pay.clicked.connect(lambda checked, t=tid: self._toggle_unpaid(t))
            else:
                btn_pay = QPushButton("✔ Paid")
                btn_pay.setStyleSheet("""
                    QPushButton {
                        background: rgba(52, 211, 153, 0.15);
                        color: #34d399;
                        border: 1px solid rgba(52, 211, 153, 0.2);
                        border-radius: 40px;
                        padding: 4px 14px;
                        font-size: 12px;
                        font-weight: 600;
                    }
                    QPushButton:hover { background: rgba(52, 211, 153, 0.25); }
                """)
                btn_pay.clicked.connect(lambda checked, t=tid: self._toggle_paid(t))

            btn_edit = QPushButton("✏️")
            btn_edit.setStyleSheet("""
                QPushButton {
                    background: rgba(255,255,255,0.04);
                    border: 1px solid rgba(255,255,255,0.06);
                    border-radius: 40px;
                    padding: 4px 10px;
                    font-size: 14px;
                    color: #aaa;
                }
                QPushButton:hover { background: rgba(255,255,255,0.08); }
            """)
            btn_edit.clicked.connect(lambda checked, t=tid: self._edit_task(t))

            btn_delete = QPushButton("🗑")
            btn_delete.setStyleSheet("""
                QPushButton {
                    background: rgba(248, 113, 113, 0.08);
                    border: 1px solid rgba(248, 113, 113, 0.1);
                    border-radius: 40px;
                    padding: 4px 10px;
                    font-size: 14px;
                    color: #f87171;
                }
                QPushButton:hover { background: rgba(248, 113, 113, 0.2); }
            """)
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

        # Update badge
        badge = self.findChild(QLabel, "badge")
        if badge:
            badge.setText(f"{count} tasks")

    # ----- History, Add, Settings, etc. (same as before, with updated styles) -----
    # ... (keep all existing methods: _history_page, _add_task_page, _settings_page, etc.)
    # I'll include them for completeness below.
