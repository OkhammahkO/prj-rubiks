"""Generate synthetic test images for CI/manual testing."""

from __future__ import annotations

from pathlib import Path

from conftest import generate_rubiks_test_image


def main() -> None:
    """Generate all test sample images."""
    samples_dir = Path(__file__).parent / "samples"
    samples_dir.mkdir(exist_ok=True)

    # Single-colour faces (perfect detection scenario)
    for colour, code in [
        ("white", "W"),
        ("yellow", "Y"),
        ("red", "R"),
        ("orange", "O"),
        ("blue", "B"),
        ("green", "G"),
    ]:
        img = generate_rubiks_test_image([code] * 9)
        path = samples_dir / f"{colour}_face.jpg"
        img.save(path, quality=85)
        print(f"✓ {path.name}")

    # Mixed solved cube (standard solved state)
    solved_sequence = (
        ["W"] * 9  # White face
        + ["B"] * 9  # Blue face
        + ["Y"] * 9  # Yellow face
        + ["G"] * 9  # Green face
        + ["O"] * 9  # Orange face
        + ["R"] * 9  # Red face
    )
    for idx, (colour, _code) in enumerate(
        [
            ("white", "W"),
            ("blue", "B"),
            ("yellow", "Y"),
            ("green", "G"),
            ("orange", "O"),
            ("red", "R"),
        ]
    ):
        img = generate_rubiks_test_image(solved_sequence[idx * 9 : (idx + 1) * 9])
        path = samples_dir / f"solved_{colour}_face.jpg"
        img.save(path, quality=85)
        print(f"✓ {path.name}")

    # Mixed/scrambled face (tests detection with multiple colours)
    mixed = ["W", "W", "W", "B", "W", "Y", "Y", "Y", "Y"]
    img = generate_rubiks_test_image(mixed)
    path = samples_dir / "mixed_face.jpg"
    img.save(path, quality=85)
    print(f"✓ {path.name}")

    print(
        f"\nGenerated {len(list(samples_dir.glob('*.jpg')))} test images in {samples_dir}"
    )


if __name__ == "__main__":
    main()
