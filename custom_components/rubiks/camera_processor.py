"""Image processing for Rubiks Cube Scanner."""

from __future__ import annotations

import io
import logging
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

_LOGGER = logging.getLogger(__name__)

# Approximate CIELAB values for standard Rubik's cube sticker colours (D65).
# Used for first-pass nearest-neighbour classification before per-session
# calibration refines the centroids from actual camera readings.
REFERENCE_LAB: dict[str, tuple[float, float, float]] = {
    # Approximate OV2640 readings — a/b channels are compressed vs standard LAB.
    # R and O measured from this specific unit (two sessions, very consistent).
    # Other colours from a different unit — replace via Save Calibration after a clean scan.
    "W": ( 66.0,  16.0, -15.0),
    "Y": ( 74.0,  -1.0,  26.0),
    "R": ( 35.0,  50.0,  22.0),  # measured: centres (33.5,49.7,23.4) (33.6,49.7,23.4)
    "O": ( 62.0,  47.0,  27.0),  # measured: centres (61.9,47.9,27.7) (62.1,47.6,26.3)
    "B": ( 32.0,  33.0, -51.0),
    "G": ( 45.0, -15.0,  14.0),
}

# RGB colours for the annotated image overlay labels
OVERLAY_COLORS: dict[str, tuple[int, int, int]] = {
    "W": (200, 200, 200),
    "Y": (220, 220,   0),
    "R": (220,   0,   0),
    "O": (220, 120,   0),
    "B": (  0,  80, 220),
    "G": (  0, 160,   0),
    "?": (255,   0, 255),
}

CropBox = tuple[int, int, int, int]  # left, top, right, bottom

_L_WEIGHT = 1.5   # L is a reliable discriminator on OV2640 — Red L≈14-38, Orange L≈40-63
_AB_WEIGHT = 2.0  # chrominance weighted more — hue separation is what matters
_LAB_UNKNOWN_THRESHOLD = 80.0  # distance beyond which a sample is classified "?"

# 5 sample offsets per cell: centre + 4 inner corners (at ¼ cell distance).
_OFFSETS = [(0, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)]


