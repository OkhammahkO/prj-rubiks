"""Kociemba sticker remapping and cube solver."""

from __future__ import annotations

import logging
from collections import Counter

_LOGGER = logging.getLogger(__name__)

# Maps each cube colour code to its kociemba face label
COLOUR_TO_FACE: dict[str, str] = {
    "W": "U",
    "Y": "D",
    "G": "F",
    "B": "B",
    "O": "L",
    "R": "R",
}

# Maps each sticker colour code to the kociemba sticker letter used in the solve string.
# Identical to COLOUR_TO_FACE — a sticker's letter is the face label of its colour's centre.
COLOUR_TO_STICKER = COLOUR_TO_FACE

# kociemba face output order
KOCIEMBA_FACE_ORDER = ["U", "R", "F", "D", "L", "B"]

# For each scanned colour (camera face), the permutation that maps camera grid index →
# kociemba face index. Camera grid is row-major, top-to-bottom, left-to-right from the
# camera's viewpoint. kociemba face index is row-major top-to-bottom, left-to-right
# when looking at that face from outside with its canonical "up" direction.
#
# Derivation from scan sequence (barrel-roll, starting White-facing-camera, Blue at top):
#
#   Cube state at each step (Front, Top, Bottom, Back, Left, Right):
#   1 W: F=W T=B  Bo=G Ba=Y L=O R=R  → cam-top=B,  cam-left=O (=L) → identity
#   2 B: F=B T=Y  Bo=W Ba=G L=O R=R  → cam-top=D,  cam-left=O (=L)
#        kociemba B: canon-top=U, canon-left=R → both flipped → 180°
#   3 Y: F=Y T=G  Bo=B Ba=W L=O R=R  → cam-top=F,  cam-left=O (=L) → identity
#   4 G: F=G T=W  Bo=Y Ba=B L=O R=R  → cam-top=U,  cam-left=O (=L) → identity
#   5 O: F=O T=W  Bo=Y Ba=R L=B R=G  → cam-top=U,  cam-left=B (=B)
#        kociemba L: canon-top=U, canon-left=B → identical → identity
#   6 R: F=R T=W  Bo=Y Ba=O L=G R=B  → cam-top=U,  cam-left=G (=F)
#        kociemba R: canon-top=U, canon-left=F → identical → identity
#
# Canon-left derivation (from corner position table — each face viewed from outside):
#   U: top=B side, left=L  (looking down, F toward viewer)
#   R: top=U,     left=F   (standing right, looking left — F face is on viewer's left)
#   F: top=U,     left=L   (standing front)
#   D: top=F side, left=L  (looking up, F toward viewer)
#   L: top=U,     left=B   (standing left, looking right — B face is on viewer's left)
#   B: top=U,     left=R   (standing behind, looking forward — R face is on viewer's left)
#
# Transforms as index permutations on a 3×3 grid (0–8, row-major):
#   identity:      [0, 1, 2, 3, 4, 5, 6, 7, 8]
#   180° rotation: [8, 7, 6, 5, 4, 3, 2, 1, 0]
CAMERA_TO_KOCIEMBA_REMAP: dict[str, list[int]] = {
    "W": [0, 1, 2, 3, 4, 5, 6, 7, 8],
    "B": [8, 7, 6, 5, 4, 3, 2, 1, 0],
    "Y": [0, 1, 2, 3, 4, 5, 6, 7, 8],
    "G": [0, 1, 2, 3, 4, 5, 6, 7, 8],
    "O": [0, 1, 2, 3, 4, 5, 6, 7, 8],
    "R": [0, 1, 2, 3, 4, 5, 6, 7, 8],
}

# Edge positions: each entry is (face1, index1, face2, index2).
# Both positions belong to the same physical edge piece.
_EDGE_POSITIONS: list[tuple[str, int, str, int]] = [
    ("U", 7, "F", 1), ("U", 5, "R", 1), ("U", 1, "B", 1), ("U", 3, "L", 1),
    ("D", 1, "F", 7), ("D", 5, "R", 7), ("D", 7, "B", 7), ("D", 3, "L", 7),
    ("F", 5, "R", 3), ("F", 3, "L", 5), ("B", 3, "R", 5), ("B", 5, "L", 3),
]

