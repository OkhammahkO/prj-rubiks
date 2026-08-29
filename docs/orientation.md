# Cube Orientation & Camera Convention

## Loading Position

The user loads the cube in a fixed orientation before each scan:

```
White on top (U), Green facing robot front (F), Orange on left (L), Red on right (R)
Blue on back (B), Yellow on bottom (D)
```

## Camera

Top-down, fixed to the chassis — the cube moves (via Flip/Spin), the camera does not.
Since the arm returns to the same closed position for every capture, the camera's frame
is identical for all six scans.

```
image direction   →   physical robot direction
image TOP         =   whatever is currently FRONT
image BOTTOM      =   whatever is currently BACK
image LEFT        =   whatever is currently RIGHT   ← inverted mount
image RIGHT       =   whatever is currently LEFT
```

## Scan Sequence

Six positions, 0-indexed, matching `scan_face_idx_` in `rubiks_solver.cpp` and
`SCAN_SEQUENCE` in `const.py` (one shared list for both the manual button and the robot
service schema). The HA status sensor is 1-indexed (`"SCAN " + (scan_face_idx_ + 1)`).

**Flip**: Front→Bottom, Top→Front, Back→Top, Bottom→Back. Left/Right unchanged.
**Spin CW** (viewed from above): Front→Right→Back→Left→Front. Top/Bottom unchanged.

| Pos | Face (Top) | Front | Back | Left | Right | Motion from previous |
|-----|-----------|-------|------|------|-------|----------------------|
| 0   | W | Green  | Blue   | Orange | Red    | load |
| 1   | B | White  | Yellow | Orange | Red    | flip |
| 2   | Y | Blue   | Green  | Orange | Red    | flip |
| 3   | G | Yellow | White  | Orange | Red    | flip |
| 4   | R | Green  | Blue   | White  | Yellow | spin CW + flip |
| 5   | O | Blue   | Green  | White  | Yellow | flip + flip |

Positions 0–3 are a barrel roll (Left/Right untouched). Position 4 adds a turntable
spin before its flip; position 5 is two more plain flips.

Red/Orange at positions 4/5 is a documented visual-confusion pair on this camera (see
`REFERENCE_LAB` in `camera_processor.py`) — this order was derived from first-principles
state tracing, not by eye, and should not be re-flipped without an objective check (e.g.
comparing a logged LAB reading against `REFERENCE_LAB["R"]` vs `["O"]` distance).

## Per-Face Raw Camera Orientation

Derived from the table above via `image-top=Front`, `image-left=Right`,
`image-bottom=Back`, `image-right=Left`:

| Face | Image TOP | Image LEFT | Image RIGHT | Image BOTTOM |
|------|-----------|------------|-------------|---------------|
| W    | G | R | O | B |
| B    | W | R | O | Y |
| Y    | B | R | O | G |
| G    | Y | R | O | W |
| R    | G | Y | W | B |
| O    | B | Y | W | G |

Faces 0–3 share the same left/right adjacency (Orange/Red fixed through the barrel
roll). Faces 4–5 differ because the cube was spun 90° before the flip.

## Kociemba Face Mapping

Independent of the scan-order question — purely kociemba's own convention crossed with
solved-cube geometry.

**Kociemba order (`U R F D L B`) in colours: `W R G Y O B`**

```
   W
O  G  R  B
   Y
```

| Colour | Kociemba face | Canonical top | Canonical left |
|--------|---------------|---------------|----------------|
| W      | U             | B             | O |
| R      | R             | W             | G |
| G      | F             | W             | O |
| Y      | D             | G             | O |
| O      | L             | W             | B |
| B      | B             | W             | R |

## Rotation Required per Face (raw → kociemba order)

| Face | Raw top | Kociemba top | Raw left | Kociemba left | Rotation needed |
|------|---------|--------------|----------|---------------|-----------------|
| W    | G       | B            | R        | O             | 180°        |
| B    | W       | W ✓          | R        | R ✓           | identity    |
| Y    | B       | G            | R        | O             | 180°        |
| G    | Y       | W            | R        | O             | 180°        |
| R    | G       | W            | Y        | G             | 90° CCW     |
| O    | B       | W            | Y        | B             | 90° CCW     |

Matches deployed `FACE_SCAN_ROTATIONS` — a good independent check.

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

Flip/Spin definitions match CUBOTino's `Cubotino_moves.py`, written here as continuous
cycles:

- **Flip** (front→bottom): F→D→B→U→F
- **Spin CW**: F→R→B→L→F
- **Spin CCW**: F→L→B→R→F

Original CUBOTino scanned via a separate PC webcam; this project scans on the ESP32-CAM
itself. Starting orientation: CUBOTino's "Front facing viewer, Upper up" = this
project's Green-front, White-up.
