from __future__ import annotations

import os
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pygame
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .audio_engine import SYSTEM_DEFAULT_DEVICE, AudioEngine
from .audio_processing import AudioProcessingError, AudioProcessor
from .dialogs import PadSettingsDialog
from .models import PadConfig, PageConfig, is_supported_audio_file
from .resources import app_root, resource_path
from .store import PADS_PER_PAGE, ProjectStore
from .theme import apply_theme, load_theme
from .widgets import PAD_COPY_MIME_TYPE, PAD_MIME_TYPE, PadWidget


_STARTUP_PROFILE_ENABLED = os.environ.get("SOUNDPAD_STARTUP_PROFILE") == "1"
_STARTUP_PROFILE_START = time.perf_counter()


def _startup_profile_path() -> Path:
    return Path.cwd() / "cache" / "startup-profile.log"


def _write_startup_profile(label: str, elapsed: float | None = None) -> None:
    if not _STARTUP_PROFILE_ENABLED:
        return
    path = _startup_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    total = time.perf_counter() - _STARTUP_PROFILE_START
    suffix = f" elapsed={elapsed:.4f}s" if elapsed is not None else ""
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{total:.4f}s {label}{suffix}\n")


@contextmanager
def _profile_step(label: str) -> Iterator[None]:
    start = time.perf_counter()
    _write_startup_profile(f"{label}: start")
    try:
        yield
    finally:
        _write_startup_profile(f"{label}: end", time.perf_counter() - start)


def plain_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("plainLabel")
    return label


