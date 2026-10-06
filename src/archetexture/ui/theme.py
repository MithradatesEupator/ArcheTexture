from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

_PALETTE_COLORS = {
    "dark": {
        QPalette.ColorRole.Window: "#1b1d21",
        QPalette.ColorRole.WindowText: "#e7e9ec",
        QPalette.ColorRole.Base: "#191b1f",
        QPalette.ColorRole.AlternateBase: "#24272d",
        QPalette.ColorRole.ToolTipBase: "#30343a",
        QPalette.ColorRole.ToolTipText: "#e7e9ec",
        QPalette.ColorRole.Text: "#e7e9ec",
        QPalette.ColorRole.Button: "#30343a",
        QPalette.ColorRole.ButtonText: "#e7e9ec",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Link: "#8ab4e6",
        QPalette.ColorRole.LinkVisited: "#b49add",
        QPalette.ColorRole.Highlight: "#426f9f",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Light: "#4a5059",
        QPalette.ColorRole.Midlight: "#353a42",
        QPalette.ColorRole.Dark: "#15171a",
        QPalette.ColorRole.Mid: "#3d424a",
        QPalette.ColorRole.Shadow: "#111214",
        QPalette.ColorRole.PlaceholderText: "#969ca5",
    },
    "light": {
        QPalette.ColorRole.Window: "#f0f1f3",
        QPalette.ColorRole.WindowText: "#202328",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f5f6f8",
        QPalette.ColorRole.ToolTipBase: "#fffbe6",
        QPalette.ColorRole.ToolTipText: "#202328",
        QPalette.ColorRole.Text: "#202328",
        QPalette.ColorRole.Button: "#f3f4f6",
        QPalette.ColorRole.ButtonText: "#202328",
        QPalette.ColorRole.BrightText: "#a40000",
        QPalette.ColorRole.Link: "#245f9e",
        QPalette.ColorRole.LinkVisited: "#684a91",
        QPalette.ColorRole.Highlight: "#3978b8",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Light: "#ffffff",
        QPalette.ColorRole.Midlight: "#e6e8eb",
        QPalette.ColorRole.Dark: "#aeb3bb",
        QPalette.ColorRole.Mid: "#c5c9cf",
        QPalette.ColorRole.Shadow: "#80858d",
        QPalette.ColorRole.PlaceholderText: "#727780",
    },
}


def palette_for_mode(mode: str, system_palette: QPalette) -> QPalette:
    """Build a complete palette for explicit themes or return the system palette."""
    if mode == "system":
        return QPalette(system_palette)
    colors = _PALETTE_COLORS[mode]
    palette = QPalette()
    for role, value in colors.items():
        color = QColor(value)
        palette.setColor(QPalette.ColorGroup.Active, role, color)
        palette.setColor(QPalette.ColorGroup.Inactive, role, color)
        palette.setColor(QPalette.ColorGroup.Disabled, role, color)

    if mode == "dark":
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            palette.setColor(group, QPalette.ColorRole.WindowText, QColor("#e7e9ec"))
            palette.setColor(group, QPalette.ColorRole.Text, QColor("#e7e9ec"))
            palette.setColor(group, QPalette.ColorRole.ButtonText, QColor("#e7e9ec"))
        disabled = {
            QPalette.ColorRole.WindowText: "#a3a8b0",
            QPalette.ColorRole.Text: "#969ca5",
            QPalette.ColorRole.ButtonText: "#a3a8b0",
            QPalette.ColorRole.Base: "#1c1f23",
            QPalette.ColorRole.Button: "#292c31",
            QPalette.ColorRole.Highlight: "#343a42",
            QPalette.ColorRole.HighlightedText: "#c4c8ce",
        }
        for role, value in disabled.items():
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(value))
    else:
        disabled = {
            QPalette.ColorRole.WindowText: "#747982",
            QPalette.ColorRole.Text: "#747982",
            QPalette.ColorRole.ButtonText: "#747982",
        }
        for role, value in disabled.items():
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(value))
    return palette


