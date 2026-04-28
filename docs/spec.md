# Rubiks Cube Scanner — Technical Specification

## System Overview

```
ESP32-CAM (ESPHome) ──► HA Integration ──► Kociemba Solver ──► ESP32 Robot (ESPHome)
     camera entity       cube state string    move sequence        motor control
                         [Phase 1 ✅]         [Phase 2 ✅]         [Phase 3]
```

---

## File Structure

```
custom_components/rubiks/
├── __init__.py           — integration setup, hass.data initialisation, platform list
├── manifest.json         — domain, requirements (Pillow>=10.0.0, kociemba>=1.0)
├── const.py              — DOMAIN, CUBE_COLORS, SCAN_SEQUENCE, SCAN_MOTION,
│                           SCAN_LOADING_HINT, COLOUR_EMOJI, crop keys, device info, paths
├── config_flow.py        — source selection (camera entity or sample image path)
├── cal_store.py          — CalibrationStore: persistent LAB anchor management
├── camera_processor.py   — CIELAB detection, calibration, image annotation,
│                           summary image generation, parity checks
├── solver.py             — kociemba sticker remapping, build_kociemba_faces(),
│                           kociemba_string(), solve()
├── button.py             — Scan Face, Preview Crop, Reset Scan,
│                           Save Calibration, Reset Calibration, Solve
├── image.py              — Last Scan, per-face images (W/Y/R/O/B/G), Scan Summary
├── number.py             — Crop Left/Top/Right/Bottom, LED Brightness
├── sensor.py             — Cube State, Current Face, Faces Scanned, Scan Warnings,
│                           Kociemba Input, Solution
├── text.py               — LED Entity ID
├── strings.json          — UI strings (source of truth for translations)
├── translations/
│   └── en.json
└── tests/
```

---

## Architecture Decisions

### CIELAB colour space, not HSV
HSV hue is unreliable on low-quality camera sensors. The OV2640 compresses a/b channels significantly (standard LAB values are far from what the camera reads). CIELAB with weighted distance separates cube colours more robustly and is calibratable from actual camera readings.

#### LAB distance weights
`L×1.5, a×2.0, b×2.0`

The L channel is weighted at 1.5 (not the intuitive 0.5 for "suppress brightness") because on this specific OV2640 unit, **Red and Orange are cleanly separated by lightness** — Red centres measure L≈28–35, Orange centres measure L≈55–65, with a gap of ~20 L units. Weighting L higher than a/b exploits this separation. If a different camera has Red and Orange at similar L values, this weight would need revisiting.

The a/b channels are weighted at 2.0 to amplify chroma differences (particularly the red/orange hue shift in the a channel).

#### Factory reference LAB values
Factory references are the starting point before any calibration is saved. They are camera-specific — these values are tuned for the OV2640 unit used during development. They represent the **centroid of all 9 stickers** for each colour (not just the brightest centre square), which places the decision boundary between colours at the true midpoint of each cluster.

| Colour | L | a | b | Notes |
|--------|---|---|---|-------|
| W | 90.0 | 0.0 | 5.0 | |
| Y | 78.0 | -8.0 | 55.0 | |
| R | 35.0 | 50.0 | 22.0 | Dark on this camera; centre ~L=33 |
| O | 62.0 | 47.0 | 27.0 | Centre ~L=62; corners can fall to L=43 |
| B | 35.0 | 5.0 | -30.0 | |
| G | 50.0 | -35.0 | 25.0 | |

**Why centroid-based, not centre-square-based:** The Red face spans L=16–40 and Orange L=43–66 on this camera. A factory reference at L=35 (Red centre only) places the L decision boundary at (35+62)/2=48.5 — too high, misclassifying dark Orange corners (L=43) as Red. A centroid reference at L=28 lowers the boundary to ~45, correctly separating them.