class PageTabBar(QTabBar):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.page_count = 0
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasFormat(PAD_MIME_TYPE) or event.mimeData().hasFormat(PAD_COPY_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if not event.mimeData().hasFormat(PAD_MIME_TYPE) and not event.mimeData().hasFormat(PAD_COPY_MIME_TYPE):
            super().dragMoveEvent(event)
            return

        index = self.tabAt(event.position().toPoint())
        if 0 <= index < self.page_count and index != self.currentIndex():
            self.setCurrentIndex(index)
        event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self, project_root: Path) -> None:
        with _profile_step("MainWindow.super"):
            super().__init__()
        self.setWindowIcon(_app_icon())
        self.setWindowTitle(f"SoundPad v{__version__}")
        self.resize(900, 650)
        self.setMinimumSize(720, 520)

        with _profile_step("ProjectStore"):
            self.store = ProjectStore(project_root)
        with _profile_step("AudioProcessor"):
            self.audio_processor = AudioProcessor()
        with _profile_step("load_project"):
            self.pages, self.settings = self.store.load_project()
        with _profile_step("AudioEngine"):
            try:
                self.audio_engine = AudioEngine(self.settings.output_device_name)
            except Exception:
                self.settings.output_device_name = SYSTEM_DEFAULT_DEVICE
                self.audio_engine = AudioEngine()
        self.pad_widgets: dict[int, PadWidget] = {}
        self._active_pad_channels: dict[int, pygame.mixer.Channel | None] = {}
        self.current_page_index = 0
        self.edit_panel_enabled = False
        self._tabs_updating = False

        with _profile_step("build_static_ui"):
            central = QWidget()
            central.setObjectName("centralPanel")
            main_layout = QVBoxLayout(central)
            main_layout.setContentsMargins(18, 18, 18, 18)
            main_layout.setSpacing(14)

            toolbar = QHBoxLayout()
            toolbar.addWidget(plain_label("Output"))
            self.output_combo = QComboBox()
            self.output_combo.setMinimumWidth(280)
            toolbar.addWidget(self.output_combo)
            toolbar.addStretch(1)
            self.edit_panel_button = QPushButton("Edit Panel")
            self.edit_panel_button.setCheckable(True)
            self.edit_panel_button.setObjectName("editPanelButton")
            self.edit_panel_button.toggled.connect(self._set_edit_panel_enabled)
            toolbar.addWidget(self.edit_panel_button)
            self.kill_button = QPushButton("Kill")
            self.kill_button.setObjectName("killButton")
            self.kill_button.clicked.connect(self.stop_all_playback)
            toolbar.addWidget(self.kill_button)
            main_layout.addLayout(toolbar)

            self.page_tabs = PageTabBar()
            self.page_tabs.setObjectName("pageTabs")
            self.page_tabs.setExpanding(False)
            self.page_tabs.setDrawBase(False)
            self.page_tabs.setUsesScrollButtons(True)
            self.page_tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.page_tabs.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.page_tabs.setAutoFillBackground(False)
            self.page_tabs.currentChanged.connect(self._change_page)
            self.page_tabs.customContextMenuRequested.connect(self._show_page_menu)
            main_layout.addWidget(self.page_tabs)

            self.page_stack = QStackedWidget()
            self.page_stack.setObjectName("pageStack")
            self.page_stack.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.page_stack.setAutoFillBackground(False)
            main_layout.addWidget(self.page_stack, 1)

            self.setCentralWidget(central)
        with _profile_step("load_output_devices"):
            self._load_output_devices()
        with _profile_step("rebuild_page_tabs"):
            self._rebuild_page_tabs()
        with _profile_step("rebuild_page_views"):
            self._rebuild_page_views()
        with _profile_step("refresh_pad_widgets"):
            self.refresh_pad_widgets()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.audio_engine.close()
        super().closeEvent(event)

    def trigger_pad_pressed(self, pad_id: int) -> None:
        pad = self._pad_by_id(pad_id)
        cache_path = self._cache_path(pad)
        if not cache_path.exists():
            return
        if pad.trigger_mode in {"hold", "hold_loop"}:
            self.stop_pad(pad_id)
        loops = -1 if pad.trigger_mode == "hold_loop" else 0
        try:
            channel = self.audio_engine.play(
                cache_path,
                pad.volume,
                loops=loops,
                direction=pad.playback_direction,
            )
            if pad.trigger_mode in {"hold", "hold_loop"}:
                self._active_pad_channels[pad_id] = channel
        except Exception as exc:
            QMessageBox.warning(self, "Playback Failed", str(exc))

    def trigger_pad_released(self, pad_id: int) -> None:
        pad = self._pad_by_id(pad_id)
        if pad.trigger_mode in {"hold", "hold_loop"}:
            self.stop_pad(pad_id)

    def stop_pad(self, pad_id: int) -> None:
        channel = self._active_pad_channels.pop(pad_id, None)
        self.audio_engine.stop_channel(channel)

    def stop_all_playback(self) -> None:
        self.audio_engine.stop_all()
        self._active_pad_channels.clear()

    def open_pad_settings(self, pad_id: int) -> None:
        pad = self._pad_by_id(pad_id)
        previous_cache_path = self._cache_path(pad)
        dialog = PadSettingsDialog(
            config=pad,
            audio_processor=self.audio_processor,
            audio_engine=self.audio_engine,
            cache_path=self._cache_path(pad),
            parent=self,
        )
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self._restore_main_window_interaction()
        if not accepted:
            return

        updated = dialog.result_config()
        if updated.source_path and not updated.cache_path:
            updated.cache_path = self._relative_cache_path(self.store.cache_path_for_pad(updated.pad_id))
        self._replace_pad(updated)
        if updated.is_empty:
            self._delete_cache(previous_cache_path)
        self.stop_pad(updated.pad_id)
        self.audio_engine.reload(self._cache_path(updated))
        self._save_project()
        self.refresh_pad_widgets()
        self._restore_main_window_interaction()

    def _restore_main_window_interaction(self) -> None:
        mouse_grabber = QWidget.mouseGrabber()
        if mouse_grabber is not None:
            mouse_grabber.releaseMouse()
        keyboard_grabber = QWidget.keyboardGrabber()
        if keyboard_grabber is not None:
            keyboard_grabber.releaseKeyboard()
        self.edit_panel_button.setEnabled(True)
        self.kill_button.setEnabled(True)
        self.activateWindow()
        self.raise_()
        QTimer.singleShot(0, self.setFocus)

    def load_audio_into_pad(self, pad_id: int, source_path: Path) -> None:
        if not is_supported_audio_file(source_path):
            QMessageBox.warning(self, "Unsupported Format", "Only WAV and MP3 are supported.")
            return

        try:
            duration = self.audio_processor.duration_ms(source_path)
        except AudioProcessingError as exc:
            QMessageBox.warning(self, "Audio Error", str(exc))
            return

        self.stop_pad(pad_id)
        cache_path = self.store.cache_path_for_pad(pad_id)
        pad = PadConfig(
            pad_id=pad_id,
            source_path=str(source_path.resolve()),
            cache_path=self._relative_cache_path(cache_path),
            start_ms=0,
            end_ms=duration,
            fade_in_ms=0,
            fade_out_ms=0,
            volume=1.0,
            display_name=source_path.name,
            custom_label="",
        )

        try:
            self.audio_processor.export_cache(source_path, cache_path, 0, duration)
        except AudioProcessingError as exc:
            QMessageBox.warning(self, "Cache Export Failed", str(exc))
            return

        self._replace_pad(pad)
        self.audio_engine.reload(cache_path)
        self._save_project()
        self.refresh_pad_widgets()

    def refresh_pad_widgets(self) -> None:
        for page in self.pages:
            for index, pad in enumerate(page.pads):
                widget = self.pad_widgets.get(pad.pad_id)
                if widget is None:
                    continue
                widget.set_display_id(index + 1)
                widget.set_config(pad, self._cache_path(pad).exists())
                widget.set_edit_mode(self.edit_panel_enabled)

    def clear_pad(self, pad_id: int) -> None:
        page_index, pad_index = self._pad_location(pad_id)
        pad = self.pages[page_index].pads[pad_index]
        self.stop_pad(pad_id)
        self._delete_cache(self._cache_path(pad))
        self.audio_engine.reload(self._cache_path(pad))
        self.pages[page_index].pads[pad_index] = PadConfig(pad_id=pad.pad_id)
        self._save_project()
        self._rebuild_page_views()
        self.refresh_pad_widgets()

    def move_pad(self, source_pad_id: int, target_pad_id: int) -> None:
        if source_pad_id == target_pad_id:
            return
        source_page_index, source_index = self._pad_location(source_pad_id)
        target_page_index, target_index = self._pad_location(target_pad_id)

        source_pads = self.pages[source_page_index].pads
        target_pads = self.pages[target_page_index].pads
        source_pads[source_index], target_pads[target_index] = (
            target_pads[target_index],
            source_pads[source_index],
        )

        self._save_project()
        self._rebuild_page_views()
        self.refresh_pad_widgets()

    def copy_pad(self, source_pad_id: int, target_pad_id: int) -> None:
        if source_pad_id == target_pad_id:
            return

        source_pad = self._pad_by_id(source_pad_id)
        target_pad = self._pad_by_id(target_pad_id)
        target_cache_path = self.store.cache_path_for_pad(target_pad_id)
        previous_target_cache_path = self._cache_path(target_pad)
        source_cache_path = self._cache_path(source_pad)
        self.stop_pad(target_pad_id)
        if previous_target_cache_path.resolve() != source_cache_path.resolve():
            self._delete_cache(previous_target_cache_path)

        if source_pad.is_empty:
            copied = PadConfig(pad_id=target_pad_id)
            self._replace_pad(copied)
            self.audio_engine.reload(previous_target_cache_path)
            self.audio_engine.reload(target_cache_path)
            self._save_project()
            self.refresh_pad_widgets()
            return

        copied = PadConfig(
            pad_id=target_pad_id,
            source_path=source_pad.source_path,
            cache_path=self._relative_cache_path(target_cache_path),
            start_ms=source_pad.start_ms,
            end_ms=source_pad.end_ms,
            fade_in_ms=source_pad.fade_in_ms,
            fade_out_ms=source_pad.fade_out_ms,
            volume=source_pad.volume,
            display_name=source_pad.display_name,
            custom_label=source_pad.custom_label,
            trigger_mode=source_pad.trigger_mode,
            playback_direction=source_pad.playback_direction,
        )

        cache_ready = False
        try:
            if source_cache_path.exists() and source_cache_path.is_file():
                target_cache_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_cache_path, target_cache_path)
                cache_ready = True
            elif copied.source_path and Path(copied.source_path).exists():
                self.audio_processor.export_cache(
                    Path(copied.source_path),
                    target_cache_path,
                    copied.start_ms,
                    copied.end_ms,
                    copied.fade_in_ms,
                    copied.fade_out_ms,
                )
                cache_ready = True
        except (OSError, AudioProcessingError) as exc:
            QMessageBox.warning(self, "Pad Copy Cache Failed", str(exc))

        self._replace_pad(copied)
        self.audio_engine.reload(previous_target_cache_path)
        self.audio_engine.reload(target_cache_path)
        self._save_project()
        self.refresh_pad_widgets()
        if not cache_ready:
            self.statusBar().showMessage("Pad copied, but cache is missing.", 4000)

    def _set_edit_panel_enabled(self, enabled: bool) -> None:
        self.edit_panel_enabled = enabled
        self.edit_panel_button.setText("Done" if enabled else "Edit Panel")
        self.refresh_pad_widgets()

    def _change_page(self, page_index: int) -> None:
        if self._tabs_updating or page_index < 0:
            return
        if page_index == len(self.pages):
            self.add_page()
            return
        self.current_page_index = page_index
        self.page_stack.setCurrentIndex(page_index)

    def add_page(self) -> None:
        page_number = len(self.pages) + 1
        self.pages.append(self.store.new_page(self._next_page_id(), f"Page {page_number}", self._next_pad_id()))
        self.current_page_index = len(self.pages) - 1
        self._save_project()
        self._rebuild_page_tabs()
        self._rebuild_page_views()
        self.refresh_pad_widgets()

    def rename_page(self, page_index: int) -> None:
        page = self.pages[page_index]
        name, accepted = QInputDialog.getText(self, "Rename Page", "Page name", text=page.name)
        name = name.strip()
        if not accepted or not name:
            return
        page.name = name
        self._save_project()
        self._rebuild_page_tabs()

    def delete_page(self, page_index: int) -> None:
        page = self.pages[page_index]
        answer = QMessageBox.question(
            self,
            "Delete Page",
            f"Delete {page.name}? This will delete all cache files on this page.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.stop_all_playback()
        for pad in page.pads:
            self._delete_cache(self._cache_path(pad))
            self.audio_engine.reload(self._cache_path(pad))
        del self.pages[page_index]
        if not self.pages:
            self.pages = self.store.default_pages()
        self.current_page_index = min(page_index, len(self.pages) - 1)
        self._save_project()
        self._rebuild_page_tabs()
        self._rebuild_page_views()
        self.refresh_pad_widgets()

    def _show_page_menu(self, position) -> None:
        page_index = self.page_tabs.tabAt(position)
        if page_index < 0 or page_index >= len(self.pages):
            return

        menu = QMenu(self)
        rename_action = menu.addAction("Rename Page")
        delete_action = menu.addAction("Delete Page")
        selected_action = menu.exec(self.page_tabs.mapToGlobal(position))
        if selected_action == rename_action:
            self.rename_page(page_index)
        elif selected_action == delete_action:
            self.delete_page(page_index)

    def _rebuild_page_tabs(self) -> None:
        self._tabs_updating = True
        while self.page_tabs.count():
            self.page_tabs.removeTab(0)
        for page in self.pages:
            self.page_tabs.addTab(page.name)
        self.page_tabs.addTab("+")
        self.page_tabs.page_count = len(self.pages)
        self.page_tabs.setCurrentIndex(self.current_page_index)
        self._tabs_updating = False

    def _rebuild_page_views(self) -> None:
        while self.page_stack.count():
            widget = self.page_stack.widget(0)
            self.page_stack.removeWidget(widget)
            widget.deleteLater()

        self.pad_widgets.clear()
        for page in self.pages:
            grid_holder = QWidget()
            grid_holder.setObjectName("gridPanel")
            grid_holder.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            grid_holder.setAutoFillBackground(False)
            grid = QGridLayout(grid_holder)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(12)

            for local_index, pad in enumerate(page.pads):
                widget = PadWidget(pad.pad_id, display_id=local_index + 1)
                widget.triggerPressed.connect(self.trigger_pad_pressed)
                widget.triggerReleased.connect(self.trigger_pad_released)
                widget.settingsRequested.connect(self.open_pad_settings)
                widget.audioDropped.connect(self.load_audio_into_pad)
                widget.deleteRequested.connect(self.clear_pad)
                widget.padDropped.connect(self.move_pad)
                widget.padCopyDropped.connect(self.copy_pad)
                self.pad_widgets[pad.pad_id] = widget
                row = local_index // 4
                column = local_index % 4
                grid.addWidget(widget, row, column)

            self.page_stack.addWidget(grid_holder)

        self.page_stack.setCurrentIndex(self.current_page_index)

    def _pad_by_id(self, pad_id: int) -> PadConfig:
        page_index, pad_index = self._pad_location(pad_id)
        return self.pages[page_index].pads[pad_index]

    def _replace_pad(self, config: PadConfig) -> None:
        page_index, pad_index = self._pad_location(config.pad_id)
        self.pages[page_index].pads[pad_index] = config

    def _pad_location(self, pad_id: int) -> tuple[int, int]:
        for page_index, page in enumerate(self.pages):
            for pad_index, pad in enumerate(page.pads):
                if pad.pad_id == pad_id:
                    return page_index, pad_index
        raise KeyError(f"Unknown pad_id: {pad_id}")

    def _next_page_id(self) -> int:
        return max((page.page_id for page in self.pages), default=0) + 1

    def _next_pad_id(self) -> int:
        return max((pad.pad_id for page in self.pages for pad in page.pads), default=0) + 1

    def _cache_path(self, pad: PadConfig) -> Path:
        if pad.cache_path:
            cache_path = Path(pad.cache_path)
            if cache_path.is_absolute():
                return cache_path
            return self.store.project_root / cache_path
        return self.store.cache_path_for_pad(pad.pad_id)

    def _relative_cache_path(self, cache_path: Path) -> str:
        try:
            return str(cache_path.relative_to(self.store.project_root))
        except ValueError:
            return str(cache_path)

    def _delete_cache(self, cache_path: Path) -> None:
        try:
            if cache_path.exists() and cache_path.is_file():
                cache_path.unlink()
        except OSError as exc:
            QMessageBox.warning(self, "Cache Delete Failed", str(exc))

    def _save_project(self) -> None:
        self.store.save_project(self.pages, self.settings)

    def _load_output_devices(self) -> None:
        devices = self.audio_engine.list_output_devices()
        selected = self.settings.output_device_name
        if selected and selected not in devices:
            selected = SYSTEM_DEFAULT_DEVICE
            self.settings.output_device_name = selected

        self.output_combo.blockSignals(True)
        self.output_combo.clear()
        self.output_combo.addItem("System Default", SYSTEM_DEFAULT_DEVICE)
        for device in devices:
            self.output_combo.addItem(device, device)

        index = self.output_combo.findData(selected)
        self.output_combo.setCurrentIndex(max(0, index))
        self.output_combo.blockSignals(False)
        self.output_combo.currentIndexChanged.connect(self._change_output_device)

    def _change_output_device(self, _index: int = 0) -> None:
        device_name = self.output_combo.currentData()
        if not isinstance(device_name, str):
            device_name = SYSTEM_DEFAULT_DEVICE
        try:
            self.audio_engine.set_output_device(device_name)
        except Exception as exc:
            QMessageBox.warning(self, "Output Device Error", str(exc))
            self.output_combo.blockSignals(True)
            self.output_combo.setCurrentIndex(0)
            self.output_combo.blockSignals(False)
            device_name = SYSTEM_DEFAULT_DEVICE
            self.audio_engine.set_output_device(device_name)
        self.settings.output_device_name = device_name
        self._save_project()


def run() -> int:
    _write_startup_profile("--- SoundPad startup ---")
    _install_windows_app_id()
    with _profile_step("QApplication"):
        app = QApplication(sys.argv)
    app.setWindowIcon(_app_icon())
    with _profile_step("setStyle"):
        app.setStyle("Fusion")
    with _profile_step("load_theme"):
        theme = load_theme()
    with _profile_step("apply_theme"):
        apply_theme(app, theme)
    with _profile_step("MainWindow"):
        window = MainWindow(_project_root())
    with _profile_step("window.show"):
        window.show()
    _write_startup_profile("event_loop: start")
    return app.exec()


def _project_root() -> Path:
    return app_root()


def _app_icon() -> QIcon:
    if sys.platform == "win32":
        candidates = (
            resource_path("assets", "app-icon.svg"),
            resource_path("assets", "app-icon.ico"),
        )
    elif sys.platform == "darwin":
        candidates = (
            resource_path("assets", "AppIcon.icns"),
            resource_path("assets", "app-icon.svg"),
        )
    else:
        candidates = (resource_path("assets", "app-icon.svg"),)
    for path in candidates:
        if path.exists():
            return QIcon(str(path))
    return QIcon()


def _install_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("KuoCT.SoundPad")
    except Exception:
        return
