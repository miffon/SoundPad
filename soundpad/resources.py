from __future__ import annotations

import sys
from pathlib import Path


def resource_path(*parts: str) -> Path:
    package_path = Path(__file__).parent.joinpath(*parts)
    if package_path.exists():
        return package_path

    executable_path = _external_executable_path()
    app_resources = executable_path.parent.parent / "Resources" / "soundpad"
    app_path = app_resources.joinpath(*parts)
    if app_path.exists():
        return app_path

    standalone_path = executable_path.parent / "soundpad"
    return standalone_path.joinpath(*parts)


def app_root() -> Path:
    if "__compiled__" in globals() or getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "SoundPad"
        return _external_executable_path().parent
    return Path.cwd()


def _external_executable_path() -> Path:
    # Nuitka onefile may run from an internal extraction path; argv[0] keeps the user-facing exe/app path.
    return Path(sys.argv[0]).resolve()
