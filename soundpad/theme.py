from __future__ import annotations

import copy
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from .resources import resource_path


DEFAULT_THEME: dict[str, Any] = {
    "text": {
        "primary": "#edf0f4",
        "secondary": "#aab2bf",
        "strong": "#ffffff",
        "warning": "#ffca58",
    },
    "surface": {
        "window": "#20242b",
        "panel": "#2b3038",
        "panel_pressed": "#20262f",
        "panel_empty": "#262b33",
        "panel_ready": "#263830",
        "panel_missing": "#3a3026",
        "input": "#2b3038",
        "menu": "#2b3038",
        "dialog": "#20242b",
        "border": "#4d5664",
        "border_muted": "#3b424d",
        "accent": "#67d5b5",
        "accent_muted": "#3f695d",
        "selection": "#465161",
        "drag_hover_border": "#6ee7ff",
    },
    "button": {
        "default": {
            "normal": "#39414d",
            "hover": "#465161",
            "pressed": "#303846",
            "border": "#4d5664",
            "text": "#edf0f4",
        },
        "danger": {
            "normal": "#6b2f35",
            "hover": "#803942",
            "pressed": "#57272d",
            "border": "#c75f68",
            "text": "#ffffff",
        },
        "edit": {
            "normal": "#51415f",
            "hover": "#604e70",
            "pressed": "#443750",
            "border": "#806aa0",
            "text": "#ffffff",
        },
        "active": {
            "normal": "#3f695d",
            "hover": "#4b7b6e",
            "pressed": "#33564d",
            "border": "#67d5b5",
            "text": "#ffffff",
        },
    },
    "platform": {
        "windows_title_bar": {
            "enabled": True,
            "style": "dark",
            "header_color": "#20242b",
            "title_color": "#edf0f4",
            "border_color": "#3b424d",
        },
    },
    "waveform": {
        "background": "#16181d",
        "empty_text": "#7f8794",
        "wave": "#67d5b5",
        "selection": "#ffffff",
        "selection_alpha": 34,
        "fade_region": "#ffca58",
        "fade_region_alpha": 50,
        "fade_slope": "#ffffff",
        "handle": "#ffca58",
        "fade_handle": "#f08f5f",
        "knob_border": "#20242b",
        "zoom_text": "#aab2bf",
        "playhead": "#6ee7ff",
        "db_line": "#edf0f4",
        "db_line_alpha": 72,
        "db_label": "#aab2bf",
    },
}


@dataclass(frozen=True)
class Theme:
    values: dict[str, Any]

    def color(self, section: str, key: str) -> str:
        value = self.values[section][key]
        return str(value)

    def alpha(self, section: str, key: str) -> int:
        return int(self.values[section][key])

    def enabled(self, section: str, key: str) -> bool:
        value = self.values[section][key]
        return bool(value)


_current_theme = Theme(copy.deepcopy(DEFAULT_THEME))
_platform_window_filter: "PlatformWindowThemeFilter | None" = None


def load_theme(theme_path: Path | None = None) -> Theme:
    path = theme_path or resource_path("theme.toml")
    values = copy.deepcopy(DEFAULT_THEME)
    try:
        loaded = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        loaded = {}
    _deep_update(values, loaded)
    return Theme(values)


def apply_theme(app: QApplication, theme: Theme) -> None:
    global _current_theme
    _current_theme = theme
    app.setPalette(build_palette(theme))
    app.setStyleSheet(build_stylesheet(theme))
    install_platform_window_theme_filter(app, theme)


def install_platform_window_theme_filter(app: QApplication, theme: Theme) -> None:
    global _platform_window_filter
    if _platform_window_filter is not None:
        app.removeEventFilter(_platform_window_filter)
    _platform_window_filter = PlatformWindowThemeFilter(theme)
    app.installEventFilter(_platform_window_filter)


class PlatformWindowThemeFilter(QObject):
    def __init__(self, theme: Theme) -> None:
        super().__init__()
        self.theme = theme
        self._themed_windows: set[int] = set()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget) and watched.isWindow():
            window_id = int(watched.winId())
            if window_id not in self._themed_windows:
                self._themed_windows.add(window_id)
                QTimer.singleShot(
                    0,
                    lambda window=watched: apply_platform_window_theme(window, self.theme),
                )
        return super().eventFilter(watched, event)