# Corner positions: each entry is (face1, index1, face2, index2, face3, index3).
_CORNER_POSITIONS: list[tuple[str, int, str, int, str, int]] = [
    ("U", 8, "F", 2, "R", 0), ("U", 6, "F", 0, "L", 2),
    ("U", 2, "B", 0, "R", 2), ("U", 0, "B", 2, "L", 0),
    ("D", 2, "F", 8, "R", 6), ("D", 0, "F", 6, "L", 8),
    ("D", 8, "B", 6, "R", 8), ("D", 6, "B", 8, "L", 6),
]

# Pairs of opposite faces — no edge or corner can contain both.
_OPPOSITE_PAIRS: frozenset[frozenset[str]] = frozenset([
    frozenset(["U", "D"]),
    frozenset(["F", "B"]),
    frozenset(["L", "R"]),
])


def build_kociemba_faces(
    scanned_faces: dict[str, list[str]],
) -> dict[str, list[str]] | None:
    """Convert camera-ordered scanned faces to kociemba face format.

    Returns a dict keyed by kociemba face label (U/R/F/D/L/B) with sticker values
    as kociemba face letters, or None if any face is missing, wrong length, or
    contains unclassified squares.
    """
    if len(scanned_faces) != 6:
        return None

    kociemba_faces: dict[str, list[str]] = {}

    for colour, camera_stickers in scanned_faces.items():
        if len(camera_stickers) != 9 or "?" in camera_stickers:
            return None

        face_label = COLOUR_TO_FACE.get(colour)
        remap = CAMERA_TO_KOCIEMBA_REMAP.get(colour)
        if face_label is None or remap is None:
            _LOGGER.warning("Unknown colour code in scanned_faces: %s", colour)
            return None

        kociemba_stickers: list[str] = ["?"] * 9
        for camera_idx, kociemba_idx in enumerate(remap):
            kociemba_stickers[kociemba_idx] = COLOUR_TO_STICKER.get(
                camera_stickers[camera_idx], "?"
            )

        kociemba_faces[face_label] = kociemba_stickers

    return kociemba_faces


def kociemba_string(kociemba_faces: dict[str, list[str]]) -> str | None:
    """Build the 54-character kociemba input string from the remapped face dict."""
    if not kociemba_faces or len(kociemba_faces) != 6:
        return None
    try:
        return "".join("".join(kociemba_faces[face]) for face in KOCIEMBA_FACE_ORDER)
    except KeyError:
        return None


