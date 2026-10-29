"""Tema escuro do app (mesmos tokens do frontend antigo) em QSS."""

BG, BG2, PANEL, PANEL2 = "#0a0e16", "#0d1320", "#121826", "#171f31"
BORDER, BORDER_STRONG = "#1c2335", "#2a3550"
TEXT, MUTED = "#e7ecf5", "#8a94a6"
ACCENT, ACCENT_SOFT = "#22d3ee", "#12323d"
LIVE, REC, WARN = "#34d399", "#f87171", "#fbbf24"

QSS = f"""
* {{ font-size: 13px; }}
QWidget {{ background: {BG}; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[title="true"] {{ font-size: 15px; font-weight: 600; }}
QLabel[big="true"] {{ font-size: 30px; font-weight: 700; }}
QFrame#panel, QFrame#tile, QFrame#sidebar {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#sidebar {{ border-radius: 0; border-top: 0; border-bottom: 0; border-left: 0; }}
QWidget[plain="true"] {{ background: transparent; }}
QFrame#row {{ background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame#card {{ background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 10px; }}
QPushButton {{ background: {PANEL2}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; }}
QPushButton:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton[primary="true"] {{ background: {ACCENT}; color: #04222a; border: 0; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: #67e8f9; }}
QPushButton[ghost="true"] {{ background: transparent; border-color: transparent; color: {MUTED}; }}
QPushButton[ghost="true"]:hover {{ color: {TEXT}; }}
QPushButton[mini="true"] {{ padding: 3px 9px; font-size: 12px; }}
QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {{
  background: {BG2}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 6px 8px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {BORDER_STRONG}; selection-background-color: {ACCENT_SOFT}; }}
QListWidget, QTreeWidget {{ background: transparent; border: 0; outline: 0; }}
QListWidget::item {{ padding: 8px; border-radius: 8px; }}
QListWidget::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {BORDER_STRONG}; background: {BG2}; }}
QListWidget::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QListWidget::item:selected, QListWidget::item:hover {{ background: {PANEL2}; }}
QTreeWidget::item {{ padding: 3px; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 34px; height: 18px; border-radius: 9px; background: {BORDER_STRONG}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; }}
QCheckBox[plain="true"]::indicator {{ width: 16px; height: 16px; border-radius: 4px; }}
QScrollArea {{ border: 0; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QToolTip {{ background: {PANEL2}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; padding: 4px; }}
QMessageBox {{ background: {PANEL}; }}
"""