#### Unknown threshold
`_LAB_UNKNOWN_THRESHOLD = 80.0` — a sticker is labelled `?` only if its closest reference is more than 80 weighted units away. This was raised from 60 to accommodate dark Red cells (L≈16) whose distance to any reference is larger when L is weighted at 1.5.

### 5-point majority vote per cell
Each cell is sampled at the centre and 4 inner corners at **¼ cell width/height** offset from the centre. The 5 LAB readings are classified individually and the winner is taken by majority vote.

**Why majority vote, not median LAB:** Majority vote handles two distinct glare failure modes better than median LAB:
- *Brightening glare* (high L only): 1–2 points are blown out but still classify correctly via nearest-neighbour; majority overrules them.
- *Desaturating glare* (high L AND low a/b): a/b collapse toward the white/grey cluster. If 3+ points are affected, majority vote can fail too — but for 1–2 affected points, the unaffected points outvote them. Median LAB would average in the desaturated values, potentially misclassifying (e.g. a Red cell with b=−6 being mistaken for White).

The sample offset was initially set to ⅙ cell width/height to avoid edges entirely, then reverted to ¼ to give better spatial coverage and match the annotated dot positions the user relies on for crop alignment.

### Per-session calibration with persistent EMA
First-pass classification uses reference centroids (factory defaults or saved calibration). After all 6 faces are scanned, `calibrate_faces()` runs a two-round greedy constrained assignment (max 9 per colour, sorted by LAB distance) which enforces colour counts independently of the first-pass result. The refined centroids are:
- Blended into persistent storage via EMA (α=0.2) if parity is valid
- Available as a manual hard-commit via Save Calibration button

This means the integration gets more accurate with each successful session. After Save Calibration, the saved anchors reflect the **centroid of all 9 stickers per colour** (from round-2 anchor recomputation), not just the centre squares — so future scans classify borderline stickers (e.g. dark Orange corners) correctly at scan time.

#### Centre sticker locking
Centre stickers (cell index 4) are **pre-assigned before the greedy competition begins**. With loading-position enforcement, the centre of each face is ground truth — we know exactly which colour it is. Locking centres prevents a numerically close colour (e.g. Orange bidding against Red for the Red centre) from winning in round 1 and contaminating the anchor recomputation.

Without this lock, a single misassigned centre in round 1 shifts the refined anchor for that colour, potentially cascading into more errors in round 2.

#### Anchor recomputation between rounds
After round 1 assigns all 54 stickers, new anchors are computed as the **median LAB** of all stickers assigned to each colour. Median is used instead of mean because a contaminated round-1 cluster (containing 1 misassigned sticker from an adjacent colour) will have that outlier below the median — the median anchor is unaffected, while the mean would be dragged toward it.

### Loading position enforcement
The user loads the cube in a fixed canonical orientation: White facing camera, Blue at top, Orange on left. The scan sequence (W→B→Y→G→O→R) then deterministically assigns face labels by position (`SCAN_SEQUENCE[len(scanned_faces)]`) rather than by classifying the centre square.

This eliminates the Red/Orange ambiguity — since both faces are always scanned at a fixed sequence step, there is no classification decision to make for centre identification. A LAB sanity check still warns in the logs if the detected centre LAB is more than 20 units from the expected colour's reference, so orientation mistakes are surfaced early.

### Crop region as runtime number entities
Crop coordinates are four `number` entities rather than config-flow fields. The user tunes them live with dashboard sliders and presses Preview Crop to see the annotated result immediately — much tighter feedback than editing config and reloading.

### LED control in `_load_image`
The `_illuminate()` method is called inside `_load_image` which is used by both Scan Face and Preview Crop. Configuring LED entity ID and brightness via text/number entities (not config flow) follows the same pattern as crop — tunable at runtime without reloading.

**LED brightness and LAB values:** All absolute L values shift uniformly with LED brightness. Factory defaults and saved calibration anchors are only reliable at the brightness they were established at. If LED brightness changes significantly, Reset Calibration → rescan → Save Calibration is required to re-establish correct anchors.