def _srgb_to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert sRGB (0-255) to CIELAB (D65 illuminant)."""
    def _lin(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    rl, gl, bl = _lin(r), _lin(g), _lin(b)
    x = (rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375) / 0.95047
    y = (rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750) / 1.00000
    z = (rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041) / 1.08883

    def _f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0

    fx, fy, fz = _f(x), _f(y), _f(z)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def lab_distance(
    lab1: tuple[float, float, float],
    lab2: tuple[float, float, float],
) -> float:
    """Weighted Euclidean distance in LAB — a/b channels weighted over L."""
    dl = (lab1[0] - lab2[0]) * _L_WEIGHT
    da = (lab1[1] - lab2[1]) * _AB_WEIGHT
    db = (lab1[2] - lab2[2]) * _AB_WEIGHT
    return math.sqrt(dl * dl + da * da + db * db)


def classify_lab(
    lab: tuple[float, float, float],
    references: dict[str, tuple[float, float, float]],
) -> str:
    """Nearest-neighbour LAB classification. Returns '?' if too far from all references."""
    best = min(references, key=lambda c: lab_distance(lab, references[c]))
    if lab_distance(lab, references[best]) > _LAB_UNKNOWN_THRESHOLD:
        _LOGGER.debug("Unclassified LAB(%.1f, %.1f, %.1f)", *lab)
        return "?"
    return best


@dataclass
class FaceScan:
    """Result of scanning one cube face."""

    face_label: str
    colors: list[str]                                       # 9 colour codes, row by row
    lab_readings: list[tuple[float, float, float]] = field(default_factory=list)
    annotated_image: bytes = field(default_factory=bytes, repr=False)

    def is_complete(self) -> bool:
        """Return True if all 9 squares were detected."""
        return len(self.colors) == 9 and all(c != "?" for c in self.colors)

    @property
    def centre_color(self) -> str:
        """Return the centre square colour (index 4)."""
        return self.colors[4] if len(self.colors) == 9 else "?"

    @property
    def has_unknowns(self) -> bool:
        return "?" in self.colors


def detect_face_colors(
    image: Image.Image,
    crop_box: CropBox | None = None,
    references: dict[str, tuple[float, float, float]] | None = None,
    override_centre: str | None = None,
) -> FaceScan:
    """Detect the 9 square colours from an image using LAB nearest-neighbour classification.

    Args:
        image: Full source image.
        crop_box: (left, top, right, bottom) pixel coords of the cube face.
                  If None the full image is used.
        references: LAB centroids per colour. Defaults to REFERENCE_LAB; replaced
                    by calibrated centroids after a full 6-face scan.

    Returns a FaceScan with colours, LAB readings, and an annotated JPEG.
    """
    refs = references or REFERENCE_LAB

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

    lab_readings_raw: list[tuple[float, float, float]] = []
    per_cell_points: list[list[tuple[int, int]]] = []
    per_cell_labs: list[list[tuple[float, float, float]]] = []

    sample_size = max(3, min(cell_w, cell_h) // 8)
    step_x = cell_w // 4
    step_y = cell_h // 4

    for row in range(3):
        for col in range(3):
            cx = col * cell_w + cell_w // 2
            cy = row * cell_h + cell_h // 2
            cell_samples: list[tuple[int, int]] = []
            cell_lab_samples: list[tuple[float, float, float]] = []

            for dx, dy in _OFFSETS:
                px = cx + dx * step_x
                py = cy + dy * step_y
                left_s = max(0, px - sample_size)
                top_s = max(0, py - sample_size)
                right_s = min(width, px + sample_size)
                bottom_s = min(height, py + sample_size)

                region = rgb_image.crop((left_s, top_s, right_s, bottom_s))
                pixels = list(region.getdata())
                avg_r = sum(p[0] for p in pixels) // len(pixels)
                avg_g = sum(p[1] for p in pixels) // len(pixels)
                avg_b = sum(p[2] for p in pixels) // len(pixels)
                cell_samples.append((px, py))
                cell_lab_samples.append(_srgb_to_lab(avg_r, avg_g, avg_b))

            per_cell_points.append(cell_samples)
            per_cell_labs.append(cell_lab_samples)
            # Median LAB across 5 sample points — stored for logging/display only; classification uses majority vote above.
            lab_readings_raw.append((
                statistics.median(pt[0] for pt in cell_lab_samples),
                statistics.median(pt[1] for pt in cell_lab_samples),
                statistics.median(pt[2] for pt in cell_lab_samples),
            ))

    # Per-cell classification: classify each of 5 sample points, majority vote wins.
    colors: list[str] = []
    all_point_colors: list[list[str]] = []

    for cell_idx, ((row, col), cell_samples, point_labs) in enumerate(
        zip([(r, c) for r in range(3) for c in range(3)], per_cell_points, per_cell_labs)
    ):
        point_colors = [classify_lab(lab, refs) for lab in point_labs]
        all_point_colors.append(point_colors)

        counts = Counter(point_colors)
        winner = counts.most_common(1)[0][0]
        colors.append(winner)

        L, a, b = lab_readings_raw[cell_idx]
        _LOGGER.info(
            "Cell [%d,%d] LAB(%.1f, %.1f, %.1f) point_votes=%s -> %s",
            row, col, L, a, b, dict(counts), winner,
        )

    if override_centre and len(colors) == 9:
        _LOGGER.info(
            "Centre colour overridden: detected %s → declared %s",
            colors[4], override_centre,
        )
        colors[4] = override_centre

    face_label = colors[4] if len(colors) == 9 else "?"
    annotated = _annotate_image(
        image, crop_box, box_offset, colors,
        per_cell_points, all_point_colors,
        cell_w, cell_h, lab_readings_raw,
    )

    return FaceScan(
        face_label=face_label,
        colors=colors,
        lab_readings=lab_readings_raw,
        annotated_image=annotated,
    )


def _annotate_image(
    image: Image.Image,
    crop_box: CropBox | None,
    box_offset: tuple[int, int],
    colors: list[str],
    per_cell_points: list[list[tuple[int, int]]],
    all_point_colors: list[list[str]],
    cell_w: int,
    cell_h: int,
    lab_readings: list[tuple[float, float, float]] | None = None,
) -> bytes:
    """Draw crop boundary, grid, per-cell sample dots, colour labels, and LAB values."""
    annotated = image.convert("RGB").copy()
    draw = ImageDraw.Draw(annotated, "RGBA")

    ox, oy = box_offset

    if crop_box is not None:
        draw.rectangle(crop_box, outline=(255, 255, 0), width=3)

    face_w = cell_w * 3
    face_h = cell_h * 3
    for i in range(1, 3):
        x = ox + i * cell_w
        draw.line([(x, oy), (x, oy + face_h)], fill=(255, 255, 0, 180), width=1)
        y = oy + i * cell_h
        draw.line([(ox, y), (ox + face_w, y)], fill=(255, 255, 0, 180), width=1)

    label_font_size = max(10, cell_w // 4)
    debug_font_size = max(7, cell_w // 8)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=label_font_size
        )
        font_small = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=debug_font_size
        )
    except OSError:
        font = ImageFont.load_default()
        font_small = font

    centre_dot_r = max(4, min(cell_w, cell_h) // 10)
    corner_dot_r = max(2, centre_dot_r // 2)

    for cell_idx, (color, cell_samples, point_colors) in enumerate(
        zip(colors, per_cell_points, all_point_colors)
    ):
        winning_rgb = OVERLAY_COLORS.get(color, (255, 0, 255))

        for pt_idx, ((px, py), pt_color) in enumerate(zip(cell_samples, point_colors)):
            ax = ox + px
            ay = oy + py
            pt_rgb = OVERLAY_COLORS.get(pt_color, (255, 0, 255))
            r = centre_dot_r if pt_idx == 0 else corner_dot_r
            draw.ellipse([(ax - r, ay - r), (ax + r, ay + r)], fill=pt_rgb)

        cx, cy = cell_samples[0]
        ax, ay = ox + cx, oy + cy
        tx, ty = ax + centre_dot_r, ay - centre_dot_r

        lab_label = ""
        if lab_readings and cell_idx < len(lab_readings):
            L, a, b = lab_readings[cell_idx]
            lab_label = f"L{L:.0f} a{a:.0f} b{b:.0f}"

        # Semi-transparent background box behind all text for legibility
        pad = 2
        box_h = label_font_size + (debug_font_size + pad if lab_label else 0) + pad * 2
        box_w = max(
            draw.textlength(color, font=font),
            draw.textlength(lab_label, font=font_small) if lab_label else 0,
        ) + pad * 2
        draw.rectangle(
            [(tx - pad, ty - pad), (tx + box_w, ty + box_h)],
            fill=(0, 0, 0, 160),
        )

        # Colour letter
        draw.text((tx, ty), color, fill=winning_rgb, font=font)

        # LAB values
        if lab_label:
            draw.text((tx, ty + label_font_size + pad), lab_label, fill=(220, 220, 220), font=font_small)

    buf = io.BytesIO()
    annotated.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def load_image_from_bytes(data: bytes) -> Image.Image:
    """Load a PIL Image from raw bytes (e.g. camera snapshot)."""
    return Image.open(io.BytesIO(data))


def load_image_from_path(path: str) -> Image.Image:
    """Load a PIL Image from a file path (sample image mode)."""
    return Image.open(path)


_LOW_CONF_THRESHOLD = 0.15


@dataclass
class CalibrationResult:
    """Result of per-session colour calibration across all 6 faces."""

    calibrated_faces: dict[str, list[str]]           # face_label -> 9 corrected colours
    anchors: dict[str, tuple[float, float, float]]   # colour -> final LAB centroid
    low_confidence: list[dict]                       # stickers where margin < threshold
    pre_calibration_changes: list[dict]              # stickers changed vs raw first pass
    parity_valid: bool
    parity_error: str | None


def calibrate_faces(face_scans: dict[str, FaceScan]) -> CalibrationResult:
    """Per-session calibration using centre squares as LAB anchors.

    1. Build 6 LAB anchors from centre squares (cell index 4).
    2. Greedy constrained assignment — max 9 stickers per colour, sorted by distance.
    3. Recompute centroids from first assignment, do one final pass.
    4. Compute confidence margins; flag low-confidence stickers.
    5. Validate colour counts (full permutation parity deferred until face-adjacency is known).
    """
    colour_order = list(face_scans.keys())

    stickers: list[tuple[str, int, str, tuple[float, float, float]]] = [
        (fl, ci, scan.colors[ci], scan.lab_readings[ci])
        for fl, scan in face_scans.items()
        for ci in range(9)
        if len(scan.lab_readings) == 9
    ]

    if len(stickers) != 54:
        _LOGGER.error("calibrate_faces: expected 54 stickers, got %d", len(stickers))
        return CalibrationResult(
            calibrated_faces={fl: list(scan.colors) for fl, scan in face_scans.items()},
            anchors={},
            low_confidence=[],
            pre_calibration_changes=[],
            parity_valid=False,
            parity_error="Incomplete scan data",
        )

    anchors: dict[str, tuple[float, float, float]] = {
        fl: scan.lab_readings[4]
        for fl, scan in face_scans.items()
        if len(scan.lab_readings) == 9
    }

    def _greedy_assign(
        anchors: dict[str, tuple[float, float, float]],
    ) -> list[str | None]:
        assigned: list[str | None] = [None] * len(stickers)
        count = {c: 0 for c in colour_order}
        # Centre stickers (cell index 4) are known data points — lock them first.
        for si, (fl, ci, _, _) in enumerate(stickers):
            if ci == 4:
                assigned[si] = fl
                count[fl] += 1
        pairs = sorted(
            (lab_distance(stickers[si][3], anchors[colour]), si, colour)
            for si in range(len(stickers))
            if assigned[si] is None
            for colour in colour_order
        )
        done = sum(1 for a in assigned if a is not None)
        for _, si, colour in pairs:
            if assigned[si] is not None or count[colour] >= 9:
                continue
            assigned[si] = colour
            count[colour] += 1
            done += 1
            if done == len(stickers):
                break
        return assigned

    assignment = _greedy_assign(anchors)

    # Recompute centroids from first assignment
    clusters: dict[str, list[tuple[float, float, float]]] = {c: [] for c in colour_order}
    for si, colour in enumerate(assignment):
        if colour:
            clusters[colour].append(stickers[si][3])
    anchors = {
        colour: tuple(  # type: ignore[assignment]
            statistics.median(pt[i] for pt in labs) for i in range(3)
        ) if (labs := clusters[colour]) else anchors[colour]
        for colour in colour_order
    }

    final_assignment = _greedy_assign(anchors)

    # Confidence: margin between 1st and 2nd closest centroid, normalised 0-1
    all_sorted_dists = [
        sorted((lab_distance(stickers[si][3], anchors[c]), c) for c in colour_order)
        for si in range(len(stickers))
    ]
    max_dist = max(d[0][0] for d in all_sorted_dists) or 1.0
    margins = [(d[1][0] - d[0][0]) / max_dist for d in all_sorted_dists]

    calibrated_faces: dict[str, list[str]] = {fl: ["?"] * 9 for fl in colour_order}
    low_confidence: list[dict] = []
    pre_calibration_changes: list[dict] = []

    for si, (face_label, cell_idx, raw_color, _) in enumerate(stickers):
        colour = final_assignment[si] or "?"
        calibrated_faces[face_label][cell_idx] = colour
        margin = round(margins[si], 3)
        if margin < _LOW_CONF_THRESHOLD:
            low_confidence.append({
                "face": face_label,
                "cell": cell_idx,
                "assigned": colour,
                "raw": raw_color,
                "margin": margin,
                "runner_up": all_sorted_dists[si][1][1],
            })
        if colour != raw_color:
            pre_calibration_changes.append({
                "face": face_label, "cell": cell_idx,
                "from": raw_color, "to": colour,
            })

    parity_valid, parity_error = check_cube_parity(calibrated_faces)

    _LOGGER.debug(
        "Calibration anchors: %s",
        {c: tuple(round(x, 1) for x in lab) for c, lab in anchors.items()},
    )
    _LOGGER.info(
        "Calibration: %d corrections, %d low-confidence, parity %s",
        len(pre_calibration_changes),
        len(low_confidence),
        "OK" if parity_valid else f"FAIL ({parity_error})",
    )

    return CalibrationResult(
        calibrated_faces=calibrated_faces,
        anchors={c: tuple(round(x, 2) for x in lab) for c, lab in anchors.items()},  # type: ignore[misc]
        low_confidence=low_confidence,
        pre_calibration_changes=pre_calibration_changes,
        parity_valid=parity_valid,
        parity_error=parity_error,
    )


def generate_summary_image(
    face_images: dict[str, bytes],
    face_order: list[str] | None = None,
) -> bytes:
    """Compose up to 6 face annotated images into a 3×2 summary grid."""
    order = face_order or ["W", "Y", "R", "O", "B", "G"]
    cols, rows = 3, 2
    thumb_w, thumb_h = 160, 120
    pad = 4
    label_h = 16

    grid_w = cols * thumb_w + (cols + 1) * pad
    grid_h = rows * (thumb_h + label_h) + (rows + 1) * pad
    grid = Image.new("RGB", (grid_w, grid_h), (30, 30, 30))
    draw = ImageDraw.Draw(grid)

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=11
        )
    except OSError:
        font = ImageFont.load_default()

    for i, face_label in enumerate(order):
        if face_label not in face_images:
            continue
        col = i % cols
        row = i // cols
        x = pad + col * (thumb_w + pad)
        y = pad + row * (thumb_h + label_h + pad)

        thumb = Image.open(io.BytesIO(face_images[face_label])).resize(
            (thumb_w, thumb_h), Image.LANCZOS
        )
        label_rgb = OVERLAY_COLORS.get(face_label, (200, 200, 200))
        draw.rectangle([(x, y), (x + thumb_w, y + label_h - 1)], fill=(20, 20, 20))
        draw.text((x + 4, y + 2), face_label, fill=label_rgb, font=font)
        grid.paste(thumb, (x, y + label_h))

    buf = io.BytesIO()
    grid.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def check_running_validity(scanned_faces: dict[str, list[str]]) -> list[str]:
    """Return plain-English warnings about the current scan state.

    Called after each face is stored so problems surface early.
    Checks:
    - No colour appears more than 9 times across all scanned faces so far
    - After all 6 faces: each colour appears as a centre exactly once
    """
    warnings: list[str] = []
    n_faces = len(scanned_faces)
    all_colours = [c for colours in scanned_faces.values() for c in colours]
    counts = Counter(all_colours)

    colour_names = {
        "W": "White", "Y": "Yellow", "R": "Red",
        "O": "Orange", "B": "Blue", "G": "Green",
    }

    for colour, count in counts.items():
        if count > 9:
            name = colour_names.get(colour, colour)
            warnings.append(
                f"{name} appears {count} times across {n_faces} face(s) — 9 is the maximum"
            )

    if n_faces == 6:
        centres = set(scanned_faces.keys())
        expected = set(colour_names.keys())
        missing = expected - centres
        duplicates = centres - expected
        if missing:
            warnings.append(
                f"No centre found for: {', '.join(colour_names.get(c, c) for c in sorted(missing))}"
            )
        if duplicates:
            warnings.append(
                f"Unexpected centre colour(s): {', '.join(sorted(duplicates))}"
            )

    return warnings


def check_cube_parity(calibrated_faces: dict[str, list[str]]) -> tuple[bool, str | None]:
    """Validate colour counts across all 6 faces.

    Full permutation parity check is deferred until face-adjacency is known
    (required for the solve step).
    """
    all_colours = [c for colours in calibrated_faces.values() for c in colours]
    if len(all_colours) != 54:
        return False, f"Expected 54 stickers, got {len(all_colours)}"
    counts = Counter(all_colours)
    if len(counts) != 6:
        return False, f"Expected 6 colours, got {len(counts)}: {dict(counts)}"
    wrong = {k: v for k, v in counts.items() if v != 9}
    if wrong:
        return False, f"Unequal counts: {wrong}"
    return True, None
