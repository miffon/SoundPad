import os

from soundpad.windows_subprocess import install_hidden_subprocess_windows


os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
install_hidden_subprocess_windows()

from soundpad.app import run


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
