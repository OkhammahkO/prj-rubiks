# Rubiks Cube Scanner — Technical Specification

## System Overview

```
ESP32-CAM (ESPHome) ──► HA Integration ──► Kociemba Solver ──► ESP32 Robot (ESPHome)
     camera entity       cube state string    move sequence        motor control
```

Camera scanning and cube-state detection can run standalone (Phase 1/2, manual/webcam
workflow) or driven by the robot (Phase 3, `docs/robot.md`). Both share the same
`SCAN_SEQUENCE` and colour-detection pipeline.

## File Structure

```
custom_components/rubiks/
├── __init__.py           — integration setup, hass.data initialisation, platform list
├── manifest.json         — domain, requirements (Pillow, kociemba)
├── const.py              — DOMAIN, CUBE_COLORS, SCAN_SEQUENCE, SCAN_MOTION,
│                           SCAN_LOADING_HINT, COLOUR_EMOJI, crop keys, device info
├── config_flow.py        — source selection (camera entity or sample image path)
├── cal_store.py          — CalibrationStore: persistent LAB anchor management
├── camera_processor.py   — CIELAB detection, calibration, image annotation,
│                           summary image generation, parity checks
├── solver.py             — kociemba sticker remapping, build_kociemba_faces(),
│                           kociemba_string(), solve()
├── button.py             — Scan Face, Preview Crop, Reset Scan, Save/Reset Calibration,
│                           Solve, Robot Start Scan/Stop/Abort/Advance Face
├── image.py               — Last Scan, per-face images, Scan Summary
├── number.py              — Crop Left/Top/Right/Bottom, Crop Rotation, LED Brightness,
│                           LED Stabilise Delay
├── text.py                — LED entity ID override
├── sensor.py               — Cube State, Current Face, Faces Scanned, Scan Warnings,
│                           Kociemba Input, Solution
├── strings.json / translations/en.json
└── tests/                  — CIELAB, detection, calibration, sticker remap, kociemba logic
```

## Architecture Decisions

**CIELAB, not HSV.** HSV hue is unreliable on this camera sensor; CIELAB with weighted
distance (`L×1.5, a×2.0, b×2.0`) separates cube colours more robustly. L is weighted
*above* a/b — unusual, but on this specific OV2640 unit Red and Orange are cleanly
separated by lightness (Red centres ≈L28-35, Orange ≈L55-65) more reliably than by
chroma. A different camera might not have this separation and would need revisiting.

**Factory reference LAB values** are centroids of all 9 stickers per colour (not just
centre squares), camera-specific, tuned for the development unit:

| Colour | L | a | b |
|--------|---|---|---|
| W | 66.0 | 16.0 | -15.0 |
| Y | 74.0 | -1.0 | 26.0 |
| R | 35.0 | 50.0 | 22.0 |
| O | 62.0 | 47.0 | 27.0 |
| B | 32.0 | 33.0 | -51.0 |
| G | 45.0 | -15.0 | 14.0 |

Unknown threshold: `_LAB_UNKNOWN_THRESHOLD = 80.0` (weighted units).

**5-point majority vote per cell** (centre + 4 inner corners at ¼ cell offset). Majority
vote tolerates 1-2 glare-affected points outvoting correctly; median LAB would instead
average a desaturated point into the result, risking misclassification.

**Per-session calibration with persistent EMA.** After all 6 faces scan,
`calibrate_faces()` runs a two-round greedy constrained assignment (max 9 per colour) to
refine anchors, blended into persistent storage via EMA (α=0.2) if parity is valid, or
hard-committed via Save Calibration. Centre stickers are locked (pre-assigned before the
greedy competition) since loading-position enforcement makes them ground truth — this
prevents a close competing colour from contaminating round-1 anchor recomputation.
Round-2 anchors use median LAB per cluster (not mean), so a single misassigned outlier
from round 1 doesn't drag the anchor toward it.

**Loading position enforcement.** Face labels are assigned by scan position
(`SCAN_SEQUENCE[len(scanned_faces)]`), not by classifying the centre square — this
eliminates Red/Orange centre-identification ambiguity entirely. A LAB sanity check still
warns if a detected centre is >20 units from its expected reference.

**Crop region and LED brightness as runtime number entities**, not config-flow fields —
tunable live via dashboard sliders with Preview Crop for immediate feedback.

**LED brightness and LAB values**: all absolute L values shift with LED brightness.
Changing brightness significantly requires Reset Calibration → rescan → Save
Calibration to re-establish anchors.

**Kociemba sticker remapping** (`solver.py`) maps each scan position's camera-grid index
to kociemba's canonical face-position index:

| Face | Remap | kociemba canon-top | kociemba canon-left |
|------|-------|--------------------|---------------------|
| W (U) | Identity | B-side | L |
| B (B) | 180° | U (=W) | R |
| Y (D) | Identity | F-side | L |
| G (F) | Identity | U | L |
| O (L) | Identity | U | B |
| R (R) | Identity | U | F |

**Phase 3 (robot) key decisions** — full detail in `docs/robot.md` and
`docs/collision-prevention.md`:
- Kociemba runs in HA, not on the ESP32 (two-phase pruning tables need 10-20MB RAM).
- Servo step queue is non-blocking, pre-planned into `std::vector<ServoStep>`, drained
  one entry per `loop()` tick.
- Raw MicroPython PWM duty (0-1023, from `Cubotino_settings.txt`) converts to ESPHome's
  -1.0..1.0 via `duty_to_esphome()` in C++ only.

**kociemba solved-cube quirk**: the library returns a non-trivial move sequence for an
already-solved cube string. `solve()` short-circuits with `_is_solved()` before calling
`kociemba.solve()`.