### Kociemba sticker remapping in `solver.py`
Camera captures each face from a specific orientation. For each scan position, the camera-grid index must be mapped to the kociemba canonical face-position index before building the solver input string. Remapping is derived by comparing camera-top/left at each barrel-roll step against kociemba's canonical face orientations.

| Face | Remap | cam-top | cam-left | kociemba canon-top | kociemba canon-left | Match |
|------|-------|---------|----------|--------------------|---------------------|-------|
| W (U) | Identity | B | O (=L) | B-side | L | ✓ |
| B (B) | 180° | Y (=D) | O (=L) | U (=W) | R | both opposite |
| Y (D) | Identity | G (=F) | O (=L) | F-side | L | ✓ |
| G (F) | Identity | W (=U) | O (=L) | U | L | ✓ |
| O (L) | Identity | W (=U) | B (=B) | U | B | ✓ |
| R (R) | Identity | W (=U) | G (=F) | U | F | ✓ |

**Canon-left derivation** (each face viewed from outside):
- U: looking down with F toward viewer → left = L face
- R: standing right, looking left → F face is on viewer's left → left = F
- F: standing front → left = L face
- D: looking up with F toward viewer → left = L face
- L: standing left, looking right → B face is on viewer's left → left = B
- B: standing behind, looking forward → R face is on viewer's left → left = R

**Historical note:** The O (L) and R (R) faces were previously remapped with h-mirror (`[6,3,0,7,4,1,8,5,2]`), which caused all solver attempts to fail. The spec comment had L and R canon-lefts transposed — L was listed as canon-left=F and R as canon-left=B, the reverse of the correct values. Identity remap is correct for both.

### kociemba solved-cube behaviour
The installed kociemba library returns a non-trivial move sequence when given a fully solved cube string (`UUUUUUUUURRRRRRRRR...`). This is a library quirk — the expected return for a solved input is `""` (0 moves).

`solve()` short-circuits with `_is_solved()` before calling `kociemba.solve()`: if every 9-sticker face group is uniform, return `""` immediately. The button layer then displays "Already solved!" rather than an empty sensor.

---

## Shared Data (`hass.data[DOMAIN][entry_id]`)

| Key | Type | Description |
|-----|------|-------------|
| `scanned_faces` | `dict[str, list[str]]` | face_label → 9 colour codes (updated post-calibration) |
| `scanned_face_details` | `dict[str, list[dict]]` | face_label → per-square LAB/HSV detail (color field patched post-calibration) |
| `face_scans` | `dict[str, FaceScan]` | face_label → FaceScan dataclass |
| `face_annotated_images` | `dict[str, bytes]` | face_label → annotated JPEG bytes |
| `calibration_result` | `CalibrationResult \| None` | most recent calibration |
| `summary_image` | `bytes \| None` | 3×2 grid JPEG |
| `last_annotated_image` | `bytes \| None` | most recent scan or preview |
| `image_size` | `tuple[int, int] \| None` | (width, height) of last image |
| `scan_warnings` | `list[str]` | current plain-English warnings |
| `crop_entities` | `dict[str, CropNumberEntity]` | keyed by crop key |
| `led_brightness_entity` | `LedBrightnessEntity \| None` | |
| `led_entity_id_entity` | `LedEntityIdText \| None` | |
| `cal_store` | `CalibrationStore` | persistent LAB anchor store |
| `kociemba_faces` | `dict[str, list[str]] \| None` | kociemba face label (U/R/F/D/L/B) → 9 sticker values as face letters; built from `scanned_faces` + sticker remapping after calibration |
| `solution` | `str \| None` | last move sequence from kociemba solver |

---

## Colour Detection Pipeline

