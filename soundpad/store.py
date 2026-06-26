from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from .models import AppSettings, PadConfig, PageConfig


PADS_PER_PAGE = 16


class ProjectStore:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.cache_root = project_root / "cache"
        self.config_path = project_root / "soundpad" / "config.toml"
        self.legacy_config_path = self.cache_root / "soundpad.json"
        self.cache_dir = self.cache_root / "clips"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def default_pages(self) -> list[PageConfig]:
        return [self.new_page(1, "Page 1", 1)]

    def new_page(self, page_id: int, name: str, first_pad_id: int) -> PageConfig:
        pads = [PadConfig(pad_id=first_pad_id + index) for index in range(PADS_PER_PAGE)]
        return PageConfig(page_id=page_id, name=name, pads=pads)

    def cache_path_for_pad(self, pad_id: int) -> Path:
        return self.cache_dir / f"pad_{pad_id:02d}.wav"

    def load(self) -> list[PageConfig]:
        pages, _settings = self.load_project()
        return pages

    def load_project(self) -> tuple[list[PageConfig], AppSettings]:
        if self.config_path.exists():
            try:
                raw = tomllib.loads(self.config_path.read_text(encoding="utf-8"))
            except (tomllib.TOMLDecodeError, OSError):
                return self.default_pages(), AppSettings()
            return self._project_from_mapping(raw)

        if self.legacy_config_path.exists():
            pages, settings = self._load_legacy_json()
            self.save_project(pages, settings)
            return pages, settings

        return self.default_pages(), AppSettings()

    def _load_legacy_json(self) -> tuple[list[PageConfig], AppSettings]:
        try:
            raw = json.loads(self.legacy_config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self.default_pages(), AppSettings()
        return self._project_from_mapping(raw)

    def _project_from_mapping(self, raw: dict[str, Any]) -> tuple[list[PageConfig], AppSettings]:
        pages = [
            self._normalize_page(PageConfig.from_json(item, index + 1))
            for index, item in enumerate(raw.get("pages", []))
            if isinstance(item, dict)
        ]
        if not pages:
            pages = self.default_pages()
        return pages, AppSettings.from_json(raw.get("settings"))

    def save(self, pages: list[PageConfig]) -> None:
        _existing_pages, settings = self.load_project()
        self.save_project(pages, settings)

    def save_project(self, pages: list[PageConfig], settings: AppSettings) -> None:
        data = {
            "version": 2,
            "settings": settings.to_json(),
            "pages": [page.to_json() for page in pages],
        }
        self.config_path.write_text(self._project_to_toml(data), encoding="utf-8")

    def _normalize_page(self, page: PageConfig) -> PageConfig:
        pads = list(page.pads[:PADS_PER_PAGE])
        next_pad_id = max((pad.pad_id for pad in pads), default=0) + 1
        while len(pads) < PADS_PER_PAGE:
            pads.append(PadConfig(pad_id=next_pad_id))
            next_pad_id += 1
        return PageConfig(page_id=page.page_id, name=page.name, pads=pads)

    def _project_to_toml(self, data: dict[str, Any]) -> str:
        lines = [
            f"version = {int(data.get('version', 2))}",
            "",
            "[settings]",
            f"output_device_name = {_toml_string(data['settings'].get('output_device_name', ''))}",
            "",
        ]
        for page in data.get("pages", []):
            lines.extend(
                [
                    "[[pages]]",
                    f"page_id = {int(page.get('page_id', 0))}",
                    f"name = {_toml_string(page.get('name', ''))}",
                    "",
                ]
            )
            for pad in page.get("pads", []):
                lines.extend(
                    [
                        "[[pages.pads]]",
                        f"pad_id = {int(pad.get('pad_id', 0))}",
                        f"source_path = {_toml_string(pad.get('source_path', ''))}",
                        f"cache_path = {_toml_string(pad.get('cache_path', ''))}",
                        f"start_ms = {int(pad.get('start_ms', 0))}",
                        f"end_ms = {int(pad.get('end_ms', 0))}",
                        f"fade_in_ms = {int(pad.get('fade_in_ms', 0))}",
                        f"fade_out_ms = {int(pad.get('fade_out_ms', 0))}",
                        f"volume = {float(pad.get('volume', 1.0)):.6g}",
                        f"display_name = {_toml_string(pad.get('display_name', ''))}",
                        f"custom_label = {_toml_string(pad.get('custom_label', ''))}",
                        "",
                    ]
                )
        return "\n".join(lines)


def _toml_string(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)