## Shared Data (`hass.data[DOMAIN][entry_id]`)

| Key | Type | Description |
|-----|------|--------------|
| `scanned_faces` | `dict[str, list[str]]` | face_label → 9 colour codes |
| `scanned_face_details` | `dict[str, list[dict]]` | per-square LAB/HSV detail |
| `face_scans` | `dict[str, FaceScan]` | dataclass per face |
| `face_annotated_images` | `dict[str, bytes]` | per-face annotated JPEG |
| `calibration_result` | `CalibrationResult \| None` | most recent calibration |
| `summary_image` | `bytes \| None` | cross-net-layout JPEG (see `_SUMMARY_NET_POSITIONS`) |
| `last_annotated_image` | `bytes \| None` | most recent scan or preview |
| `scan_warnings` | `list[str]` | current plain-English warnings |
| `cal_store` | `CalibrationStore` | persistent LAB anchor store |
| `kociemba_faces` | `dict[str, list[str]] \| None` | built from `scanned_faces` after calibration |
| `solution` | `str \| None` | last move sequence from kociemba solver |

## Pipelines

**Colour detection**: image → optional crop → 3×3 grid → per-cell 5-point CIELAB
classification + majority vote → `override_centre` (loading-position label) →
`_annotate_image()` → `FaceScan`.

**Calibration** (after 6th face): build anchors from centres → greedy round 1 (centres
locked) → recompute anchors (median) → greedy round 2 → confidence margins → flag
low-confidence (<0.15 margin) → `check_cube_parity()` → `CalibrationResult` → EMA update
if valid → `build_kociemba_faces()` → fire `rubiks_calibrated`.

**Solver** (Solve button): `kociemba_string()` → `_is_solved()` short-circuit →
`kociemba.solve()` via executor job → solution string or `""` ("Already solved!") →
fire `rubiks_solved`.

## Scan Sequence (Phase 1/2 manual/webcam)

Loading position: **White facing camera, Blue at top, Orange on left.**

| Step | Face | Motion | Camera-top | Camera-left | kociemba face |
|------|------|--------|------------|-------------|---------------|
| 1 | White | Load | Blue | Orange | U |
| 2 | Blue | Tilt backward | Yellow | Orange | B |
| 3 | Yellow | Tilt backward | Green | Orange | D |
| 4 | Green | Tilt backward | White | Orange | F |
| 5 | Red | Rotate left 90° | White | Blue | R |
| 6 | Orange | Rotate 180° | White | Green | L |

Matches `SCAN_SEQUENCE = ["W","B","Y","G","R","O"]` and `SCAN_MOTION` in `const.py` —
the same list the robot service schema validates against.

## Validation Checks

| Check | When | Action |
|-------|------|--------|
| LAB centre vs expected colour | Each scan | Warning if distance > 20 units |
| No colour > 9 across scanned faces | After each scan | Warning |
| Each colour appears as centre once | After face 6 | Warning if missing/unexpected |
| Centre sticker matches face label | After calibration | Warning (Red/Orange confusion indicator) |
| Exactly 54 stickers, 6×9 | After calibration | `parity_valid`/`parity_error` |
| Structural cube validity | After calibration | `diagnose_cube_string()` |
| Low-confidence stickers | After calibration | Flagged, not blocking |
| Valid cube state | On Solve | `kociemba.solve()` raises if impossible |

## Services

| Service | Description | Returns |
|---------|-------------|---------|
| `rubiks.robot_scan_face` | Illuminate → capture → detect → store for one face | — |
| `rubiks.solve` | Run kociemba solver against stored face scans | `{solution, move_count, cube_string}` or `{error}` |

## Events

| Event | Payload | Fired by |
|-------|---------|----------|
| `rubiks_face_scanned` | `{face, colors, warnings}` | ScanFaceButton |
| `rubiks_scan_rejected` | `{}` | ScanFaceButton (preview), PreviewCropButton |
| `rubiks_scan_reset` | `{}` | ResetScanButton, RobotStartScanButton, RobotAbortButton |
| `rubiks_calibrated` | `{parity_valid, corrections, low_confidence, anchors_saved, kociemba_string}` | ScanFaceButton |
| `rubiks_solved` | `{solution, move_count, cube_string}` | SolveButton, `rubiks.solve` |
| `rubiks_calibration_saved` / `rubiks_calibration_reset` | — | Save/Reset Calibration buttons |
| `rubiks_robot_start_requested` / `_stop_requested` / `_advance_face_requested` | `{}` | Robot buttons |

## Cube State String Formats

**Human-readable** (Cube State sensor): 54 chars, scan order (`W B Y G R O`), letters
`W Y R O B G`.

**Kociemba Input sensor**: 54 chars, kociemba face order (`U R F D L B`), letters
`U R F D L B`. Produced by `solver.kociemba_string(kociemba_faces)`.

## Red/Orange Separation — Camera-Specific Notes

Hardest pair to separate (adjacent hue, differ mainly in lightness/saturation). On this
camera: Red L range 16-40 (centre 33-35), Orange L range 43-66 (centre 61-64) — only a
~3-unit gap between the darkest Orange corner and brightest Red corner, so a/b still
matters for borderline cells even with L weighted higher.

Centroid-based anchors (post-calibration) classify borderline dark-Orange corners
correctly; centre-square-only anchors place the decision boundary too high and risk
misclassifying them as Red on the first scan, before calibration's two-round greedy
corrects it.

Glare on Red can desaturate b toward White's range; majority vote tolerates this unless
3+ of the 5 sample points are affected.
