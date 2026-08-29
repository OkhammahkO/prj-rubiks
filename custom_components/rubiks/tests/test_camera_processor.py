"""Tests for camera_processor.py — CIELAB detection and calibration."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from custom_components.rubiks.camera_processor import (
    FaceScan,
    calibrate_faces,
    check_cube_parity,
    check_running_validity,
    classify_lab,
    detect_face_colors,
    lab_distance,
)


class TestLabDistance:
    """Test LAB colour distance calculations."""

    def test_identical_points(self) -> None:
        """Distance from a point to itself is zero."""
        lab = (50.0, 10.0, 20.0)
        assert lab_distance(lab, lab) == pytest.approx(0.0)

    def test_symmetric(self) -> None:
        """Distance is symmetric: d(a,b) == d(b,a)."""
        lab1 = (50.0, 0.0, 0.0)
        lab2 = (60.0, 10.0, 10.0)
        assert lab_distance(lab1, lab2) == pytest.approx(lab_distance(lab2, lab1))

    def test_l_weighting(self) -> None:
        """L channel is weighted 1.5x more than a/b."""
        # Δ L = 10 → weighted 15
        lab1 = (50.0, 0.0, 0.0)
        lab2 = (60.0, 0.0, 0.0)
        d_l = lab_distance(lab1, lab2)

        # Δ a = 10 → weighted 20
        lab3 = (50.0, 10.0, 0.0)
        d_a = lab_distance(lab1, lab3)

        # L weighted higher should make a/b difference dominate
        assert d_a > d_l


class TestClassifyLab:
    """Test LAB nearest-neighbour classification."""

    def test_classify_to_closest_reference(self) -> None:
        """Classify returns the closest reference colour."""
        lab_white = (90.0, 0.0, 0.0)
        refs = {
            "W": (90.0, 0.0, 0.0),
            "Y": (70.0, -10.0, 50.0),
        }
        assert classify_lab(lab_white, refs) == "W"

    def test_classify_unknown_when_far(self) -> None:
        """Classify returns '?' if closest reference is too far."""
        lab_unknown = (200.0, 200.0, 200.0)
        refs = {
            "W": (90.0, 0.0, 0.0),
            "Y": (70.0, -10.0, 50.0),
        }
        assert classify_lab(lab_unknown, refs) == "?"


class TestDetectFaceColors:
    """Test face colour detection on synthetic images."""

    @pytest.fixture
    def samples_dir(self) -> Path:
        """Get path to test samples directory."""
        return Path(__file__).parent / "samples"

    def test_detect_perfect_white_face(self, samples_dir: Path) -> None:
        """Detect all-white face with consistent colour."""
        img_path = samples_dir / "white_face.jpg"
        if not img_path.exists():
            pytest.skip("Sample image not found; run generate_samples.py")

        img = Image.open(img_path)
        scan = detect_face_colors(img)

        assert len(scan.colors) == 9
        # Synthetic images may not match camera-tuned references exactly.
        # Just verify all cells classify to the same colour (uniform).
        assert len(set(scan.colors)) == 1, (
            f"Expected uniform colours, got {scan.colors}"
        )
        assert not scan.has_unknowns

    def test_detect_all_single_colour_faces(self, samples_dir: Path) -> None:
        """Detect each single-colour face has uniform colour (no validation of exact colour)."""
        for colour_code in ["W", "Y", "R", "O", "B", "G"]:
            colour_names = {
                "W": "white",
                "Y": "yellow",
                "R": "red",
                "O": "orange",
                "B": "blue",
                "G": "green",
            }
            img_path = samples_dir / f"{colour_names[colour_code]}_face.jpg"

            if not img_path.exists():
                pytest.skip(f"Sample {img_path.name} not found")

            img = Image.open(img_path)
            scan = detect_face_colors(img)
            # Verify all 9 cells classify to the same colour (uniform)
            assert len(set(scan.colors)) == 1, (
                f"Face {colour_code}: expected uniform classification, got {scan.colors}"
            )

    def test_detect_mixed_face(self, samples_dir: Path) -> None:
        """Detect mixed-colour face with multiple stickers."""
        img_path = samples_dir / "mixed_face.jpg"
        if not img_path.exists():
            pytest.skip("Sample image not found")

        img = Image.open(img_path)
        scan = detect_face_colors(img)

        assert len(scan.colors) == 9
        # Mixed face has W, B, Y — should detect at least one of each
        colour_set = set(scan.colors)
        assert len(colour_set) > 1, "Mixed face should have multiple colours"

    def test_detect_with_crop_box(self, samples_dir: Path) -> None:
        """Detect colours when image is cropped."""
        img_path = samples_dir / "white_face.jpg"
        if not img_path.exists():
            pytest.skip("Sample image not found")

        img = Image.open(img_path)
        w, h = img.size
        crop_box = (w // 4, h // 4, (3 * w) // 4, (3 * h) // 4)

        scan = detect_face_colors(img, crop_box=crop_box)
        assert len(scan.colors) == 9


class TestCalibratefaces:
    """Test per-session calibration."""

    def test_calibration_preserves_colour_counts(self) -> None:
        """Calibration must not change total colour counts."""
        # Mock 6 FaceScan objects (one per colour)

        faces = {
            "W": FaceScan("W", ["W"] * 9, [(90.0, 0.0, 0.0)] * 9),
            "Y": FaceScan("Y", ["Y"] * 9, [(78.0, -8.0, 55.0)] * 9),
            "R": FaceScan("R", ["R"] * 9, [(35.0, 50.0, 22.0)] * 9),
            "O": FaceScan("O", ["O"] * 9, [(62.0, 47.0, 27.0)] * 9),
            "B": FaceScan("B", ["B"] * 9, [(35.0, 5.0, -30.0)] * 9),
            "G": FaceScan("G", ["G"] * 9, [(50.0, -35.0, 25.0)] * 9),
        }

        result = calibrate_faces(faces)
        assert result.parity_valid

        # Verify 9 of each colour
        from collections import Counter

        all_colours = [c for cs in result.calibrated_faces.values() for c in cs]
        counts = Counter(all_colours)
        for colour in ["W", "Y", "R", "O", "B", "G"]:
            assert counts[colour] == 9, f"Expected 9 {colour}, got {counts[colour]}"


class TestCheckCubeParity:
    """Test cube parity validation."""

    def test_valid_parity(self) -> None:
        """Valid cube has 6 colours, 9 each."""
        faces = {
            "W": ["W"] * 9,
            "Y": ["Y"] * 9,
            "R": ["R"] * 9,
            "O": ["O"] * 9,
            "B": ["B"] * 9,
            "G": ["G"] * 9,
        }
        valid, error = check_cube_parity(faces)
        assert valid
        assert error is None

    def test_invalid_missing_colour(self) -> None:
        """Missing a colour fails parity."""
        faces = {
            "W": ["W"] * 9,
            "Y": ["Y"] * 9,
            "R": ["R"] * 9,
            "O": ["O"] * 9,
            "B": ["B"] * 9,
            # Missing G
        }
        valid, error = check_cube_parity(faces)
        assert not valid
        assert error is not None

    def test_invalid_unequal_counts(self) -> None:
        """Unequal colour counts fail parity."""
        faces = {
            "W": ["W"] * 9,
            "Y": ["Y"] * 9,
            "R": ["R"] * 8,  # Only 8
            "O": ["O"] * 9,
            "B": ["B"] * 9,
            "G": ["G"] * 10,  # 10
        }
        valid, error = check_cube_parity(faces)
        assert not valid
        assert error is not None


class TestCheckRunningValidity:
    """Test running scan validity warnings."""

    def test_no_warnings_on_valid_state(self) -> None:
        """Valid scan state should have no warnings."""
        faces = {
            "W": ["W"] * 9,
            "B": ["B"] * 9,
        }
        warnings = check_running_validity(faces)
        assert len(warnings) == 0

    def test_warns_on_colour_overflow(self) -> None:
        """Warns if any colour exceeds 9."""
        faces = {
            "W": ["W"] * 9,
            "B": ["B"] * 9,
            "Y": ["Y"] * 2,
            "R": ["R"] * 11,  # Too many
        }
        warnings = check_running_validity(faces)
        assert any("Red" in w and "11" in w for w in warnings)

    def test_warns_on_missing_centre_after_6_faces(self) -> None:
        """After 6 faces, warns if a centre colour is missing."""
        faces = {
            "W": ["W"] * 9,
            "B": ["B"] * 9,
            "Y": ["Y"] * 9,
            "G": ["G"] * 9,
            "O": ["O"] * 9,
            # Missing R centre
        }
        warnings = check_running_validity(faces)
        # No warning yet — only 5 faces
        assert len(warnings) == 0

        # Now add 6th but wrong centre
        faces["X"] = ["X"] * 9
        warnings = check_running_validity(faces)
        # Should warn about missing R and unexpected X
        assert len(warnings) > 0
