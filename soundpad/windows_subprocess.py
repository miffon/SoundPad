from __future__ import annotations

import subprocess
import sys
from typing import Any


_original_popen = subprocess.Popen
_installed = False


def install_hidden_subprocess_windows() -> None:
    global _installed
    if _installed or sys.platform != "win32":
        return
    subprocess.Popen = _hidden_popen  # type: ignore[assignment]
    _installed = True


def _hidden_popen(*args: Any, **kwargs: Any) -> subprocess.Popen:
    # Windows GUI build 沒有 console，ffmpeg/ffprobe 子程序需要明確隱藏視窗。
    kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW

    startupinfo = kwargs.get("startupinfo")
    if startupinfo is None:
        startupinfo = subprocess.STARTUPINFO()
        kwargs["startupinfo"] = startupinfo
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE

    return _original_popen(*args, **kwargs)
