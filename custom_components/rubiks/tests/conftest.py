"""Fixtures and helpers for tests."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def generate_synthetic_face(
    colour_code: str, size: tuple[int, int] = (300, 300)
) -> Image.Image:
    """Generate a synthetic 3×3 cube face image (solid colour per cell).

    Args:
        colour_code: Single letter (W/Y/R/O/B/G)
        size: Image size in pixels

    Returns:
        PIL Image of a 3×3 grid where each cell is the cube sticker colour
    """
    rgb_map = {
        "W": (240, 240, 240),
        "Y": (255, 255, 0),
        "R": (200, 0, 0),
        "O": (255, 140, 0),
        "B": (0, 80, 200),
        "G": (0, 140, 0),
    }

    colour = rgb_map.get(colour_code, (100, 100, 100))
    img = Image.new("RGB", size, colour)

    return img


def generate_rubiks_test_image(
    face_colours: list[str] | None = None,
    size: tuple[int, int] = (300, 300),
) -> Image.Image:
    """Generate a 3×3 grid test image with mixed sticker colours.

    Args:
        face_colours: List of 9 colour codes (W/Y/R/O/B/G), row-major.
                      Defaults to all white.
        size: Cell size in pixels (total image is 3×size)

    Returns:
        PIL Image with 3×3 grid
    """
    if face_colours is None:
        face_colours = ["W"] * 9

    rgb_map = {
        "W": (240, 240, 240),
        "Y": (255, 255, 0),
        "R": (200, 0, 0),
        "O": (255, 140, 0),
        "B": (0, 80, 200),
        "G": (0, 140, 0),
    }

    cell_size = size[0] // 3
    grid_size = (cell_size * 3, cell_size * 3)
    img = Image.new("RGB", grid_size, (50, 50, 50))

    for idx, colour_code in enumerate(face_colours[:9]):
        row = idx // 3
        col = idx % 3
        x = col * cell_size
        y = row * cell_size
        rgb = rgb_map.get(colour_code, (100, 100, 100))
        cell = Image.new("RGB", (cell_size, cell_size), rgb)
        img.paste(cell, (x, y))

    return img


def save_test_image(img: Image.Image, filename: str) -> None:
    """Save test image to tests/samples."""
    path = Path(__file__).parent / "samples" / filename
    img.save(path, quality=85)
