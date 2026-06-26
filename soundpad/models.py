from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Any


SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3"}
VOLUME_GAIN_MAX_DB = 18.0
VOLUME_GAIN_MAX = math.pow(10.0, VOLUME_GAIN_MAX_DB / 20.0)


def clamp_volume_gain(gain: float) -> float:
    return max(0.0, min(VOLUME_GAIN_MAX, float(gain)))


def gain_to_db(gain: float) -> float:
    gain = clamp_volume_gain(gain)
    if gain <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(gain)


def db_to_gain(db_value: float) -> float:
    if math.isinf(db_value) and db_value < 0:
        return 0.0
    return clamp_volume_gain(math.pow(10.0, float(db_value) / 20.0))


@dataclass
class PadConfig:
    pad_id: int
    source_path: str = ""
    cache_path: str = ""
    start_ms: int = 0
    end_ms: int = 0
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    volume: float = 1.0
    display_name: str = ""
    custom_label: str = ""

    @property
    def cache_file(self) -> Path | None:
        if not self.cache_path:
            return None
        return Path(self.cache_path)

    @property
    def source_file(self) -> Path | None:
        if not self.source_path:
            return None
        return Path(self.source_path)

    @property
    def has_cache(self) -> bool:
        return self.cache_file is not None and self.cache_file.exists()

    @property
    def has_source(self) -> bool:
        return self.source_file is not None and self.source_file.exists()

    @property
    def is_empty(self) -> bool:
        return not self.source_path and not self.cache_path

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["volume"] = clamp_volume_gain(self.volume)
        data["fade_in_ms"] = max(0, int(self.fade_in_ms))
        data["fade_out_ms"] = max(0, int(self.fade_out_ms))
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any], pad_id: int) -> "PadConfig":
        return cls(
            pad_id=int(data.get("pad_id", pad_id)),
            source_path=str(data.get("source_path", "")),
            cache_path=str(data.get("cache_path", "")),
            start_ms=int(data.get("start_ms", 0)),
            end_ms=int(data.get("end_ms", 0)),
            fade_in_ms=max(0, int(data.get("fade_in_ms", 0))),
            fade_out_ms=max(0, int(data.get("fade_out_ms", 0))),
            volume=clamp_volume_gain(float(data.get("volume", 1.0))),
            display_name=str(data.get("display_name", "")),
            custom_label=str(data.get("custom_label", "")),
        )


@dataclass
class AppSettings:
    output_device_name: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"output_device_name": self.output_device_name}

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> "AppSettings":
        if not isinstance(data, dict):
            return cls()
        return cls(output_device_name=str(data.get("output_device_name", "")))


@dataclass
class PageConfig:
    page_id: int
    name: str
    pads: list[PadConfig]

    def to_json(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "name": self.name,
            "pads": [pad.to_json() for pad in self.pads],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any], page_id: int) -> "PageConfig":
        pads = [
            PadConfig.from_json(item, index + 1)
            for index, item in enumerate(data.get("pads", []))
            if isinstance(item, dict)
        ]
        return cls(
            page_id=int(data.get("page_id", page_id)),
            name=str(data.get("name", f"Page {page_id}")),
            pads=pads,
        )


def is_supported_audio_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
