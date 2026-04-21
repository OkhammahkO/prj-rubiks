# Rubiks Cube Scanner — Feature Tracking

## Phase 1 — Cube State Detection

Goal: reliably scan all 6 faces and produce a valid 54-character cube state string.

### Done

- [x] Integration scaffold (config flow, manifest, constants, translations)
- [x] Source selection — ESPHome camera entity or sample image file
- [x] HSV-based colour detection (3×3 grid sampling)
- [x] Face labelling by centre square colour (scan in any order)
- [x] Scan rejection if centre square is unclassified (`?`)
- [x] Warning on partial unknowns (non-centre `?` squares)
- [x] Duplicate face detection
- [x] `Scan Face` and `Reset Scan` button entities
- [x] `Cube State` sensor (54-char string, populates when all 6 faces scanned)
- [x] `Current Face` sensor (shows which colours are still missing)
- [x] `Faces Scanned` sensor with per-face colour data as attributes
- [x] Crop region number entities (Left / Top / Right / Bottom sliders)
- [x] Annotated image output — crop boundary, grid lines, sample points, colour labels
- [x] `Last Scan` camera entity serving annotated image in-memory
- [x] Annotated image also written to `www/rubiks_last_scan.jpg`

### To Do

- [ ] Sample image in repo for testing (`sample_images/`)
- [ ] HSV threshold calibration against real hardware
- [ ] Full cube state validation (each colour must appear exactly 9 times)
- [ ] Tests — colour detection unit tests, config flow tests
- [ ] Options flow — allow changing source and crop region without re-adding integration
- [ ] Scan retry UX — clearer feedback when a scan is rejected

---

## Phase 2 — Solver

Goal: take the cube state from Phase 1 and produce a move sequence.

### Planned

- [ ] Add `kociemba` as a dependency
- [ ] `solver.py` — wrap `kociemba.solve()` with state validation
- [ ] `Solve` button entity — triggers solve from current cube state
- [ ] `Solution` sensor — exposes move sequence (e.g. `U R2 F B R B2 R U2...`)
- [ ] `Move Count` sensor

---

## Phase 3 — Robot

Goal: execute the solution on a physical ESP32-based robot via ESPHome.

### Planned

- [ ] ESPHome device with motor/servo control for each face
- [ ] Robot config in config flow (select ESPHome robot device)
- [ ] `Execute Solution` button — sends moves to robot one by one
- [ ] Move execution state sensor (idle / running / complete / error)
- [ ] Speed control number entity
- [ ] Safety stop button

---

## Known Issues / Limitations

| Issue | Notes |
|-------|-------|
| HSV thresholds untested on real hardware | Red/orange distinction likely needs calibration |
| No crop calibration UI | User must know pixel coordinates; annotated overlay helps |
| Full image used if crop coordinates are all 0 | Intentional default for initial testing |
| No cube state validation | Invalid states (wrong colour counts) passed to solver without error |