```
Image bytes / file path
    │
    ▼
PIL Image  (load_image_from_bytes / load_image_from_path)
    │
    ▼
Optional crop  (left, top, right, bottom from number entities)
    │
    ▼
3×3 grid division
    │
    ▼
Per cell (9 cells):
  ├─ 5 sample points: centre + 4 inner corners (¼ cell width/height offset)
  ├─ Each point: average small region → RGB → CIELAB
  ├─ Classify each point via nearest-neighbour LAB distance (L×1.5, a/b×2.0)
  │    (uses cal_store.get_references() — saved anchors override factory defaults)
  ├─ Majority vote → cell colour
  └─ Median LAB across 5 points → cell LAB reading (for logging/display only)
    │
    ▼
override_centre applied (face label from SCAN_SEQUENCE by position)
    │
    ▼
_annotate_image() — draws crop box, grid, sample dots, colour labels, LAB values
    │
    ▼
FaceScan(face_label, colors, hsv_readings, lab_readings, annotated_image)
```

---

## Calibration Pipeline

Runs after all 6 faces are scanned.

```
6 FaceScan objects
    │
    ▼
Build 6 anchors from centre squares (cell index 4)
    │
    ▼
Greedy constrained assignment (round 1):
  - Pre-assign all 6 centre stickers (locked — ground truth from loading position)
  - For every remaining (sticker, colour) pair: compute LAB distance to anchor
  - Sort all pairs by distance
  - Assign greedily, max 9 per colour
    │
    ▼
Recompute anchors from round-1 assignment (median LAB per colour cluster)
    │
    ▼
Second greedy pass with refined anchors (centres still locked)
    │
    ▼
Compute confidence margins (gap between 1st and 2nd closest centroid, normalised)
    │
    ▼
Flag low-confidence stickers (margin < 0.15)
    │
    ▼
check_cube_parity() — validate 9×6=54, 6 colours, exactly 9 each
    │
    ▼
CalibrationResult(calibrated_faces, anchors, confidence,
                  low_confidence, pre_calibration_changes,
                  parity_valid, parity_error)
    │
    ├─► scanned_faces updated with calibrated_faces
    ├─► scanned_face_details "color" fields patched to match
    ├─► centre mismatch check (warns if any face centre ≠ expected colour)
    ├─► diagnose_cube_string() run proactively — issues surfaced to scan_warnings
    ├─► If parity_valid: cal_store.ema_update(anchors)
    ├─► build_kociemba_faces(scanned_faces) → hass.data[kociemba_faces]
    └─► Fire rubiks_calibrated event
```

---

## Solver Pipeline

Runs when Solve button is pressed.

```
hass.data[kociemba_faces]  (dict[str, list[str]])
    │
    ▼
kociemba_string() — concatenate faces in URFDLB order → 54-char string
    │
    ▼
_is_solved() check — if all 6 face groups are uniform → return "" immediately
    │  (kociemba library returns wrong moves for solved input — short-circuit)
    ▼
kociemba.solve(cube_string)  via async_add_executor_job
    │
    ▼
solution string  (e.g. "U R2 F B R B2 R U2 L B L2 F U'")
  or "" → displayed as "Already solved!"
    │
    ├─► hass.data[solution]
    └─► Fire rubiks_solved event
```

---

## Scan Sequence & Camera-Top Mapping

Fixed canonical starting position: **White facing camera, Blue at top, Orange on left.**

| Step | Face | Motion | Camera-top | Camera-left | kociemba face |
|------|------|--------|------------|-------------|---------------|
| 1 | White | Load (starting position) | Blue | Orange | U |
| 2 | Blue | Tilt backward | Yellow | Orange | B |
| 3 | Yellow | Tilt backward | Green | Orange | D |
| 4 | Green | Tilt backward | White | Orange | F |
| 5 | Orange | Rotate left 90° | White | Blue | L |
| 6 | Red | Rotate 180° | White | Green | R |

The loading position (step 1) is a hard requirement. Steps 2–4 are three backward tilts; step 5 is a left rotation from the step-4 position; step 6 is a 180° rotation from the step-5 position.

---

## Validation Checks

