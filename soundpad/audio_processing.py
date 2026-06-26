from __future__ import annotations

import os
import shutil
from pathlib import Path

from pydub import AudioSegment


class AudioProcessingError(RuntimeError):
    pass


class AudioProcessor:
    def __init__(self) -> None:
        configure_ffmpeg()
        self._duration_cache: dict[tuple[str, int, int], int] = {}
        self._waveform_cache: dict[tuple[str, int, int, int], tuple[list[float], int]] = {}

    def load_audio(self, source_path: Path) -> AudioSegment:
        try:
            return AudioSegment.from_file(source_path)
        except Exception as exc:  # pydub 會包住 ffmpeg/檔案格式錯誤
            raise AudioProcessingError(_format_read_error(source_path, exc)) from exc

    def duration_ms(self, source_path: Path) -> int:
        signature = self._file_signature(source_path)
        cached = self._duration_cache.get(signature)
        if cached is not None:
            return cached

        duration = len(self.load_audio(source_path))
        self._duration_cache[signature] = duration
        return duration

    def export_cache(
        self,
        source_path: Path,
        cache_path: Path,
        start_ms: int,
        end_ms: int,
        fade_in_ms: int = 0,
        fade_out_ms: int = 0,
    ) -> None:
        clip = self.clip_audio(source_path, start_ms, end_ms, fade_in_ms, fade_out_ms)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            clip.export(cache_path, format="wav")
        except Exception as exc:
            raise AudioProcessingError(f"Cannot export WAV cache: {cache_path}") from exc

    def clip_audio(
        self,
        source_path: Path,
        start_ms: int,
        end_ms: int,
        fade_in_ms: int = 0,
        fade_out_ms: int = 0,
    ) -> AudioSegment:
        duration = self.duration_ms(source_path)
        start = max(0, min(start_ms, duration))
        end = max(start + 1, min(end_ms, duration))
        clip = self._load_audio_range(source_path, start, end)
        fade_in, fade_out = self.clamp_fades(len(clip), fade_in_ms, fade_out_ms)
        if fade_in:
            clip = clip.fade_in(fade_in)
        if fade_out:
            clip = clip.fade_out(fade_out)
        return clip

    def waveform_peaks(self, source_path: Path, points: int = 4000) -> list[float]:
        peaks, _duration = self.waveform_data(source_path, points)
        return peaks

    def waveform_data(self, source_path: Path, points: int = 4000) -> tuple[list[float], int]:
        signature = (*self._file_signature(source_path), points)
        cached = self._waveform_cache.get(signature)
        if cached is not None:
            peaks, duration = cached
            return list(peaks), duration

        audio = self.load_audio(source_path).set_channels(1)
        duration = len(audio)
        samples = audio.get_array_of_samples()
        if not samples:
            self._duration_cache[self._file_signature(source_path)] = duration
            self._waveform_cache[signature] = ([], duration)
            return [], duration

        step = max(1, len(samples) // points)
        max_value = float(1 << (8 * audio.sample_width - 1))
        peaks: list[float] = []
        for index in range(0, len(samples), step):
            chunk_peak = 0
            chunk_end = min(index + step, len(samples))
            for sample_index in range(index, chunk_end):
                value = abs(samples[sample_index])
                if value > chunk_peak:
                    chunk_peak = value
            peaks.append(min(1.0, chunk_peak / max_value))

        file_signature = self._file_signature(source_path)
        self._duration_cache[file_signature] = duration
        self._waveform_cache[signature] = (peaks, duration)
        return list(peaks), duration

    def clamp_fades(
        self,
        clip_duration_ms: int,
        fade_in_ms: int,
        fade_out_ms: int,
    ) -> tuple[int, int]:
        duration = max(0, int(clip_duration_ms))
        fade_in = max(0, min(int(fade_in_ms), duration))
        fade_out = max(0, min(int(fade_out_ms), duration))
        if fade_in + fade_out <= duration:
            return fade_in, fade_out

        if fade_in == 0:
            return 0, duration
        if fade_out == 0:
            return duration, 0

        ratio = duration / (fade_in + fade_out)
        clamped_in = int(fade_in * ratio)
        clamped_out = max(0, duration - clamped_in)
        return clamped_in, clamped_out

    def _load_audio_range(self, source_path: Path, start_ms: int, end_ms: int) -> AudioSegment:
        range_duration_ms = max(1, end_ms - start_ms)
        try:
            return AudioSegment.from_file(
                source_path,
                start_second=start_ms / 1000,
                duration=range_duration_ms / 1000,
            )
        except Exception as exc:  # pydub 會包住 ffmpeg/檔案格式錯誤
            raise AudioProcessingError(_format_read_error(source_path, exc)) from exc

    def _file_signature(self, source_path: Path) -> tuple[str, int, int]:
        try:
            stat = source_path.stat()
        except OSError as exc:
            raise AudioProcessingError(f"Cannot read audio file: {source_path}") from exc
        return str(source_path.resolve()), stat.st_size, stat.st_mtime_ns


def configure_ffmpeg() -> None:
    ffmpeg_path = _find_executable("ffmpeg")
    ffprobe_path = _find_executable("ffprobe")

    paths_to_add = {
        path.parent
        for path in (ffmpeg_path, ffprobe_path)
        if path is not None
    }
    if paths_to_add:
        current_path = os.environ.get("PATH", "")
        existing_paths = current_path.split(os.pathsep) if current_path else []
        missing_paths = [str(path) for path in paths_to_add if str(path) not in existing_paths]
        if missing_paths:
            os.environ["PATH"] = os.pathsep.join([*missing_paths, *existing_paths])

    if ffmpeg_path is not None:
        AudioSegment.converter = str(ffmpeg_path)
        AudioSegment.ffmpeg = str(ffmpeg_path)


def _find_executable(name: str) -> Path | None:
    found = shutil.which(name)
    if found:
        return Path(found)

    if os.name == "nt":
        suffixes = [".exe"]
        common_dirs = [
            Path("C:/ffmpeg/bin"),
            Path("C:/Program Files/ffmpeg/bin"),
            Path("C:/Program Files (x86)/ffmpeg/bin"),
        ]
    else:
        suffixes = [""]
        common_dirs = [
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
            Path("/usr/bin"),
            Path("/bin"),
        ]
    for directory in common_dirs:
        for suffix in suffixes:
            candidate = directory / f"{name}{suffix}"
            if candidate.exists() and candidate.is_file():
                return candidate
    return None


def _format_read_error(source_path: Path, exc: Exception) -> str:
    message = f"Cannot read audio file: {source_path}"
    detail = str(exc).strip()
    if detail:
        message = f"{message}\n\n{detail}"
    if source_path.suffix.lower() == ".mp3" and _find_executable("ffmpeg") is None:
        message = (
            f"{message}\n\n"
            "ffmpeg was not found by SoundPad. If you installed ffmpeg with Homebrew, "
            "make sure it exists at /opt/homebrew/bin/ffmpeg or /usr/local/bin/ffmpeg."
        )
    return message
