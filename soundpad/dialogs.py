from __future__ import annotations

from pathlib import Path

import pygame
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from .audio_engine import AudioEngine
from .audio_processing import AudioProcessingError, AudioProcessor
from .models import PadConfig, db_to_gain, gain_to_db, is_supported_audio_file
from .widgets import WaveformRangeWidget


VOLUME_DB_SCALE = 10
VOLUME_MUTE_SLIDER_VALUE = -601
VOLUME_MIN_DB = -60.0
VOLUME_MAX_DB = 18.0


def plain_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("plainLabel")
    return label


def gain_to_volume_slider_value(gain: float) -> int:
    db_value = gain_to_db(gain)
    if db_value == float("-inf"):
        return VOLUME_MUTE_SLIDER_VALUE
    db_value = max(VOLUME_MIN_DB, min(VOLUME_MAX_DB, db_value))
    return int(round(db_value * VOLUME_DB_SCALE))


def volume_slider_value_to_gain(value: int) -> float:
    if value <= VOLUME_MUTE_SLIDER_VALUE:
        return 0.0
    return db_to_gain(value / VOLUME_DB_SCALE)


def format_gain_db(gain: float) -> str:
    db_value = gain_to_db(gain)
    if db_value == float("-inf"):
        return "-inf dB"
    return f"{db_value:+.1f} dB"