| Check | When | Action |
|-------|------|--------|
| LAB centre vs expected colour | Each scan | Warning logged if distance > 20 units — check cube orientation |
| No colour > 9 across all scanned faces | After each scan | Warning in Scan Warnings sensor and logs |
| Each colour appears as centre exactly once | After face 6 | Warning if missing or unexpected |
| Centre sticker matches face label after calibration | After calibration | Warning if any centre was reassigned (Red/Orange confusion indicator) |
| Exactly 54 stickers, 6 colours, 9 each | After calibration | `parity_valid` / `parity_error` |
| Structural cube validity (edges, corners, opposite faces) | After calibration | `diagnose_cube_string()` — issues surfaced to scan_warnings |
| Low-confidence stickers | After calibration | Flagged in attributes, not blocking |
| Valid cube state | On Solve | kociemba.solve() raises if state is physically impossible |

---

## Events

| Event | Payload | Fired by |
|-------|---------|----------|
| `rubiks_face_scanned` | `{face, colors, warnings}` | ScanFaceButton |
| `rubiks_scan_rejected` | `{}` | ScanFaceButton (preview), PreviewCropButton |
| `rubiks_scan_reset` | `{}` | ResetScanButton |
| `rubiks_calibrated` | `{parity_valid, corrections, low_confidence, anchors_saved, kociemba_string}` | ScanFaceButton |
| `rubiks_solved` | `{solution, move_count, cube_string}` | SolveButton |
| `rubiks_calibration_saved` | `{anchors}` | SaveCalibrationButton |
| `rubiks_calibration_reset` | `{}` | ResetCalibrationButton |

---

## Cube State String Format

### Human-readable (Cube State sensor)
54 characters, 9 per face, in scan sequence order (`W B Y G O R`):

```
WWWWWWWWWBBBBBBBBBYYYYYYYYYYGGGGGGGGGOOOOOOOOORRRRRRRR
^^^^^^^^^
 White face, row by row, camera-left to camera-right
```

Each character: `W` `Y` `R` `O` `B` `G`

### Kociemba Input sensor
54 characters, 9 per face, in kociemba face order (`U R F D L B`), sticker values as face letters:

```
UUUUUUUUURRRRRRRRR FFFFFFFFF DDDDDDDDD LLLLLLLLL BBBBBBBBB
```

Each character: `U` `R` `F` `D` `L` `B`

Produced by `solver.kociemba_string(kociemba_faces)`.

---

## Red/Orange Separation — Camera-Specific Notes

Red and Orange are the hardest colours to separate because they are adjacent on the hue wheel and differ primarily in saturation and lightness rather than hue. On the OV2640 used during development:

| Colour | L range (face) | L range (centre) | a range |
|--------|---------------|------------------|---------|
| Red | 16–40 | 33–35 | 27–51 |
| Orange | 43–66 | 61–64 | 40–49 |

The L gap between the darkest Orange corner (L≈43) and the brightest Red corner (L≈40) is only ~3 units. With L×1.5 weighting, this is 4.5 weighted units — smaller than the a/b contributions, meaning a/b still matters for borderline cells.

**First-scan behaviour:** At scan time, the factory/saved references are centre-square-based (or centroid-based after Save Calibration). A dark Orange corner (L≈43) is correctly classified once anchors reflect the full-face centroid (R≈L28, O≈L55). If only centre-square anchors are saved (R≈L35, O≈L62), the decision boundary is at L≈48.5 and dark Orange corners may first-classify as Red. Calibration's two-round greedy corrects these: after round-1 anchor recomputation (which shifts R anchor to ~L30), round 2 correctly reassigns borderline Orange cells to Orange. After Save Calibration, anchors become centroid-based and scan-time classification improves.

**Glare on Red:** Red cells under direct LED illumination can develop very low b values (b≈−4) due to desaturation. Majority vote handles this correctly as long as fewer than 3 of the 5 sample points are glare-affected. If a single Red sticker has 3+ severely desaturated points, it may misclassify as White. Reducing LED brightness or adjusting crop to avoid direct reflection resolves this.
