from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QDrag, QKeyEvent, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QVBoxLayout

from .models import PadConfig, clamp_volume_gain
from .theme import qcolor


PAD_MIME_TYPE = "application/x-soundpad-pad-id"
PAD_COPY_MIME_TYPE = "application/x-soundpad-pad-copy-id"


class PadWidget(QFrame):
    playRequested = Signal(int)
    settingsRequested = Signal(int)
    audioDropped = Signal(int, object)
    deleteRequested = Signal(int)
    padDropped = Signal(int, int)
    padCopyDropped = Signal(int, int)

    def __init__(self, pad_id: int, display_id: int | None = None) -> None:
        super().__init__()
        self.pad_id = pad_id
        self._config = PadConfig(pad_id=pad_id)
        self._edit_mode = False
        self._drag_start_position: QPoint | None = None
        self._drag_button: Qt.MouseButton | None = None
        self._pending_settings_request = False
        self.setAcceptDrops(True)
        self.setMinimumSize(130, 100)
        self.setObjectName("padWidget")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setProperty("pressedActive", "false")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self.number_label = QLabel(f"{display_id or pad_id:02d}")
        self.number_label.setObjectName("padNumber")
        self.name_label = QLabel("Empty")
        self.name_label.setObjectName("padName")
        self.name_label.setWordWrap(True)
        self.status_label = QLabel("")
        self.status_label.setObjectName("padStatus")
        self.delete_button = QPushButton("X", self)
        self.delete_button.setObjectName("padDeleteButton")
        self.delete_button.setFixedSize(28, 22)
        self.delete_button.hide()
        self.delete_button.clicked.connect(lambda: self.deleteRequested.emit(self.pad_id))

        layout.addWidget(self.number_label)
        layout.addStretch(1)
        layout.addWidget(self.name_label)
        layout.addWidget(self.status_label)

    def set_display_id(self, display_id: int) -> None:
        self.number_label.setText(f"{display_id:02d}")

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = enabled
        self.delete_button.setVisible(enabled)
        if enabled:
            self._set_pressed_active(False)
        if enabled:
            self.delete_button.raise_()
        self.setProperty("editing", "true" if enabled else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_config(self, config: PadConfig, cache_exists: bool) -> None:
        self._config = config
        self.pad_id = config.pad_id
        self.name_label.setText(config.custom_label or config.display_name or "Empty")
        if config.is_empty:
            self.status_label.setText("Drop WAV / MP3")
            self.setProperty("state", "empty")
        elif cache_exists:
            self.status_label.setText("Ready")
            self.setProperty("state", "ready")
        else:
            self.status_label.setText("Cache missing")
            self.setProperty("state", "missing")
        self.style().unpolish(self)
        self.style().polish(self)

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def _set_pressed_active(self, active: bool) -> None:
        self.setProperty("pressedActive", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        self.delete_button.move(self.width() - self.delete_button.width() - 8, 8)
        self.delete_button.raise_()
        super().resizeEvent(event)

    def _has_pad_drag(self, event) -> bool:
        mime_data = event.mimeData()
        return mime_data.hasFormat(PAD_MIME_TYPE) or mime_data.hasFormat(PAD_COPY_MIME_TYPE)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if self._edit_mode and self._has_pad_drag(event):
            self._set_drag_active(True)
            event.acceptProposedAction()
            return
        if event.mimeData().hasUrls():
            self._set_drag_active(True)
            event.acceptProposedAction()
            return
        self._set_drag_active(False)
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._edit_mode and self._has_pad_drag(event):
            self._set_drag_active(True)
            event.acceptProposedAction()
            return
        if event.mimeData().hasUrls():
            self._set_drag_active(True)
            event.acceptProposedAction()
            return
        self._set_drag_active(False)
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        self._set_drag_active(False)
        if self._edit_mode and event.mimeData().hasFormat(PAD_COPY_MIME_TYPE):
            raw_pad_id = bytes(event.mimeData().data(PAD_COPY_MIME_TYPE)).decode("utf-8")
            self.padCopyDropped.emit(int(raw_pad_id), self.pad_id)
            event.acceptProposedAction()
            return

        if self._edit_mode and event.mimeData().hasFormat(PAD_MIME_TYPE):
            raw_pad_id = bytes(event.mimeData().data(PAD_MIME_TYPE)).decode("utf-8")
            self.padDropped.emit(int(raw_pad_id), self.pad_id)
            event.acceptProposedAction()
            return

        urls = event.mimeData().urls()
        if not urls:
            return
        local_path = urls[0].toLocalFile()
        if local_path:
            self.audioDropped.emit(self.pad_id, Path(local_path))
            event.acceptProposedAction()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._edit_mode:
            if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
                self._set_pressed_active(False)
                self._drag_start_position = event.position().toPoint()
                self._drag_button = event.button()
                event.accept()
                return
            super().mousePressEvent(event)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            self._set_pressed_active(True)
            self.playRequested.emit(self.pad_id)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._pending_settings_request = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._edit_mode or self._drag_start_position is None or self._drag_button is None:
            super().mouseMoveEvent(event)
            return
        if not event.buttons() & self._drag_button:
            return
        distance = (event.position().toPoint() - self._drag_start_position).manhattanLength()
        if distance < QApplication.startDragDistance():
            return

        mime_data = QMimeData()
        if self._drag_button == Qt.MouseButton.RightButton:
            mime_type = PAD_COPY_MIME_TYPE
            action = Qt.DropAction.CopyAction
        else:
            mime_type = PAD_MIME_TYPE
            action = Qt.DropAction.MoveAction
        mime_data.setData(mime_type, QByteArray(str(self.pad_id).encode("utf-8")))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.setPixmap(self.grab())
        drag.setHotSpot(event.position().toPoint())
        drag.exec(action)
        self._drag_start_position = None
        self._drag_button = None

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start_position = None
        self._drag_button = None
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_pressed_active(False)
        if event.button() == Qt.MouseButton.RightButton:
            should_open_settings = self._pending_settings_request and not self._edit_mode
            self._pending_settings_request = False
            event.accept()
            if should_open_settings:
                QTimer.singleShot(0, lambda pad_id=self.pad_id: self.settingsRequested.emit(pad_id))
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._set_pressed_active(False)
        if not self._edit_mode:
            self._pending_settings_request = False
        super().leaveEvent(event)


class WaveformRangeWidget(QFrame):
    rangeChanged = Signal(int, int)
    fadeChanged = Signal(int, int)
    viewChanged = Signal(float, float)
    scrubPreviewRequested = Signal(int)
    scrubPreviewStopped = Signal()
    audioDropped = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._peaks: list[float] = []
        self._duration_ms = 0
        self._start_ms = 0
        self._end_ms = 0
        self._view_start_ms = 0
        self._view_end_ms = 0
        self._requested_zoom_ratio = 1.0
        self._playhead_ms: int | None = None
        self._fade_in_ms = 0
        self._fade_out_ms = 0
        self._dragging: str | None = None
        self._last_pan_x: float | None = None
        self._range_drag_anchor_ms: int | None = None
        self._space_pressed = False
        self._fade_knob_radius = 8.0
        self._volume_gain = 1.0
        self._read_only = False
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)
        self.setMinimumHeight(150)
        self.setMouseTracking(True)
        self.setObjectName("waveformWidget")

    def set_waveform(
        self,
        peaks: list[float],
        duration_ms: int,
        start_ms: int,
        end_ms: int,
        fade_in_ms: int = 0,
        fade_out_ms: int = 0,
    ) -> None:
        self._peaks = peaks
        self._duration_ms = max(0, duration_ms)
        self._start_ms = max(0, min(start_ms, self._duration_ms))
        self._end_ms = max(self._start_ms, min(end_ms, self._duration_ms))
        self._view_start_ms = 0
        self._view_end_ms = self._duration_ms
        self._requested_zoom_ratio = 1.0
        self.set_fades(fade_in_ms, fade_out_ms, emit=False, update=False)
        self.viewChanged.emit(self.zoom_ratio(), self.view_start_ratio())
        self.update()

    def set_volume_gain(self, gain: float) -> None:
        self._volume_gain = clamp_volume_gain(gain)
        self.update()

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = read_only
        if read_only:
            self._clear_interaction_state()
            self.scrubPreviewStopped.emit()

    def range_ms(self) -> tuple[int, int]:
        return self._start_ms, self._end_ms

    def fade_ms(self) -> tuple[int, int]:
        return self._fade_in_ms, self._fade_out_ms

    def zoom_ratio(self) -> float:
        return self._requested_zoom_ratio

    def view_start_ratio(self) -> float:
        if self._duration_ms <= 0 or not self._is_zoomed():
            return 0.0
        max_start = self._duration_ms - self._visible_duration_ms()
        if max_start <= 0:
            return 0.0
        return max(0.0, min(1.0, self._view_start_ms / max_start))

    def set_zoom_ratio(self, ratio: float) -> None:
        if self._duration_ms <= 0:
            return
        old_start_ratio = self.view_start_ratio()
        zoom = max(1.0, min(100.0, ratio))
        self._requested_zoom_ratio = zoom
        min_duration = 1
        visible_duration = int(max(min_duration, self._duration_ms / zoom))
        visible_duration = min(self._duration_ms, visible_duration)
        max_start = max(0, self._duration_ms - visible_duration)
        new_start = int(max_start * old_start_ratio)
        self._set_view(new_start, new_start + visible_duration)
        self.update()

    def set_view_start_ratio(self, ratio: float) -> None:
        if self._duration_ms <= 0:
            return
        visible_duration = self._visible_duration_ms()
        max_start = max(0, self._duration_ms - visible_duration)
        new_start = int(max_start * max(0.0, min(1.0, ratio)))
        self._set_view(new_start, new_start + visible_duration)
        self.update()

    def set_playhead_ms(self, playhead_ms: int | None) -> None:
        if playhead_ms is None:
            self._playhead_ms = None
        else:
            self._playhead_ms = max(0, min(playhead_ms, self._duration_ms))
        self.update()

    def set_fades(
        self,
        fade_in_ms: int,
        fade_out_ms: int,
        emit: bool = True,
        update: bool = True,
    ) -> None:
        clip_duration = max(0, self._end_ms - self._start_ms)
        fade_in = max(0, min(fade_in_ms, clip_duration))
        fade_out = max(0, min(fade_out_ms, clip_duration))
        if fade_in + fade_out > clip_duration and clip_duration > 0:
            if fade_in >= fade_out:
                fade_in = clip_duration - fade_out
            else:
                fade_out = clip_duration - fade_in
        self._fade_in_ms = max(0, fade_in)
        self._fade_out_ms = max(0, fade_out)
        if emit:
            self.fadeChanged.emit(self._fade_in_ms, self._fade_out_ms)
        if update:
            self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.contentsRect().adjusted(10, 10, -10, -10)
        painter.fillRect(rect, qcolor("waveform", "background"))

        if not self._peaks or self._duration_ms <= 0:
            painter.setPen(qcolor("waveform", "empty_text"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No waveform")
            return

        center_y = rect.center().y()
        waveform_half_height = rect.height() * 0.45
        wave_pen = QPen(qcolor("waveform", "wave"), 1.4)
        painter.setPen(wave_pen)
        painter.setClipRect(rect)
        for x, peak in self._visible_waveform_points(rect):
            half_height = peak * self._volume_gain * waveform_half_height
            painter.drawLine(QPointF(x, center_y - half_height), QPointF(x, center_y + half_height))

        start_x = self._ms_to_x(self._start_ms, rect)
        end_x = self._ms_to_x(self._end_ms, rect)
        selected = QRectF(start_x, rect.top(), max(1.0, end_x - start_x), rect.height())
        painter.fillRect(selected, qcolor("waveform", "selection", "selection_alpha"))

        fade_in_x = self._ms_to_x(self._start_ms + self._fade_in_ms, rect)
        fade_out_x = self._ms_to_x(self._end_ms - self._fade_out_ms, rect)
        painter.fillRect(
            QRectF(start_x, rect.top(), max(0.0, fade_in_x - start_x), rect.height()),
            qcolor("waveform", "fade_region", "fade_region_alpha"),
        )
        painter.fillRect(
            QRectF(fade_out_x, rect.top(), max(0.0, end_x - fade_out_x), rect.height()),
            qcolor("waveform", "fade_region", "fade_region_alpha"),
        )
        fade_slope_pen = QPen(qcolor("waveform", "fade_slope"), 1.6)
        painter.setPen(fade_slope_pen)
        if fade_in_x > start_x:
            painter.drawLine(
                QPointF(start_x, rect.bottom()),
                QPointF(fade_in_x, rect.top()),
            )
        if end_x > fade_out_x:
            painter.drawLine(
                QPointF(fade_out_x, rect.top()),
                QPointF(end_x, rect.bottom()),
            )

        minus_six_db_ratio = math.pow(10.0, -6.0 / 20.0)
        upper_db_y = center_y - minus_six_db_ratio * waveform_half_height
        lower_db_y = center_y + minus_six_db_ratio * waveform_half_height
        db_pen = QPen(qcolor("waveform", "db_line", "db_line_alpha"), 1.0, Qt.PenStyle.DashLine)
        painter.setPen(db_pen)
        painter.drawLine(QPointF(rect.left(), upper_db_y), QPointF(rect.right(), upper_db_y))
        painter.drawLine(QPointF(rect.left(), lower_db_y), QPointF(rect.right(), lower_db_y))

        original_font = painter.font()
        label_font = painter.font()
        point_size = label_font.pointSizeF()
        if point_size <= 0:
            point_size = 9.0
        label_font.setPointSizeF(max(7.0, point_size - 2.0))
        painter.setFont(label_font)
        painter.setPen(qcolor("waveform", "db_label"))
        label_height = painter.fontMetrics().height()
        painter.drawText(
            QRectF(rect.left() + 6, rect.top() + 2, 90, label_height + 2),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "0 dBFS",
        )
        painter.drawText(
            QRectF(rect.left() + 6, upper_db_y + 2, 90, label_height + 2),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "-6 dBFS",
        )
        painter.setFont(original_font)

        handle_pen = QPen(qcolor("waveform", "handle"), 3)
        painter.setPen(handle_pen)
        painter.drawLine(QPointF(start_x, rect.top()), QPointF(start_x, rect.bottom()))
        painter.drawLine(QPointF(end_x, rect.top()), QPointF(end_x, rect.bottom()))

        fade_pen = QPen(qcolor("waveform", "fade_handle"), 2)
        painter.setPen(fade_pen)
        painter.drawLine(QPointF(fade_in_x, rect.top()), QPointF(fade_in_x, rect.bottom()))
        painter.drawLine(QPointF(fade_out_x, rect.top()), QPointF(fade_out_x, rect.bottom()))

        fade_in_knob = self._fade_knob_center(fade_in_x, rect)
        fade_out_knob = self._fade_knob_center(fade_out_x, rect)
        painter.setBrush(qcolor("waveform", "fade_handle"))
        painter.setPen(QPen(qcolor("waveform", "knob_border"), 2))
        painter.drawEllipse(fade_in_knob, self._fade_knob_radius, self._fade_knob_radius)
        painter.drawEllipse(fade_out_knob, self._fade_knob_radius, self._fade_knob_radius)
        painter.setClipping(False)

        if self._is_zoomed():
            painter.setPen(qcolor("waveform", "zoom_text"))
            painter.drawText(
                rect.adjusted(6, 4, -6, -4),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                f"{self._view_start_ms / 1000:.2f}s - {self._view_end_ms / 1000:.2f}s",
            )

        if self._playhead_ms is not None and self._view_start_ms <= self._playhead_ms <= self._view_end_ms:
            playhead_x = self._ms_to_x(self._playhead_ms, rect)
            painter.setPen(QPen(qcolor("waveform", "playhead"), 2.2))
            painter.drawLine(QPointF(playhead_x, rect.top()), QPointF(playhead_x, rect.bottom()))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if self._read_only:
            event.ignore()
            return
        if self._duration_ms <= 0 or not self.isEnabled():
            self._clear_interaction_state()
            return
        rect = self.contentsRect().adjusted(10, 10, -10, -10)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._dragging = "pan"
            self._last_pan_x = event.position().x()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.scrubPreviewRequested.emit(self._x_to_ms(event.position().x(), rect))
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        start_x = self._ms_to_x(self._start_ms, rect)
        end_x = self._ms_to_x(self._end_ms, rect)
        fade_in_x = self._ms_to_x(self._start_ms + self._fade_in_ms, rect)
        fade_out_x = self._ms_to_x(self._end_ms - self._fade_out_ms, rect)
        x = event.position().x()
        position = event.position()
        if self._is_near_fade_knob(position, fade_in_x, rect):
            self._dragging = "fade_in"
            self._move_handle(x, rect)
            event.accept()
            return
        if self._is_near_fade_knob(position, fade_out_x, rect):
            self._dragging = "fade_out"
            self._move_handle(x, rect)
            event.accept()
            return

        if self._space_pressed:
            self._dragging = "pan"
            self._last_pan_x = x
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._dragging = "range"
            self._range_drag_anchor_ms = self._x_to_ms(x, rect)
            self._set_range_from_points(self._range_drag_anchor_ms, self._range_drag_anchor_ms)
        else:
            self._dragging = "start" if abs(x - start_x) <= abs(x - end_x) else "end"
        self._move_handle(x, rect)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._read_only or not self.isEnabled():
            self._clear_interaction_state()
            event.ignore()
            return
        if self._dragging is None:
            return
        rect = self.contentsRect().adjusted(10, 10, -10, -10)
        if self._dragging == "pan":
            self._pan_view_by_pixels(event.position().x(), rect)
            event.accept()
            return
        if self._dragging == "range":
            if self._range_drag_anchor_ms is not None:
                self._set_range_from_points(
                    self._range_drag_anchor_ms,
                    self._x_to_ms(event.position().x(), rect),
                )
            event.accept()
            return
        self._move_handle(event.position().x(), rect)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._read_only:
            self._clear_interaction_state()
            event.ignore()
            return
        if event.button() == Qt.MouseButton.MiddleButton and self._dragging == "pan":
            self._clear_interaction_state()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.scrubPreviewStopped.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging == "range" and self._range_drag_anchor_ms is not None:
                rect = self.contentsRect().adjusted(10, 10, -10, -10)
                self._set_range_from_points(
                    self._range_drag_anchor_ms,
                    self._x_to_ms(event.position().x(), rect),
                )
            self._clear_interaction_state()
            event.accept()
            return
        self._clear_interaction_state()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().enterEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._read_only:
            event.ignore()
            return
        if self._duration_ms <= 0:
            event.ignore()
            return

        rect = self.contentsRect().adjusted(10, 10, -10, -10)
        position = event.position()
        if not rect.contains(int(position.x()), int(position.y())):
            event.ignore()
            return

        pixel_horizontal_delta = event.pixelDelta().x()
        if pixel_horizontal_delta != 0:
            self._pan_view_by_pixel_delta(pixel_horizontal_delta, rect)
            event.accept()
            self.update()
            return

        angle_horizontal_delta = event.angleDelta().x()
        if angle_horizontal_delta != 0:
            self._pan_view_by_wheel(angle_horizontal_delta)
            event.accept()
            self.update()
            return

        vertical_delta = event.angleDelta().y()
        if vertical_delta == 0:
            vertical_delta = event.pixelDelta().y()
        if vertical_delta == 0:
            event.ignore()
            return

        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._pan_view(-vertical_delta)
        else:
            self._zoom_view(vertical_delta, event.position().x(), rect)
        event.accept()
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = True
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = False
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:  # type: ignore[override]
        self._space_pressed = False
        self._clear_interaction_state()
        super().focusOutEvent(event)

    def _clear_interaction_state(self) -> None:
        self._dragging = None
        self._last_pan_x = None
        self._range_drag_anchor_ms = None

    def _set_range_from_points(self, first_ms: int, second_ms: int) -> None:
        start_ms = max(0, min(first_ms, second_ms, self._duration_ms))
        end_ms = max(0, min(max(first_ms, second_ms), self._duration_ms))
        if start_ms == end_ms:
            if end_ms < self._duration_ms:
                end_ms += 1
            else:
                start_ms = max(0, end_ms - 1)
        self._start_ms = start_ms
        self._end_ms = end_ms
        self.set_fades(self._fade_in_ms, self._fade_out_ms, update=False)
        self.rangeChanged.emit(self._start_ms, self._end_ms)
        self.update()

    def _move_handle(self, x: float, rect: QRectF) -> None:
        ms = self._x_to_ms(x, rect)
        if self._dragging == "start":
            self._start_ms = max(0, min(ms, self._end_ms - 1))
            self.set_fades(self._fade_in_ms, self._fade_out_ms, update=False)
        elif self._dragging == "end":
            self._end_ms = min(self._duration_ms, max(ms, self._start_ms + 1))
            self.set_fades(self._fade_in_ms, self._fade_out_ms, update=False)
        elif self._dragging == "fade_in":
            self.set_fades(max(0, ms - self._start_ms), self._fade_out_ms, update=False)
        elif self._dragging == "fade_out":
            self.set_fades(self._fade_in_ms, max(0, self._end_ms - ms), update=False)
        if self._dragging in {"start", "end"}:
            self.rangeChanged.emit(self._start_ms, self._end_ms)
        self.update()

    def _ms_to_x(self, ms: int, rect: QRectF) -> float:
        visible_duration = self._visible_duration_ms()
        if visible_duration <= 0:
            return rect.left()
        return rect.left() + ((ms - self._view_start_ms) / visible_duration) * rect.width()

    def _x_to_ms(self, x: float, rect: QRectF) -> int:
        visible_duration = self._visible_duration_ms()
        if rect.width() <= 0 or visible_duration <= 0:
            return 0
        ratio = max(0.0, min(1.0, (x - rect.left()) / rect.width()))
        return int(self._view_start_ms + ratio * visible_duration)

    def _peak_index_to_ms(self, index: int) -> int:
        if len(self._peaks) <= 1 or self._duration_ms <= 0:
            return 0
        return int(index / (len(self._peaks) - 1) * self._duration_ms)

    def _visible_peak_indexes(self) -> tuple[int, int]:
        if not self._peaks or self._duration_ms <= 0:
            return 0, -1
        if len(self._peaks) == 1:
            return 0, 0

        scale = (len(self._peaks) - 1) / self._duration_ms
        first = max(0, int(self._view_start_ms * scale) - 1)
        last = min(len(self._peaks) - 1, int(self._view_end_ms * scale) + 1)
        return first, last

    def _visible_waveform_points(self, rect: QRectF) -> list[tuple[float, float]]:
        first_peak, last_peak = self._visible_peak_indexes()
        if last_peak < first_peak:
            return []

        visible_count = last_peak - first_peak + 1
        pixel_columns = max(1, int(rect.width()))
        if visible_count <= pixel_columns:
            return [
                (self._ms_to_x(self._peak_index_to_ms(index), rect), self._peaks[index])
                for index in range(first_peak, last_peak + 1)
            ]

        column_peaks = [0.0] * pixel_columns
        visible_duration = self._visible_duration_ms()
        for index in range(first_peak, last_peak + 1):
            peak_ms = self._peak_index_to_ms(index)
            ratio = (peak_ms - self._view_start_ms) / visible_duration
            column = int(max(0.0, min(1.0, ratio)) * (pixel_columns - 1))
            if self._peaks[index] > column_peaks[column]:
                column_peaks[column] = self._peaks[index]

        if pixel_columns == 1:
            return [(rect.left(), column_peaks[0])]
        return [
            (rect.left() + (column / (pixel_columns - 1)) * rect.width(), peak)
            for column, peak in enumerate(column_peaks)
        ]

    def _visible_duration_ms(self) -> int:
        return max(1, self._view_end_ms - self._view_start_ms)

    def _is_zoomed(self) -> bool:
        return self._duration_ms > 0 and self._visible_duration_ms() < self._duration_ms

    def _zoom_view(self, wheel_delta: int, anchor_x: float, rect: QRectF) -> None:
        anchor_ms = self._x_to_ms(anchor_x, rect)
        ratio = max(0.0, min(1.0, (anchor_x - rect.left()) / max(1.0, rect.width())))
        zoom_factor = 1.25 if wheel_delta > 0 else 0.8
        new_zoom = max(1.0, min(100.0, self._requested_zoom_ratio * zoom_factor))
        self._requested_zoom_ratio = new_zoom
        new_duration = int(max(1, min(self._duration_ms, self._duration_ms / new_zoom)))
        new_start = int(anchor_ms - new_duration * ratio)
        self._set_view(new_start, new_start + new_duration)

    def _pan_view(self, wheel_delta: int) -> None:
        shift = int(self._visible_duration_ms() * 0.15)
        if wheel_delta < 0:
            shift = -shift
        self._set_view(self._view_start_ms + shift, self._view_end_ms + shift)

    def _pan_view_by_wheel(self, wheel_delta: int) -> None:
        shift = int(self._visible_duration_ms() * 0.15)
        if wheel_delta > 0:
            shift = -shift
        self._set_view(self._view_start_ms + shift, self._view_end_ms + shift)

    def _pan_view_by_pixel_delta(self, wheel_delta: int, rect: QRectF) -> None:
        if rect.width() <= 0:
            return
        shift = int(-(wheel_delta / rect.width()) * self._visible_duration_ms())
        if shift == 0:
            shift = -1 if wheel_delta > 0 else 1
        self._set_view(self._view_start_ms + shift, self._view_end_ms + shift)

    def _pan_view_by_pixels(self, current_x: float, rect: QRectF) -> None:
        if self._last_pan_x is None or rect.width() <= 0:
            self._last_pan_x = current_x
            return
        delta_x = current_x - self._last_pan_x
        self._last_pan_x = current_x
        delta_ms = int(-(delta_x / rect.width()) * self._visible_duration_ms())
        self._set_view(self._view_start_ms + delta_ms, self._view_end_ms + delta_ms)
        self.update()

    def _set_view(self, start_ms: int, end_ms: int) -> None:
        duration = max(0, self._duration_ms)
        visible = max(1, end_ms - start_ms)
        if visible >= duration:
            self._view_start_ms = 0
            self._view_end_ms = duration
            self.viewChanged.emit(self.zoom_ratio(), self.view_start_ratio())
            return
        start = max(0, min(start_ms, duration - visible))
        self._view_start_ms = start
        self._view_end_ms = start + visible
        self.viewChanged.emit(self.zoom_ratio(), self.view_start_ratio())

    def _fade_knob_center(self, x: float, rect: QRectF) -> QPointF:
        return QPointF(x, rect.top() + self._fade_knob_radius + 3)

    def _is_near_fade_knob(self, position: QPointF, x: float, rect: QRectF) -> bool:
        center = self._fade_knob_center(x, rect)
        dx = position.x() - center.x()
        dy = position.y() - center.y()
        hit_radius = self._fade_knob_radius + 4
        return dx * dx + dy * dy <= hit_radius * hit_radius

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            self._set_drag_active(True)
            event.acceptProposedAction()
            return
        self._set_drag_active(False)
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            self._set_drag_active(True)
            event.acceptProposedAction()
            return
        self._set_drag_active(False)
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        self._set_drag_active(False)
        urls = event.mimeData().urls()
        if not urls:
            return
        local_path = urls[0].toLocalFile()
        if local_path:
            self.audioDropped.emit(Path(local_path))
            event.acceptProposedAction()

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)
