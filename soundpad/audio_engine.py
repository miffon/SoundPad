from __future__ import annotations

from pathlib import Path

import pygame
import pygame._sdl2.audio as sdl_audio
from pydub import AudioSegment

from .models import PlaybackDirection, clamp_volume_gain, gain_to_db, normalize_playback_direction


SYSTEM_DEFAULT_DEVICE = ""


class AudioEngine:
    def __init__(self, output_device_name: str = SYSTEM_DEFAULT_DEVICE) -> None:
        self.output_device_name = output_device_name
        self._sounds: dict[tuple[Path, float, PlaybackDirection], pygame.mixer.Sound] = {}
        self._init_mixer(output_device_name)

    def _init_mixer(self, output_device_name: str) -> None:
        # 較小 buffer 可降低 pad 觸發延遲。
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
        pygame.mixer.init(devicename=output_device_name or None)
        pygame.mixer.set_num_channels(32)
        self.output_device_name = output_device_name

    def play(
        self,
        cache_path: Path,
        volume: float,
        loops: int = 0,
        direction: PlaybackDirection = "forward",
    ) -> pygame.mixer.Channel | None:
        cache_path = cache_path.resolve()
        if not cache_path.exists():
            raise FileNotFoundError(cache_path)
        gain = clamp_volume_gain(volume)
        if gain <= 0.0:
            return None

        direction = normalize_playback_direction(direction)
        sound_key = (cache_path, round(gain, 4) if gain > 1.0 else 1.0, direction)
        sound = self._sounds.get(sound_key)
        if sound is None:
            sound = self._load_sound(cache_path, gain, direction)
            self._sounds[sound_key] = sound

        sound.set_volume(min(1.0, gain))
        return sound.play(loops=loops)

    def play_segment(
        self,
        audio: AudioSegment,
        volume: float,
        loops: int = 0,
        direction: PlaybackDirection = "forward",
    ) -> pygame.mixer.Channel | None:
        gain = clamp_volume_gain(volume)
        if gain <= 0.0:
            return None

        direction = normalize_playback_direction(direction)
        audio = self._apply_direction(audio, direction)
        sound = self._sound_from_segment(audio, gain)
        sound.set_volume(min(1.0, gain))
        return sound.play(loops=loops)

    def list_output_devices(self) -> list[str]:
        try:
            if not pygame.mixer.get_init():
                self._init_mixer(self.output_device_name)
            return list(sdl_audio.get_audio_device_names(False))
        except Exception:
            return []

    def set_output_device(self, output_device_name: str) -> None:
        if output_device_name == self.output_device_name and pygame.mixer.get_init():
            return
        pygame.mixer.quit()
        self._sounds.clear()
        self._init_mixer(output_device_name)

    def reload(self, cache_path: Path) -> None:
        resolved = cache_path.resolve()
        for key in list(self._sounds):
            if key[0] == resolved:
                self._sounds.pop(key, None)

    def stop_channel(self, channel: pygame.mixer.Channel | None) -> None:
        if channel is not None:
            channel.stop()

    def stop_all(self) -> None:
        pygame.mixer.stop()

    def close(self) -> None:
        pygame.mixer.quit()

    def _load_sound(
        self,
        cache_path: Path,
        gain: float,
        direction: PlaybackDirection,
    ) -> pygame.mixer.Sound:
        if gain <= 1.0 and direction == "forward":
            return pygame.mixer.Sound(str(cache_path))

        audio = AudioSegment.from_file(cache_path)
        audio = self._apply_direction(audio, direction)
        if gain > 1.0:
            audio = audio + gain_to_db(gain)
        return self._sound_from_segment(audio, 1.0)

    def _apply_direction(self, audio: AudioSegment, direction: PlaybackDirection) -> AudioSegment:
        if direction == "reverse":
            return audio.reverse()
        if direction == "pingpong":
            return audio + audio.reverse()
        return audio

    def _sound_from_segment(self, audio: AudioSegment, gain: float) -> pygame.mixer.Sound:
        if gain > 1.0:
            audio = audio + gain_to_db(gain)

        mixer_init = pygame.mixer.get_init()
        if mixer_init is not None:
            frequency, sample_size, channels = mixer_init
            audio = (
                audio.set_frame_rate(frequency)
                .set_sample_width(abs(sample_size) // 8)
                .set_channels(channels)
            )

        return pygame.mixer.Sound(buffer=audio.raw_data)
