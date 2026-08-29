# Cube Orientation & Camera Convention

## Status (2026-08-01)

**Settled this session:**
- Scan order and the Red/Orange identity at positions 4/5 — resolved mathematically from
  the Loading Position and Flip/Spin definitions (see "Scan Sequence" below), matching
  `SCAN_FACES` (`rubiks_solver.cpp`) and `SCAN_SEQUENCE` (`const.py`). This took several
  rounds of contradictory verbal "I can see it's X" reports before being settled by
  deriving physical cube state from first principles instead of eyeballing the camera
  image — Red/Orange is a documented visual-confusion pair on this camera.
- "Per-Face Raw Camera Orientation" table — Image LEFT/RIGHT were swapped for the R and O
  rows; corrected, and re-verified against the section's own stated inversion rule.
- Kociemba face mapping and the unfolded-net diagrams — reviewed line by line, confirmed
  against `solver.py`'s `COLOUR_TO_FACE`/`KOCIEMBA_FACE_ORDER`.
- "Rotation Required per Face" table — re-verified row by row from scratch using the
  actual PIL rotation formulas (not just cross-checked against the other tables); matches
  the deployed `FACE_SCAN_ROTATIONS` code.

**Still open — face rotations.** We agreed there's more to work through here specifically
before considering this settled; picking back up soon.

**Fixed — annotated image overlay was misaligned with the image it's drawn on, for every
rotated face.** `detect_face_colors()` rotates the cropped image *before* sampling the 3×3
grid, but `_annotate_image()` drew the grid/dots/labels — computed in that rotated frame —
directly onto the *original, unrotated* image, with no inverse-rotation applied. Fixed by
adding `_unrotate_point()` (`camera_processor.py`), which maps each sample point back to
the pre-rotation frame before drawing, using the same rotation angle (`total_pil_angle`)
sampling already used — verified with an empirical PIL round-trip test (sub-2px error
across 0°/90°/180°/270°/37°, i.e. just rounding, not a formula error). The individual
per-face images still show the raw, as-captured framing (deliberately, for sanity-checking
the overlay against the real camera frame) — only the overlay's *position* changed.

**Related, also done — scan summary image.** Changed from a plain 3×2 grid to the
cross/net layout used throughout this doc and `_cube_net()` in `sensor.py`
(`generate_summary_image()`, `camera_processor.py`), and each thumbnail is now rotated by
`FACE_SCAN_ROTATIONS` before compositing — the per-face images are deliberately raw/
as-captured (see above), which differs face to face, so stacking six of them unrotated
into one summary looked inconsistent (some upside-down relative to others). Also fixed a
regression from the first pass at this: rotating with `expand=True` swapped width/height
for the two 90°-rotated faces (O/R), stretching them when forced into the fixed-aspect
thumbnail box; switched to `expand=False` (matching `detect_face_colors()`) to keep the
canvas shape consistent across all six.