def apply_platform_window_theme(window: Any, theme: Theme) -> bool:
    if sys.platform != "win32":
        return False

    settings = theme.values.get("platform", {}).get("windows_title_bar", {})
    if not bool(settings.get("enabled", False)):
        return False

    try:
        import pywinstyles
    except ImportError:
        return False

    try:
        style = str(settings.get("style", "dark"))
        if style:
            pywinstyles.apply_style(window, style)
        header_color = str(settings.get("header_color", ""))
        if header_color:
            pywinstyles.change_header_color(window, header_color)
        title_color = str(settings.get("title_color", ""))
        if title_color:
            pywinstyles.change_title_color(window, title_color)
        border_color = str(settings.get("border_color", ""))
        if border_color:
            pywinstyles.change_border_color(window, border_color)
    except Exception:
        return False
    return True


def get_theme() -> Theme:
    return _current_theme


def qcolor(section: str, key: str, alpha_key: str | None = None) -> QColor:
    theme = get_theme()
    color = QColor(theme.color(section, key))
    if alpha_key is not None:
        color.setAlpha(theme.alpha(section, alpha_key))
    return color


def build_palette(theme: Theme) -> QPalette:
    text = theme.values["text"]
    surface = theme.values["surface"]
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(surface["window"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(text["primary"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(surface["input"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(surface["panel"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(surface["panel"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(text["primary"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(text["primary"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(surface["panel"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(text["primary"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(surface["selection"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(text["strong"]))
    return palette


def build_stylesheet(theme: Theme) -> str:
    text = theme.values["text"]
    surface = theme.values["surface"]
    button = theme.values["button"]
    default = button["default"]
    danger = button["danger"]
    edit = button["edit"]
    active = button["active"]
    combo_arrow_path = resource_path("assets", "chevron-down.svg").as_posix()
    return f"""
        QWidget {{
            color: {text["primary"]};
            font-size: 14px;
        }}
        QMainWindow, #centralPanel {{
            background: {surface["window"]};
            color: {text["primary"]};
        }}
        #settingsDialog, QMessageBox, QInputDialog, QFileDialog {{
            background: {surface["dialog"]};
            color: {text["primary"]};
        }}
        #gridPanel, #pageStack, QStackedWidget, QStackedWidget > QWidget {{
            background: transparent;
            border: none;
        }}
        #plainLabel, #padNumber, #padName, #padStatus, #warningLabel {{
            background: transparent;
        }}
        #plainLabel {{
            color: {text["primary"]};
        }}
        #plainLabel:disabled {{
            color: {text["secondary"]};
        }}
        #padWidget {{
            border: 1px solid {surface["border_muted"]};
            border-radius: 8px;
            background: {surface["panel"]};
        }}
        #padWidget[editing="true"] {{
            border-color: {surface["accent"]};
        }}
        #padWidget[state="empty"] {{
            background: {surface["panel_empty"]};
            border-color: {surface["border_muted"]};
        }}
        #padWidget[state="ready"] {{
            background: {surface["panel_ready"]};
            border-color: {surface["accent"]};
        }}
        #padWidget[state="missing"] {{
            background: {surface["panel_missing"]};
            border-color: {text["warning"]};
        }}
        #padWidget[pressedActive="true"] {{
            background: {surface["panel_pressed"]};
            border-color: {surface["accent"]};
        }}
        #padWidget[dragActive="true"] {{
            border: 2px solid {surface["drag_hover_border"]};
        }}
        #padNumber {{
            color: {text["secondary"]};
            font-weight: 700;
        }}
        #padName {{
            color: {text["primary"]};
            font-size: 16px;
            font-weight: 700;
        }}
        #padStatus {{
            color: {text["secondary"]};
            font-size: 12px;
        }}
        #padDeleteButton {{
            background: {danger["normal"]};
            border: 1px solid {danger["border"]};
            border-radius: 6px;
            color: {danger["text"]};
            font-size: 12px;
            font-weight: 700;
            padding: 0;
        }}
        #padDeleteButton:hover {{
            background: {danger["hover"]};
        }}
        #padDeleteButton:pressed {{
            background: {danger["pressed"]};
        }}
        #warningLabel {{
            color: {text["warning"]};
        }}
        #waveformWidget {{
            border: 1px solid {surface["border_muted"]};
            border-radius: 6px;
            background: {theme.values["waveform"]["background"]};
        }}
        #waveformWidget[dragActive="true"] {{
            border: 2px solid {surface["drag_hover_border"]};
        }}
        QPushButton {{
            background: {default["normal"]};
            border: 1px solid {default["border"]};
            border-radius: 6px;
            padding: 8px 12px;
            color: {default["text"]};
        }}
        QPushButton:hover {{
            background: {default["hover"]};
        }}
        QPushButton:pressed {{
            background: {default["pressed"]};
        }}
        #killButton {{
            background: {danger["normal"]};
            border-color: {danger["border"]};
            color: {danger["text"]};
            font-weight: 700;
        }}
        #killButton:hover {{
            background: {danger["hover"]};
        }}
        #killButton:pressed {{
            background: {danger["pressed"]};
        }}
        #editPanelButton {{
            background: {edit["normal"]};
            border-color: {edit["border"]};
            color: {edit["text"]};
            font-weight: 700;
        }}
        #editPanelButton:hover {{
            background: {edit["hover"]};
        }}
        #editPanelButton:pressed {{
            background: {edit["pressed"]};
        }}
        #editPanelButton:checked {{
            background: {active["normal"]};
            border-color: {active["border"]};
            color: {active["text"]};
        }}
        #editPanelButton:checked:hover {{
            background: {active["hover"]};
        }}
        #relocateButton {{
            background: {danger["normal"]};
            border-color: {danger["border"]};
            color: {danger["text"]};
            font-weight: 700;
        }}
        #relocateButton:hover {{
            background: {danger["hover"]};
        }}
        #relocateButton:pressed {{
            background: {danger["pressed"]};
        }}
        QComboBox, QLineEdit, QAbstractSpinBox {{
            background: {surface["input"]};
            border: 1px solid {surface["border"]};
            border-radius: 6px;
            padding: 6px 10px;
            color: {text["primary"]};
            selection-background-color: {surface["selection"]};
            selection-color: {text["strong"]};
        }}
        QComboBox {{
            combobox-popup: 0;
            padding-right: 34px;
        }}
        QComboBox:hover {{
            border-color: {surface["accent"]};
        }}
        QComboBox:on {{
            border-color: {surface["accent"]};
            background: {surface["panel_pressed"]};
        }}
        QComboBox::drop-down {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 28px;
            border: none;
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
            background: transparent;
        }}
        QComboBox::down-arrow {{
            image: url({combo_arrow_path});
            width: 12px;
            height: 12px;
            border: none;
            margin-right: 8px;
        }}
        QComboBox QAbstractItemView, QMenu {{
            background: {surface["menu"]};
            color: {text["primary"]};
            border: 1px solid {surface["border"]};
            selection-background-color: {surface["selection"]};
            selection-color: {text["strong"]};
        }}
        QMenu::item {{
            padding: 6px 24px 6px 12px;
        }}
        QMenu::item:selected {{
            background: {surface["selection"]};
            color: {text["strong"]};
        }}
        #pageTabs {{
            background: transparent;
            border: none;
        }}
        #pageTabs::pane {{
            background: transparent;
            border: none;
        }}
        #pageTabs::tab {{
            background: {surface["panel"]};
            border: 1px solid {surface["border"]};
            border-radius: 6px;
            color: {text["primary"]};
            padding: 7px 12px;
            margin-right: 6px;
        }}
        #pageTabs::tab:selected {{
            background: {surface["accent_muted"]};
            border-color: {surface["accent"]};
            color: {text["strong"]};
        }}
        #pageTabs::tab:hover {{
            background: {surface["selection"]};
        }}
        QSlider::groove:horizontal {{
            height: 6px;
            background: {surface["border_muted"]};
            border-radius: 3px;
        }}
        QSlider::groove:horizontal:disabled {{
            background: {surface["panel_empty"]};
        }}
        QSlider::handle:horizontal {{
            width: 10px;
            height: 12px;
            margin: -3px 0;
            border-radius: 4px;
            background: {surface["accent"]};
        }}
        QSlider::handle:horizontal:hover {{
            background: {active["hover"]};
        }}
        QSlider::handle:horizontal:disabled {{
            background: {surface["border"]};
        }}
        QScrollBar:vertical, QScrollBar:horizontal {{
            background: {surface["window"]};
            border: none;
        }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
            background: {surface["border"]};
            border-radius: 4px;
        }}
    """


def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
