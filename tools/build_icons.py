from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)


def render_svg(svg_path: Path, size: int) -> QPixmap:
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f"Invalid SVG icon: {svg_path}")

    image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))

    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QPixmap.fromImage(image)


def build_icon(svg_path: Path, output_path: Path) -> None:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(render_svg(svg_path, size))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not icon.pixmap(1024, 1024).save(str(output_path)):
        raise RuntimeError(f"Cannot write icon: {output_path}")


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    svg_path = project_root / "soundpad" / "assets" / "app-icon.svg"
    app = QGuiApplication(sys.argv)
    _ = app

    build_icon(svg_path, project_root / "soundpad" / "assets" / "app-icon.ico")
    build_icon(svg_path, project_root / "soundpad" / "assets" / "AppIcon.icns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
