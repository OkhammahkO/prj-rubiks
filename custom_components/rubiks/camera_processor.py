"""Image processing for Rubiks Cube Scanner."""

from __future__ import annotations

import colorsys
import io
import logging
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

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

# RGB colors for overlay labels — dark enough to read on any cube color
OVERLAY_COLORS: dict[str, tuple[int, int, int]] = {
    "W": (200, 200, 200),
    "Y": (220, 220, 0),
    "R": (220, 0, 0),
    "O": (220, 120, 0),
    "B": (0, 80, 220),
    "G": (0, 160, 0),
    "?": (255, 0, 255),
}

CropBox = tuple[int, int, int, int]  # left, top, right, bottom


@dataclass
class FaceScan:
    """Result of scanning one cube face."""

    face_label: str           # derived from centre square color
    colors: list[str]         # 9 color codes, row by row
    annotated_image: bytes = field(default_factory=bytes, repr=False)

    def is_complete(self) -> bool:
        """Return True if all 9 squares were detected."""
        return len(self.colors) == 9 and all(c != "?" for c in self.colors)

    @property
    def centre_color(self) -> str:
        """Return the centre square color (index 4)."""
        return self.colors[4] if len(self.colors) == 9 else "?"

    @property
    def has_unknowns(self) -> bool:
        return "?" in self.colors


def classify_color(r: int, g: int, b: int) -> str:
    """Map an RGB pixel to a Rubik's cube color code."""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    hue = h * 360

    if s < 0.25 and v > 0.7:
        return "W"

    for color, (hmin, hmax, smin, vmin) in CUBE_COLOR_MAP.items():
        key = color.rstrip("2")
        if hmin <= hue <= hmax and s >= smin and v >= vmin:
            return key

    _LOGGER.debug(
        "Unclassified color: RGB(%d,%d,%d) HSV(%.0f,%.2f,%.2f)", r, g, b, hue, s, v
    )
    return "?"


def detect_face_colors(
    image: Image.Image,
    crop_box: CropBox | None = None,
) -> FaceScan:
    """Detect the 9 square colors from an image.

    Args:
        image: Full source image.
        crop_box: (left, top, right, bottom) pixel coords of the cube face.
                  If None, the full image is used.

    Returns a FaceScan with colors and an annotated JPEG as bytes.
    """
    if crop_box is not None:
        face_image = image.crop(crop_box)
        box_offset = (crop_box[0], crop_box[1])
    else:
        face_image = image
        box_offset = (0, 0)

    rgb_image = face_image.convert("RGB")
    width, height = rgb_image.size
    cell_w = width // 3
    cell_h = height // 3

    colors: list[str] = []
    sample_points: list[tuple[int, int]] = []  # (cx, cy) relative to face

    for row in range(3):
        for col in range(3):
            cx = col * cell_w + cell_w // 2
            cy = row * cell_h + cell_h // 2

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
            sample_points.append((cx, cy))
            _LOGGER.debug(
                "Cell [%d,%d] RGB(%d,%d,%d) -> %s", row, col, avg_r, avg_g, avg_b, color
            )

    face_label = colors[4] if len(colors) == 9 else "?"
    annotated = _annotate_image(image, crop_box, box_offset, colors, sample_points, cell_w, cell_h)

    return FaceScan(face_label=face_label, colors=colors, annotated_image=annotated)


def _annotate_image(
    image: Image.Image,
    crop_box: CropBox | None,
    box_offset: tuple[int, int],
    colors: list[str],
    sample_points: list[tuple[int, int]],
    cell_w: int,
    cell_h: int,
) -> bytes:
    """Draw crop boundary, grid, sample points, and color labels onto the image."""
    annotated = image.convert("RGB").copy()
    draw = ImageDraw.Draw(annotated, "RGBA")

    ox, oy = box_offset

    # Face boundary box
    if crop_box is not None:
        draw.rectangle(crop_box, outline=(255, 255, 0), width=3)

    # Grid lines (3x3) relative to face origin
    face_w = cell_w * 3
    face_h = cell_h * 3
    for i in range(1, 3):
        # Vertical
        x = ox + i * cell_w
        draw.line([(x, oy), (x, oy + face_h)], fill=(255, 255, 0, 180), width=1)
        # Horizontal
        y = oy + i * cell_h
        draw.line([(ox, y), (ox + face_w, y)], fill=(255, 255, 0, 180), width=1)

    # Sample points and color labels
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=max(12, cell_w // 4))
    except OSError:
        font = ImageFont.load_default()

    dot_radius = max(4, min(cell_w, cell_h) // 10)

    for idx, (color, (cx, cy)) in enumerate(zip(colors, sample_points)):
        ax = ox + cx
        ay = oy + cy
        rgb = OVERLAY_COLORS.get(color, (255, 0, 255))

        # Sample point circle
        draw.ellipse(
            [(ax - dot_radius, ay - dot_radius), (ax + dot_radius, ay + dot_radius)],
            outline=rgb,
            width=2,
        )

        # Color label — black shadow then colored text
        label = color
        draw.text((ax + dot_radius + 1, ay - dot_radius + 1), label, fill=(0, 0, 0), font=font)
        draw.text((ax + dot_radius, ay - dot_radius), label, fill=rgb, font=font)

    buf = io.BytesIO()
    annotated.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def load_image_from_bytes(data: bytes) -> Image.Image:
    """Load a PIL Image from raw bytes (e.g. camera snapshot)."""
    return Image.open(io.BytesIO(data))


def load_image_from_path(path: str) -> Image.Image:
    """Load a PIL Image from a file path (sample image mode)."""
    return Image.open(path)