def diagnose_cube_string(cube_string: str) -> list[str]:
    """Analyse a kociemba cube string and return plain-English descriptions of why it is invalid.

    Checks:
    - Correct length and character set
    - Centre squares match their face
    - No edge or corner piece contains stickers from opposite faces
    - No edge piece appears in more than one position
    - No corner piece appears in more than one position
    """
    issues: list[str] = []

    if len(cube_string) != 54:
        issues.append(f"Expected 54 characters, got {len(cube_string)}")
        return issues

    valid_letters = set(KOCIEMBA_FACE_ORDER)
    if not all(c in valid_letters for c in cube_string):
        issues.append(f"Unexpected characters: {set(cube_string) - valid_letters}")
        return issues

    faces: dict[str, str] = {
        face: cube_string[i * 9 : (i + 1) * 9]
        for i, face in enumerate(KOCIEMBA_FACE_ORDER)
    }

    # Centre squares
    for face, stickers in faces.items():
        if stickers[4] != face:
            issues.append(
                f"{face} face centre is '{stickers[4]}', expected '{face}'"
            )

    # Colour counts
    counts = Counter(cube_string)
    for face in KOCIEMBA_FACE_ORDER:
        if counts[face] != 9:
            issues.append(f"'{face}' sticker count is {counts[face]}, expected 9")

    # Edge piece analysis
    edge_pieces: dict[frozenset[str], list[str]] = {}
    for f1, i1, f2, i2 in _EDGE_POSITIONS:
        s1, s2 = faces[f1][i1], faces[f2][i2]
        piece = frozenset([s1, s2])
        slot = f"{f1}[{i1}]/{f2}[{i2}]"
        if piece in _OPPOSITE_PAIRS:
            issues.append(
                f"Impossible edge at {slot}: '{s1}' and '{s2}' are opposite faces"
            )
        elif len(piece) == 1:
            issues.append(
                f"Impossible edge at {slot}: both stickers are '{s1}' (same face)"
            )
        edge_pieces.setdefault(piece, []).append(slot)

    for piece, slots in edge_pieces.items():
        if len(slots) > 1:
            issues.append(
                f"Edge piece {{{','.join(sorted(piece))}}} appears {len(slots)} times "
                f"(at {', '.join(slots)}) — one or more stickers misclassified"
            )

    expected_edges = {frozenset(p) for p in [
        ("U","F"),("U","R"),("U","B"),("U","L"),
        ("D","F"),("D","R"),("D","B"),("D","L"),
        ("F","R"),("F","L"),("B","R"),("B","L"),
    ]}
    missing_edges = expected_edges - set(edge_pieces.keys())
    if missing_edges:
        for piece in missing_edges:
            issues.append(
                f"Edge piece {{{','.join(sorted(piece))}}} is missing from the cube"
            )

    # Corner piece analysis
    corner_pieces: dict[frozenset[str], list[str]] = {}
    for f1, i1, f2, i2, f3, i3 in _CORNER_POSITIONS:
        s1, s2, s3 = faces[f1][i1], faces[f2][i2], faces[f3][i3]
        piece = frozenset([s1, s2, s3])
        slot = f"{f1}[{i1}]/{f2}[{i2}]/{f3}[{i3}]"
        stickers = [s1, s2, s3]
        if len(piece) < 3:
            dupes = [s for s, n in Counter(stickers).items() if n > 1]
            issues.append(
                f"Impossible corner at {slot}: '{dupes[0]}' sticker appears twice"
            )
        else:
            for pair in [frozenset([s1, s2]), frozenset([s1, s3]), frozenset([s2, s3])]:
                if pair in _OPPOSITE_PAIRS:
                    issues.append(
                        f"Impossible corner at {slot}: contains opposite-face stickers "
                        f"{{{','.join(sorted(pair))}}}"
                    )
                    break
        corner_pieces.setdefault(piece, []).append(slot)

    for piece, slots in corner_pieces.items():
        if len(slots) > 1:
            issues.append(
                f"Corner piece {{{','.join(sorted(piece))}}} appears {len(slots)} times "
                f"(at {', '.join(slots)}) — one or more stickers misclassified"
            )

    return issues


def _is_solved(cube_string: str) -> bool:
    """Return True if every face has 9 identical stickers (= solved cube)."""
    if len(cube_string) != 54:
        return False
    return all(len(set(cube_string[i * 9 : (i + 1) * 9])) == 1 for i in range(6))


def solve(cube_string: str) -> str | None:
    """Run the kociemba two-phase solver and return the move sequence string.

    Runs synchronously — call via async_add_executor_job.
    Returns None on failure (import error or invalid cube state).
    """
    # kociemba has a bug where it returns non-trivial moves for an already-solved cube.
    if _is_solved(cube_string):
        return ""
    try:
        import kociemba  # noqa: PLC0415
    except ImportError:
        _LOGGER.error("kociemba library not installed — add it to manifest requirements")
        return None
    try:
        return kociemba.solve(cube_string)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("kociemba solver failed: %s | cube string: %s", err, cube_string)
        issues = diagnose_cube_string(cube_string)
        if issues:
            _LOGGER.error(
                "Cube state diagnosis (%d issue%s):\n  %s",
                len(issues),
                "s" if len(issues) != 1 else "",
                "\n  ".join(issues),
            )
        else:
            _LOGGER.error(
                "Cube state passes structural checks — likely an orientation parity violation"
            )
        return None
