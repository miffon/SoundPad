"""SoundPad application package."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _version_from_pyproject() -> str:
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return "0.1.0"


try:
    __version__ = version("soundpad")
except PackageNotFoundError:
    __version__ = _version_from_pyproject()