class PadSettingsDialog(QDialog):
    def __init__(
        self,
        config: PadConfig,
        audio_processor: AudioProcessor,
        audio_engine: AudioEngine,
        cache_path: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setWindowTitle(f"Pad {config.pad_id:02d} Settings")
        self.resize(720, 360)
        self.config = PadConfig.from_json(config.to_json(), config.pad_id)
        self.audio_processor = audio_processor
        self.audio_engine = audio_engine
        self.cache_path = cache_path
        self._duration_ms = max(0, self.config.end_ms)
        self._source_available = self.config.has_source
        self._syncing_fade_controls = False
        self._syncing_view_controls = False
        self._loading_audio = False
        self._preview_channel: pygame.mixer.Channel | None = None
        self._preview_start_ms = 0
        self._preview_end_ms = 0
        self._preview_elapsed_ms = 0

        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(30)
        self.preview_timer.timeout.connect(self._tick_preview_playhead)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.name_label = plain_label()
        self.path_input = QLineEdit()
        self.path_input.setReadOnly(True)
        self.path_input.setPlaceholderText("Not set")
        self.warning_label = plain_label()
        self.warning_label.setObjectName("warningLabel")
        self.warning_label.setWordWrap(True)
        self.warning_label.hide()
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("Optional label")
        self.label_input.setText(self.config.custom_label)

        self.waveform = WaveformRangeWidget()
        self.waveform.set_volume_gain(self.config.volume)
        self.waveform.rangeChanged.connect(self._range_changed)
        self.waveform.fadeChanged.connect(self._sync_fade_sliders_from_waveform)
        self.waveform.viewChanged.connect(self._sync_view_sliders_from_waveform)
        self.waveform.scrubPreviewRequested.connect(self._start_scrub_preview)
        self.waveform.scrubPreviewStopped.connect(self._stop_preview)
        self.waveform.audioDropped.connect(self._replace_audio_from_drop)

        self.range_label = plain_label()
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 1000)
        self.zoom_slider.setValue(10)
        self.zoom_slider.valueChanged.connect(self._sync_waveform_from_view_sliders)
        self.zoom_label = plain_label()

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 1000)
        self.position_slider.setValue(0)
        self.position_slider.setEnabled(False)
        self.position_slider.valueChanged.connect(self._sync_waveform_from_view_sliders)
        self.position_label = plain_label()

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(VOLUME_MUTE_SLIDER_VALUE, int(VOLUME_MAX_DB * VOLUME_DB_SCALE))
        self.volume_slider.setValue(gain_to_volume_slider_value(self.config.volume))
        self.volume_label = plain_label()
        self.volume_slider.valueChanged.connect(self._volume_changed)

        self.fade_in_slider = QSlider(Qt.Orientation.Horizontal)
        self.fade_in_slider.setRange(0, 0)
        self.fade_in_slider.setValue(self.config.fade_in_ms)
        self.fade_in_slider.valueChanged.connect(self._sync_waveform_from_fade_sliders)
        self.fade_in_label = plain_label()

        self.fade_out_slider = QSlider(Qt.Orientation.Horizontal)
        self.fade_out_slider.setRange(0, 0)
        self.fade_out_slider.setValue(self.config.fade_out_ms)
        self.fade_out_slider.valueChanged.connect(self._sync_waveform_from_fade_sliders)
        self.fade_out_label = plain_label()

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        path_caption = plain_label("Path")
        path_caption.setMinimumWidth(132)
        path_row.addWidget(path_caption)
        path_row.addWidget(self.path_input, 1)

        label_row = QHBoxLayout()
        label_row.setSpacing(8)
        label_caption = plain_label("Label")
        label_caption.setMinimumWidth(132)
        label_row.addWidget(label_caption)
        label_row.addWidget(self.label_input, 1)

        zoom_row = self._control_row(self.zoom_label, self.zoom_slider)
        position_row = self._control_row(self.position_label, self.position_slider)
        fade_in_row = self._control_row(self.fade_in_label, self.fade_in_slider)
        fade_out_row = self._control_row(self.fade_out_label, self.fade_out_slider)
        gain_row = self._control_row(self.volume_label, self.volume_slider)

        action_buttons = QHBoxLayout()
        action_buttons.setSpacing(8)
        self.preview_button = QPushButton("Play")
        self.load_button = QPushButton("Load Audio")
        self.relocate_button = QPushButton("Relocate File")
        self.relocate_button.setObjectName("relocateButton")
        self.relocate_button.hide()
        self.clear_button = QPushButton("Clear")
        self.save_button = QPushButton("Save")
        self.preview_button.clicked.connect(self._toggle_preview)
        self.load_button.clicked.connect(self._load_audio)
        self.relocate_button.clicked.connect(self._relocate_audio)
        self.clear_button.clicked.connect(self._clear_audio)
        self.save_button.clicked.connect(self._save)
        action_buttons.addWidget(self.preview_button)
        action_buttons.addWidget(self.load_button)
        action_buttons.addWidget(self.relocate_button)
        action_buttons.addWidget(self.clear_button)
        action_buttons.addStretch(1)
        action_buttons.addWidget(self.save_button)

        layout.addWidget(self.name_label)
        layout.addLayout(path_row)
        layout.addWidget(self.warning_label)
        layout.addLayout(label_row)
        layout.addWidget(self.waveform)
        layout.addWidget(self.range_label)
        layout.addLayout(zoom_row)
        layout.addLayout(position_row)
        layout.addLayout(fade_in_row)
        layout.addLayout(fade_out_row)
        layout.addLayout(gain_row)
        layout.addLayout(action_buttons)

        self._load_current_audio()
        self._update_labels()
        self._update_source_state()
        self._update_volume_label()
        self._update_fade_labels()
        self._update_view_labels()

    def result_config(self) -> PadConfig:
        return self.config

    def _control_row(self, label: QLabel, slider: QSlider) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        label.setMinimumWidth(132)
        row.addWidget(label)
        row.addWidget(slider, 1)
        return row

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._stop_preview()
        super().closeEvent(event)

    def _load_current_audio(self) -> None:
        self._loading_audio = True
        source = self.config.source_file
        if source and source.exists():
            self._load_waveform_from_source(source)
            self.waveform.setEnabled(True)
            self._loading_audio = False
            self._update_source_state()
            return

        self._source_available = False
        self.waveform.setEnabled(True)
        if self.cache_path.exists():
            try:
                peaks, duration = self.audio_processor.waveform_data(self.cache_path)
                self._duration_ms = duration
                self.waveform.set_waveform(peaks, duration, 0, duration)
                self._set_fade_slider_limits(duration)
                self._loading_audio = False
                self._update_source_state()
                return
            except AudioProcessingError:
                pass
        self.waveform.set_waveform([], 0, 0, 0)
        self._duration_ms = 0
        self._loading_audio = False
        self._update_source_state()

    def _load_waveform_from_source(self, source: Path) -> None:
        try:
            peaks, duration = self.audio_processor.waveform_data(source)
        except AudioProcessingError as exc:
            self._source_available = False
            QMessageBox.warning(self, "Audio Error", str(exc))
            return

        self._source_available = True
        self._duration_ms = duration
        if self.config.end_ms <= 0 or self.config.end_ms > duration:
            self.config.end_ms = duration
        self.config.start_ms = max(0, min(self.config.start_ms, self.config.end_ms - 1))
        self.waveform.set_waveform(
            peaks,
            duration,
            self.config.start_ms,
            self.config.end_ms,
            self.config.fade_in_ms,
            self.config.fade_out_ms,
        )
        self._set_fade_slider_limits(self.config.end_ms - self.config.start_ms)
        self.fade_in_slider.setValue(self.config.fade_in_ms)
        self.fade_out_slider.setValue(self.config.fade_out_ms)

    def _clear_audio(self) -> None:
        self._stop_preview()
        self.config.source_path = ""
        self.config.cache_path = ""
        self.config.start_ms = 0
        self.config.end_ms = 0
        self.config.fade_in_ms = 0
        self.config.fade_out_ms = 0
        self.config.volume = 1.0
        self.config.display_name = ""
        self.config.custom_label = ""
        self._duration_ms = 0
        self._source_available = False
        self.label_input.clear()
        self.waveform.set_waveform([], 0, 0, 0)
        self.waveform.set_volume_gain(1.0)
        self.volume_slider.setValue(gain_to_volume_slider_value(1.0))
        self.fade_in_slider.setRange(0, 0)
        self.fade_in_slider.setValue(0)
        self.fade_out_slider.setRange(0, 0)
        self.fade_out_slider.setValue(0)
        self.zoom_slider.setValue(10)
        self.position_slider.setValue(0)
        self.position_slider.setEnabled(False)
        self._update_labels()
        self._update_source_state()
        self._update_volume_label()
        self._update_fade_labels()
        self._update_view_labels()

    def _choose_audio_file(self) -> Path | None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Audio",
            "",
            "Audio Files (*.wav *.mp3)",
        )
        if not path:
            return None
        selected = Path(path)
        if not is_supported_audio_file(selected):
            QMessageBox.warning(self, "Unsupported Format", "Only WAV and MP3 are supported.")
            return None
        return selected

    def _relocate_audio(self) -> bool:
        selected = self._choose_audio_file()
        if selected is None:
            return False
        self._set_audio_source(selected, reset_range=False)
        return self._source_available

    def _load_audio(self) -> None:
        selected = self._choose_audio_file()
        if selected is None:
            return
        self._set_audio_source(selected, reset_range=True)

    def _replace_audio_from_drop(self, source_path: Path) -> None:
        if not is_supported_audio_file(source_path):
            QMessageBox.warning(self, "Unsupported Format", "Only WAV and MP3 are supported.")
            return
        self._set_audio_source(source_path, reset_range=True)

    def _set_audio_source(self, selected: Path, reset_range: bool) -> None:
        self._loading_audio = True
        self.config.source_path = str(selected.resolve())
        self.config.display_name = selected.name
        if reset_range:
            self.config.start_ms = 0
            self.config.end_ms = 0
            self.config.fade_in_ms = 0
            self.config.fade_out_ms = 0
            self.config.volume = 1.0
            self.volume_slider.setValue(gain_to_volume_slider_value(1.0))
            self.waveform.set_volume_gain(1.0)
        self._load_waveform_from_source(selected)
        self.waveform.setEnabled(True)
        self._loading_audio = False
        self._update_labels()
        self._update_source_state()
        self._update_volume_label()
        self._update_fade_labels()
        self._update_view_labels()

    def _toggle_preview(self) -> None:
        if self._is_preview_playing():
            self._stop_preview()
            return
        start_ms, end_ms = self.waveform.range_ms()
        self._start_preview(start_ms, end_ms)

    def _start_scrub_preview(self, clicked_ms: int) -> None:
        start_ms, end_ms = self.waveform.range_ms()
        self._start_preview(max(clicked_ms, start_ms), end_ms)

    def _start_preview(self, start_ms: int, end_ms: int) -> None:
        if start_ms >= end_ms:
            return
        self._stop_preview()
        self.config.volume = volume_slider_value_to_gain(self.volume_slider.value())
        source = self.config.source_file
        if source is None or not source.exists():
            if self.cache_path.exists():
                self._preview_channel = self.audio_engine.play(self.cache_path, self.config.volume)
                return
            QMessageBox.information(self, "Cannot Preview", "Load or relocate the source audio first.")
            return

        fade_in_ms, fade_out_ms = self.waveform.fade_ms()
        try:
            preview_clip = self.audio_processor.clip_audio(
                source,
                start_ms,
                end_ms,
                fade_in_ms,
                fade_out_ms,
            )
            self._preview_channel = self.audio_engine.play_segment(preview_clip, self.config.volume)
            self._preview_start_ms = start_ms
            self._preview_end_ms = end_ms
            self._preview_elapsed_ms = 0
            self.waveform.set_playhead_ms(start_ms)
            self.preview_button.setText("Stop")
            self.preview_timer.start()
        except AudioProcessingError as exc:
            QMessageBox.warning(self, "Preview Failed", str(exc))

    def _stop_preview(self) -> None:
        self.preview_timer.stop()
        self.audio_engine.stop_channel(self._preview_channel)
        self._preview_channel = None
        self.waveform.set_playhead_ms(None)
        self.preview_button.setText("Play")

    def _is_preview_playing(self) -> bool:
        return self._preview_channel is not None and self._preview_channel.get_busy()

    def _tick_preview_playhead(self) -> None:
        if not self._is_preview_playing():
            self._stop_preview()
            return
        self._preview_elapsed_ms += self.preview_timer.interval()
        playhead_ms = self._preview_start_ms + self._preview_elapsed_ms
        if playhead_ms >= self._preview_end_ms:
            self._stop_preview()
            return
        self.waveform.set_playhead_ms(playhead_ms)

    def _save(self) -> None:
        self.config.custom_label = self.label_input.text().strip()
        self.config.volume = volume_slider_value_to_gain(self.volume_slider.value())

        source = self.config.source_file
        if source is None or not source.exists():
            self.accept()
            return

        self.config.start_ms, self.config.end_ms = self.waveform.range_ms()
        self.config.fade_in_ms, self.config.fade_out_ms = self.waveform.fade_ms()
        try:
            self.audio_processor.export_cache(
                source,
                self.cache_path,
                self.config.start_ms,
                self.config.end_ms,
                self.config.fade_in_ms,
                self.config.fade_out_ms,
            )
        except AudioProcessingError as exc:
            QMessageBox.warning(self, "Cache Export Failed", str(exc))
            return
        self.accept()

    def _update_labels(self) -> None:
        self.name_label.setText(f"Audio: {self.config.display_name or 'Empty'}")
        path_text = self.config.source_path or ""
        self.path_input.setText(path_text)
        self.path_input.setToolTip(path_text or "Not set")
        self.path_input.setCursorPosition(len(path_text))
        if self._source_has_problem():
            self.warning_label.setText(
                "Source audio is missing or cannot be read. Existing cache can still play.\nRelocate the source to edit or rebuild it."
            )
            self.warning_label.show()
        else:
            self.warning_label.setText("")
            self.warning_label.hide()
        self._update_range_label(*self.waveform.range_ms())

    def _update_source_state(self) -> None:
        source_problem = self._source_has_problem()
        has_audio_identity = bool(self.config.source_path or self.config.display_name or self.cache_path.exists())
        self.load_button.setText("Replace Audio" if has_audio_identity else "Load Audio")
        self.relocate_button.setVisible(source_problem)
        self.waveform.set_read_only(source_problem)
        self.zoom_slider.setEnabled(not source_problem and self._duration_ms > 0)
        self.fade_in_slider.setEnabled(not source_problem and self._duration_ms > 0)
        self.fade_out_slider.setEnabled(not source_problem and self._duration_ms > 0)
        self.volume_slider.setEnabled(not source_problem)
        for label in (
            self.range_label,
            self.zoom_label,
            self.position_label,
            self.fade_in_label,
            self.fade_out_label,
            self.volume_label,
        ):
            label.setEnabled(not source_problem)
        self._update_view_labels()

    def _update_range_label(self, start_ms: int, end_ms: int) -> None:
        self._set_fade_slider_limits(end_ms - start_ms)
        self.range_label.setText(
            f"Range: {start_ms / 1000:.2f}s - {end_ms / 1000:.2f}s"
        )

    def _sync_view_sliders_from_waveform(self, zoom_ratio: float, start_ratio: float) -> None:
        self._syncing_view_controls = True
        self.zoom_slider.setValue(int(round(zoom_ratio * 10)))
        self.position_slider.setValue(int(round(start_ratio * 1000)))
        self.position_slider.setEnabled(zoom_ratio > 1.01)
        self._syncing_view_controls = False
        self._update_view_labels()

    def _sync_waveform_from_view_sliders(self) -> None:
        if self._syncing_view_controls or self._source_has_problem():
            return
        zoom_ratio = self.zoom_slider.value() / 10.0
        start_ratio = self.position_slider.value() / 1000.0
        self._syncing_view_controls = True
        self.waveform.set_zoom_ratio(zoom_ratio)
        self.waveform.set_view_start_ratio(start_ratio)
        self._syncing_view_controls = False
        self._sync_view_sliders_from_waveform(
            self.waveform.zoom_ratio(),
            self.waveform.view_start_ratio(),
        )
        self._update_view_labels()

    def _update_view_labels(self) -> None:
        self.zoom_label.setText(f"Zoom: {self.zoom_slider.value() / 10.0:.1f}x")
        if self._source_has_problem():
            self.position_label.setText("Position: Read only")
            self.position_slider.setEnabled(False)
        elif self.position_slider.isEnabled():
            self.position_label.setText(f"Position: {self.position_slider.value() / 10:.1f}%")
        else:
            self.position_label.setText("Position: Full view")

    def _range_changed(self, start_ms: int, end_ms: int) -> None:
        self._update_range_label(start_ms, end_ms)

    def _volume_changed(self) -> None:
        if self._source_has_problem():
            self._update_volume_label()
            return
        self.waveform.set_volume_gain(volume_slider_value_to_gain(self.volume_slider.value()))
        self._update_volume_label()

    def _update_volume_label(self) -> None:
        gain = volume_slider_value_to_gain(self.volume_slider.value())
        self.volume_label.setText(f"Gain: {format_gain_db(gain)}")

    def _set_fade_slider_limits(self, clip_duration_ms: int) -> None:
        limit = max(0, int(clip_duration_ms))
        self._syncing_fade_controls = True
        self.fade_in_slider.setRange(0, limit)
        self.fade_out_slider.setRange(0, limit)
        self._syncing_fade_controls = False
        self._update_fade_labels()

    def _sync_fade_sliders_from_waveform(self, fade_in_ms: int, fade_out_ms: int) -> None:
        self._syncing_fade_controls = True
        self.fade_in_slider.setValue(fade_in_ms)
        self.fade_out_slider.setValue(fade_out_ms)
        self._syncing_fade_controls = False
        self._update_fade_labels()

    def _sync_waveform_from_fade_sliders(self) -> None:
        if self._syncing_fade_controls or self._source_has_problem():
            return
        self.waveform.set_fades(
            self.fade_in_slider.value(),
            self.fade_out_slider.value(),
        )
        self._update_fade_labels()

    def _update_fade_labels(self) -> None:
        fade_in_ms, fade_out_ms = self.waveform.fade_ms()
        self.fade_in_label.setText(f"Fade In: {fade_in_ms} ms")
        self.fade_out_label.setText(f"Fade Out: {fade_out_ms} ms")

    def _source_has_problem(self) -> bool:
        return bool(self.config.source_path) and not self._source_available
