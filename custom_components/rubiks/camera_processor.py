"""Image processing for Rubiks Cube Scanner."""

from __future__ import annotations

import colorsys
import io
import logging
from dataclasses import dataclass

from PIL import Image

_LOGGER = logging.getLogger(__name__)

# HSV hue ranges for each Rubik's cube color.
# Hue is 0-360. Saturation and value are 0-1.
# (hue_min, hue_max, sat_min, val_min) — white/black handled separately via sat/val
CUBE_COLOR_MAP = {
    "R": (340, 360, 0.4, 0.3),   # red (upper range)
    "R2": (0, 15, 0.4, 0.3),     # red (lower range)
    "O": (15, 40, 0.4, 0.3),     # orange
    "Y": (40, 75, 0.4, 0.3),     # yellow
    "G": (75, 165, 0.4, 0.3),    # green
    "B": (165, 260, 0.4, 0.3),   # blue
}


@dataclass
class FaceScan:
    """Result of scanning one cube face."""

    face_label: str
    colors: list[str]  # 9 color codes, row by row (top-left to bottom-right)

    def is_complete(self) -> bool:
        """Return True if all 9 squares were detected."""
        return len(self.colors) == 9 and all(c != "?" for c in self.colors)


def classify_color(r: int, g: int, b: int) -> str:
    """Map an RGB pixel to a Rubik's cube color code."""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    hue = h * 360

    # White: low saturation, high value
    if s < 0.25 and v > 0.7:
        return "W"

    # Check each hue range
    for color, (hmin, hmax, smin, vmin) in CUBE_COLOR_MAP.items():
        key = color.rstrip("2")  # normalise "R2" -> "R"
        if hmin <= hue <= hmax and s >= smin and v >= vmin:
            return key

    _LOGGER.debug("Unclassified color: RGB(%d,%d,%d) HSV(%.0f,%.2f,%.2f)", r, g, b, hue, s, v)
    return "?"


def detect_face_colors(image: Image.Image) -> list[str]:
    """Detect the 9 square colors from a face image.

    Assumes the image is already cropped to the cube face.
    Divides into a 3x3 grid and samples the center of each cell.
    """
    width, height = image.size
    cell_w = width // 3
    cell_h = height // 3

    colors: list[str] = []
    rgb_image = image.convert("RGB")

    for row in range(3):
        for col in range(3):
            # Center pixel of each cell
            cx = col * cell_w + cell_w // 2
            cy = row * cell_h + cell_h // 2

            # Average a small area around center for noise reduction
            sample_size = max(4, min(cell_w, cell_h) // 6)
            left = max(0, cx - sample_size)
            top = max(0, cy - sample_size)
            right = min(width, cx + sample_size)
            bottom = min(height, cy + sample_size)

            region = rgb_image.crop((left, top, right, bottom))
            pixels = list(region.getdata())
            avg_r = sum(p[0] for p in pixels) // len(pixels)
            avg_g = sum(p[1] for p in pixels) // len(pixels)
            avg_b = sum(p[2] for p in pixels) // len(pixels)

            color = classify_color(avg_r, avg_g, avg_b)
            colors.append(color)
            _LOGGER.debug("Cell [%d,%d] RGB(%d,%d,%d) -> %s", row, col, avg_r, avg_g, avg_b, color)

    return colors


def load_image_from_bytes(data: bytes) -> Image.Image:
    """Load a PIL Image from raw bytes (e.g. camera snapshot)."""
    return Image.open(io.BytesIO(data))


def load_image_from_path(path: str) -> Image.Image:
    """Load a PIL Image from a file path (sample image mode)."""
    return Image.open(path)