**Also fixed — diagram alignment in this doc.** The Kociemba net diagrams (both the simple
and fully-indexed versions) had `W`/`Y` indented to align with the wrong column (R's
column instead of G's) — physically wrong, since White's bottom edge touches Green's top
edge, not Red's. Corrected in both diagrams and verified programmatically.

## Loading Position

The user loads the cube in a fixed orientation before each scan, viewed from a front-top
angle, to support colour calibration:

```
White on top (U), Green facing robot front (F), Orange on left (L), Red on right (R)
Blue on back (B), Yellow on bottom (D)
```

## Camera

Top-down, fixed to the chassis — the cube moves (via Flip/Spin), the camera does not.
Since the arm returns to the same closed position for every capture, **the camera's frame is
identical for all six scans**: whatever physical direction is "image-top" for one scan is
image-top for all of them.

Two hardware-confirmed facts pin the whole frame:
- **image-top = whichever face is currently at Front** (confirmed on the White-face scan:
  raw image shows Green at top, and Green is Front at load)
- **image-left = physical Right side, image-right = physical Left side** (mount is inverted;
  confirmed on the White-face scan: raw image shows Red — the loaded Right face — at image-left,
  Orange — the loaded Left face — at image-right)

```
image direction   →   physical robot direction
image TOP         =   whatever is currently FRONT
image BOTTOM      =   whatever is currently BACK
image LEFT        =   whatever is currently RIGHT   ← inverted mount
image RIGHT       =   whatever is currently LEFT
```

## Scan Sequence

Six positions, 0-indexed — matching `scan_face_idx_` in `rubiks_solver.cpp` and the `Pos`
column below. **Note:** the Home Assistant status sensor is 1-indexed instead
(`"SCAN " + (scan_face_idx_ + 1)`), so position 4 shows there as "SCAN 5". Keep the two
straight when cross-referencing logs or conversation against this table — conflating them
was a real source of confusion during debugging.

Positions 0–3 are a barrel roll (three forward-tilt flips, same axis, Left/Right never
touched). Position 4 adds a turntable spin before its flip; position 5 is two more plain
flips.

**Flip**: Front→Bottom, Top→Front, Back→Top, Bottom→Back. Left/Right unchanged.
**Spin CW** (viewed from above): Front→Right→Back→Left→Front (each face moves to the next
slot in this cycle). Top/Bottom unchanged.

Position 4 = Red, position 5 = Orange — derived mathematically from the Loading Position and
the Flip/Spin rules above, tracing full cube state through each step (not by eye: Red/Orange
are a documented visual-confusion pair on this camera, see `REFERENCE_LAB` in
`camera_processor.py`). `SCAN_FACES` in `rubiks_solver.cpp` and `SCAN_SEQUENCE` in
`const.py` both read `{"W","B","Y","G","R","O"}` to match.

| Pos | Face (Top) | Front | Back | Left | Right | Motion from previous |
|-----|-----------|-------|------|------|-------|----------------------|
| 0   | W | Green  | Blue   | Orange | Red    | load |
| 1   | B | White  | Yellow | Orange | Red    | flip |
| 2   | Y | Blue   | Green  | Orange | Red    | flip |
| 3   | G | Yellow | White  | Orange | Red    | flip |
| 4   | R | Green  | Blue   | White  | Yellow | spin CW + flip |
| 5   | O | Blue   | Green  | White  | Yellow | flip + flip |

### Visualizing the Roll

Positions 0–3 are the *same* flip repeated, so Top/Front/Bottom/Back just cascade through
one shared cycle (each column's Top becomes the next column's Front, that Front becomes the
next Bottom, and so on) while Left/Right sit still:

```
          Pos 0   Pos 1   Pos 2   Pos 3
  Top:      W       B       Y       G
  Front:    G       W       B       Y
  Bottom:   Y       G       W       B
  Back:     B       Y       G       W

  Left = Orange, Right = Red — unchanged through all four positions
```

Position 4 breaks the cycle with a spin before its flip, and position 5 keeps flipping —
Left/Right change here, so they're shown as small unfolded nets instead (same L-F-R-B
layout as the Kociemba net below, but physical cube directions, not image directions):

```
Position 4 (spin CW + flip):     Position 5 (flip × 2):

        R                                O
   W    G    Y    B                 W    B    Y    G
        O                                R
```

## Per-Face Raw Camera Orientation

Derived directly from the table above via `image-top=Front`, `image-left=Right`,
`image-bottom=Back`, `image-right=Left`:

| Face | Image TOP | Image LEFT | Image RIGHT | Image BOTTOM |
|------|-----------|------------|-------------|--------------|
| W    | G (Green)  | R (Red)    | O (Orange) | B (Blue)   |
| B    | W (White)  | R (Red)    | O (Orange) | Y (Yellow) |
| Y    | B (Blue)   | R (Red)    | O (Orange) | G (Green)  |
| G    | Y (Yellow) | R (Red)    | O (Orange) | W (White)  |
| R    | G (Green)  | Y (Yellow) | W (White)  | B (Blue)   |
| O    | B (Blue)   | Y (Yellow) | W (White)  | G (Green)  |