def theme_stylesheet(mode: str) -> str:
    """Return centralized surface and control styling for explicit themes."""
    if mode == "system":
        return ""
    if mode == "dark":
        window, base, alternate = "#1b1d21", "#191b1f", "#22262b"
        button, raised, border = "#30343a", "#292c31", "#3d424a"
        text, muted, highlight, highlighted = "#e7e9ec", "#a3a8b0", "#426f9f", "#ffffff"
        hover, pressed = "#3a4048", "#343a42"
    else:
        window, base, alternate = "#f0f1f3", "#ffffff", "#f5f6f8"
        button, raised, border = "#f3f4f6", "#e9ebee", "#c5c9cf"
        text, muted, highlight, highlighted = "#202328", "#747982", "#3978b8", "#ffffff"
        hover, pressed = "#e4eaf1", "#d5e1ef"
    return f"""
        QWidget {{ color: {text}; }}
        QMainWindow, QDialog, QTabWidget::pane {{ background: {window}; }}
        QWidget#property-editor, QWidget#control-fields-editor,
        QWidget#control-operation-properties {{ background: {window}; }}
        QLabel#project-size-warning {{ color: {highlight}; }}
        QMenuBar, QToolBar, QStatusBar {{ background: {window}; color: {text}; }}
        QToolBar {{ border: 0; spacing: 4px; padding: 3px; }}
        QStatusBar::item {{ border: 0; }}
        QTabWidget::pane {{ border: 1px solid {border}; top: -1px; }}
        QTabBar {{ background: {window}; }}
        QTabBar::tab {{
            background: {raised}; color: {text}; border: 1px solid {border};
            padding: 6px 10px; margin-right: 2px;
        }}
        QTabBar::tab:selected {{ background: {window}; border-bottom-color: {window}; }}
        QTabBar::tab:hover:!selected {{ background: {hover}; }}
        QTabBar::tab:disabled {{ background: {window}; color: {muted}; }}
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
        QAbstractItemView, QListWidget, QListView, QTreeWidget, QTreeView {{
            background: {base}; alternate-background-color: {alternate}; color: {text};
            border: 1px solid {border}; selection-background-color: {highlight};
            selection-color: {highlighted};
        }}
        QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
        QComboBox:disabled, QAbstractItemView:disabled, QListWidget:disabled,
        QListView:disabled, QTreeWidget:disabled, QTreeView:disabled {{
            background: {base}; color: {muted}; border-color: {border};
        }}
        QComboBox::drop-down {{
            background: {raised}; border-left: 1px solid {border}; width: 20px;
        }}
        QComboBox QAbstractItemView {{ background: {base}; border: 1px solid {border}; }}
        QPushButton, QToolButton {{
            background: {button}; color: {text}; border: 1px solid {border};
            padding: 4px 8px;
        }}
        QPushButton:hover, QToolButton:hover {{ background: {hover}; }}
        QPushButton:pressed, QToolButton:pressed {{ background: {pressed}; }}
        QPushButton:disabled, QToolButton:disabled {{
            background: {raised}; color: {muted}; border-color: {border};
        }}
        QCheckBox:disabled {{ color: {muted}; }}
        QMenuBar::item {{ background: transparent; color: {text}; padding: 4px 8px; }}
        QMenuBar::item:selected, QMenuBar::item:pressed {{ background: {raised}; }}
        QMenu {{ background: {window}; color: {text}; border: 1px solid {border}; }}
        QMenu::item {{ padding: 4px 24px 4px 20px; }}
        QMenu::item:selected {{ background: {highlight}; color: {highlighted}; }}
        QMenu::item:disabled {{ color: {muted}; background: transparent; }}
        QToolTip {{
            background: {raised}; color: {text}; padding: 4px; border: 1px solid {border};
        }}
        QSplitter::handle {{ background: {border}; }}
        QScrollBar:vertical {{ width: 12px; margin: 0; background: {window}; }}
        QScrollBar:horizontal {{ height: 12px; margin: 0; background: {window}; }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
            min-width: 20px; min-height: 20px; border-radius: 4px; background: {border};
        }}
        QScrollBar::handle:hover {{ background: {hover}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """


def workspace_checkerboard_colors(palette: QPalette) -> tuple[QColor, QColor, QColor]:
    """Return background and alternating tiles appropriate to the effective palette."""
    dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
    if dark:
        return QColor("#17191c"), QColor("#22262b"), QColor("#2b3036")
    window = palette.color(QPalette.ColorRole.Window)
    base = palette.color(QPalette.ColorRole.Base)
    alternate = palette.color(QPalette.ColorRole.AlternateBase)
    return window, base, alternate


def ramp_checkerboard_colors(palette: QPalette) -> tuple[QColor, QColor]:
    """Return subdued checker tiles used to show alpha beneath color-ramp content."""
    if palette.color(QPalette.ColorRole.Window).lightness() < 128:
        return QColor("#444952"), QColor("#30343b")
    return QColor("#ffffff"), QColor("#cfd4dc")
