# Rubiks Cube Scanner — Feature Tracking

## Phase 1 — Cube State Detection ✅

Goal: reliably scan all 6 faces and produce a valid 54-character cube state string.

### Complete

**Detection**
- [x] CIELAB colour space classification (replaced HSV entirely)
- [x] Weighted LAB distance (`L×1.5`, `a/b×2.0`) — L weighted for Red/Orange lightness separation
- [x] 5-point majority vote per cell (centre + 4 inner corners) — robust against glare
- [x] Median LAB across sample points — resistant to single-point noise

**Loading position enforcement**
- [x] Fixed scan sequence: White → Blue → Yellow → Green → Orange → Red
- [x] Face label assigned from sequence position (`SCAN_SEQUENCE[len(scanned_faces)]`), not centre classification
- [x] LAB sanity check warns in logs if detected centre deviates > 20 units from expected colour reference

**Calibration**
- [x] Per-session calibration — greedy constrained assignment (max 9 per colour) with centroid refinement
- [x] Confidence margins per sticker — low-confidence stickers flagged (margin < 0.15)
- [x] Adaptive persistent calibration — EMA blend (α=0.2) saved after every parity-valid session
- [x] Manual Save Calibration button — hard-commits current session anchors (unavailable until calibration completes)
- [x] Reset Calibration button — reverts to factory defaults
- [x] Calibration store survives restarts (`.storage/rubiks_cal_<entry_id>`)

**Validation**
- [x] Running colour count check — warns if any colour exceeds 9 across scanned faces so far
- [x] Centre uniqueness check — each colour appears as centre exactly once (after face 6)
- [x] Colour count parity check — exactly 9 of each colour after calibration
- [x] `parity_valid` and `parity_error` exposed as sensor attributes

**Entities — Buttons**
- [x] Scan Face
- [x] Preview Crop (fires automatically on startup, updates Last Scan without storing)
- [x] Reset Scan
- [x] Save Calibration (unavailable until all 6 faces scanned and calibrated)
- [x] Reset Calibration

**Entities — Images**
- [x] Last Scan — updates on every scan and preview
- [x] Per-face images (White / Yellow / Red / Orange / Blue / Green) — persists annotated scan for each face, clears on reset
- [x] Scan Summary — 3×2 grid of all 6 face annotated images, generated after calibration

**Entities — Numbers**
- [x] Crop Left / Top / Right / Bottom — persisted via Store, sliders update maximums from actual image dimensions
- [x] LED Brightness — 0–255, persisted

**Entities — Sensors**
- [x] Cube State — 54-char string (scan sequence order) with plain-English attributes + emoji cube net
- [x] Current Face — next face colour and motion instruction (e.g. `White · Load (0 of 6 done)`) with loading position hint attribute
- [x] Faces Scanned — count 0–6 with per-face detail attributes + emoji grids
- [x] Scan Warnings — warning count (0 = all clear) with 🟢/🔴 status and warning list

**Entities — Text**
- [x] LED Entity ID — persisted, points at HA light entity for pre-scan illumination

**Annotated image overlay**
- [x] Crop boundary (yellow rectangle)
- [x] 3×3 grid lines
- [x] Colour-coded sample dots (centre + 4 corners per cell)
- [x] Colour label per cell
- [x] LAB values per cell
- [x] Semi-transparent background boxes for legibility

**LED control**
- [x] `_illuminate()` turns on configured LED at configured brightness before every scan/preview
- [x] 300ms stabilisation delay after turn-on

**Misc**
- [x] `hass.data` scan state cleared on unload
- [x] Annotated image also written to `www/rubiks_last_scan.jpg`

### To Do

- [ ] Options flow — change source/camera entity without re-adding integration
- [ ] Tests — unit tests for colour detection and calibration
- [ ] Sample images in repo for CI testing

---

## Phase 2 — Solver ✅

Goal: take the cube state string and produce a move sequence.

### Complete

**Sticker remapping**
- [x] `solver.py` — sticker remapping table: camera grid index 0–8 → kociemba face-position index 0–8 for each scan position
- [x] Remaps derived from barrel-roll scan orientations: W/Y/G = identity, B = 180°, O/R = horizontal mirror
- [x] After calibration, populates `kociemba_faces: dict[str, list[str]]` in `hass.data` — keyed by kociemba face label (U/R/F/D/L/B), sticker values are face letters
- [x] Existing `scanned_faces` (colour-keyed, human-readable) kept alongside

**Solver**
- [x] `kociemba>=1.0` added to `manifest.json` requirements
- [x] `solver.py` wraps `kociemba.solve()` with lazy import and error handling, runs via `async_add_executor_job`
- [x] Solve button entity

**Entities — Sensors**
- [x] Kociemba Input — 54-character string in `URFDLB` order with face-letter sticker values (direct input to `kociemba.solve()`)
- [x] Solution — move sequence (e.g. `U R2 F B R B2 R U2 L...`) with `move_count` attribute

### To Do

- [ ] Kociemba remapping verification with a known physical cube state
- [ ] Cube net display verification post-camera-fix

---

## Phase 3 — Robot

Goal: execute the solution on a physical ESP32-based robot via ESPHome.

### Planned

- [ ] ESPHome device with motor/servo control for each face
- [ ] Robot entity ID config (text entity, same pattern as LED Entity ID)
- [ ] Execute Solution button — sends moves to robot
- [ ] Move execution state sensor (idle / running / complete / error)
- [ ] Speed control number entity
- [ ] Safety stop button

---

## Known Issues / Limitations

| Issue | Notes |
|-------|-------|
| Red/Orange separation | Only ~20 LAB units apart on OV2640 — loading position enforcement (fixed sequence) eliminates the ambiguity by assigning labels from position, not centre classification; LAB warning still fires if scan looks wrong |
| White centre square has brand logo | 5-point majority vote handles it (4 white pixels, 1 on text) but confidence may be low |
| Full permutation parity not checked | Requires face adjacency data; kociemba.solve() provides this implicitly by rejecting unsolvable states |
| LED turns on but never explicitly turns off | Left on after scan — user controls it via normal HA UI |
| `image.py` `_cached_image` | Nulled directly on `ImageEntity` private attribute — brittle across HA core updates |