Faces 0–3 share the same left/right adjacency (Orange/Red fixed through the barrel roll).
Faces 4–5 differ because the cube was spun 90° before the flip — note R and O each land on
the *same* image-top colour as one of the barrel-roll faces (R↔W both see Green top; O↔Y
both see Blue top), which is the expected symmetry of spinning onto a second axis.

## Kociemba Face Mapping

Independent of the robot/scan-order bug — purely kociemba's own convention crossed with
solved-cube geometry:

**Kociemba order (`U R F D L B`) in colours: `W R G Y O B`**

Unfolded net (U top, D bottom, middle row L F R B — the same cycle as Spin CW, just
starting from L):

```
   W
O  G  R  B
   Y
```

| Colour | Kociemba face | Canonical top | Canonical left |
|--------|---------------|---------------|----------------|
| W      | U             | B (Blue)      | O (Orange/L)   |
| R      | R             | W (White/U)   | G (Green/F)    |
| G      | F             | W (White/U)   | O (Orange/L)   |
| Y      | D             | G (Green/F)   | O (Orange/L)   |
| O      | L             | W (White/U)   | B (Blue/B)     |
| B      | B             | W (White/U)   | R (Red/R)      |

Same net with full facelet indexing (0–8 per face, row-major top-left to bottom-right in
each face's own canonical orientation) — matches the indices used by `_EDGE_POSITIONS` /
`_CORNER_POSITIONS` in `solver.py`:

```
                W0  W1  W2
                W3  W4  W5
                W6  W7  W8

O0  O1  O2      G0  G1  G2      R0  R1  R2      B0  B1  B2
O3  O4  O5      G3  G4  G5      R3  R4  R5      B3  B4  B5
O6  O7  O8      G6  G7  G8      R6  R7  R8      B6  B7  B8

                Y0  Y1  Y2
                Y3  Y4  Y5
                Y6  Y7  Y8
```

## Rotation Required per Face (raw → kociemba order)

| Face | Raw top | Kociemba top | Raw left | Kociemba left | Rotation needed |
|------|---------|--------------|----------|---------------|-----------------|
| W    | G       | B            | R        | O             | **180°**        |
| B    | W       | W ✓          | R        | R ✓           | **identity**    |
| Y    | B       | G            | R        | O             | **180°**        |
| G    | Y       | W            | R        | O             | **180°**        |
| R    | G       | W            | Y        | G             | **90° CCW**     |
| O    | B       | W            | Y        | B             | **90° CCW**     |

Matches deployed `FACE_SCAN_ROTATIONS` (below) — a good independent check.

**Note:** R/O were originally `-90°` (CW); corrected to `+90°` (CCW) 2026-07-26. A
direction fix, unrelated to the R/O identity question above — same 90° magnitude either
way.

## Code Implementation

`FACE_SCAN_ROTATIONS` (`camera_processor.py`) rotates the cropped image before sticker
detection — the only orientation-correction layer (PIL: positive = CCW):

```python
FACE_SCAN_ROTATIONS: dict[str, float] = {
    "W":  180,
    "B":    0,
    "Y":  180,
    "G":  180,
    "O":   90,
    "R":   90,
}
```

`ROBOT_CAMERA_TO_KOCIEMBA_REMAP` (`solver.py`) is identity for all six faces — rotation
alone handles it, no index permutation needed.

## Original CUBOTino Reference

Our Flip/Spin definitions (above) are unchanged from CUBOTino's `Cubotino_moves.py`,
written here as continuous cycles:

- **Flip** (front→bottom): F→D→B→U→F
- **Spin CW**: F→R→B→L→F
- **Spin CCW**: F→L→B→R→F

Original CUBOTino scanned via a separate PC webcam — the ESP32 only ran servos + UART.
We ported scanning onto the ESP32-CAM itself.

Starting orientation: CUBOTino's "Front facing viewer, Upper up" = our Green-front,
White-up.
