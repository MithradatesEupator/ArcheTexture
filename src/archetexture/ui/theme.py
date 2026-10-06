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
    """Small centralized styling for controls that do not consistently follow QPalette."""
    if mode == "system":
        return ""
    if mode == "dark":
        border = "#3d424a"
        hover = "#3a4048"
    else:
        border = "#c5c9cf"
        hover = "#e4eaf1"
    return f"""
        QMenu {{ border: 1px solid {border}; }}
        QMenu::item:selected {{
            background-color: palette(highlight);
            color: palette(highlighted-text);
        }}
        QToolTip {{ padding: 4px; border: 1px solid {border}; }}
        QSplitter::handle {{ background-color: palette(mid); }}
        QScrollBar:vertical {{ width: 12px; margin: 0; background: palette(window); }}
        QScrollBar:horizontal {{ height: 12px; margin: 0; background: palette(window); }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
            min-width: 20px; min-height: 20px; border-radius: 4px;
            background: palette(mid);
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
