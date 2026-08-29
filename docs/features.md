# Rubiks Cube Scanner — Feature Tracking

## Phase 1 — Cube State Detection ✅

Reliably scan all 6 faces and produce a valid 54-character cube state string.

**Detection**: CIELAB classification (`L×1.5, a/b×2.0` weighted distance), 5-point
majority vote per cell (centre + 4 inner corners, glare-tolerant), median LAB per cell
for display.

**Loading position enforcement**: fixed scan sequence `SCAN_SEQUENCE = ["W","B","Y","G","R","O"]`;
face label assigned by sequence position, not centre classification — eliminates
Red/Orange centre-identification ambiguity. LAB sanity check warns if a detected centre
deviates >20 units from its expected reference.

**Calibration**: per-session greedy constrained assignment (max 9/colour) with centroid
refinement; confidence margins flag low-confidence stickers (<0.15); EMA blend (α=0.2)
persisted after every parity-valid session; manual Save/Reset Calibration buttons;
survives restarts (`.storage/rubiks_cal_<entry_id>`).

**Validation**: running colour-count check, centre-uniqueness check (after face 6),
parity check (exactly 9 of each colour), `parity_valid`/`parity_error` sensor attributes.

**Entities**: Scan Face / Preview Crop / Reset Scan / Save Calibration / Reset
Calibration buttons; Last Scan, 6 per-face images, Scan Summary (cross-net layout via
`_SUMMARY_NET_POSITIONS`) images; Crop Left/Top/Right/Bottom, Crop Rotation, LED
Brightness, LED Stabilise Delay numbers; LED entity ID override text; Cube State,
Current Face, Faces Scanned, Scan Warnings sensors.

**Annotated overlay**: crop boundary, 3×3 grid, colour-coded sample dots, per-cell
colour label + LAB values, semi-transparent legibility backgrounds. Overlay points are
un-rotated back to the original image frame before drawing (`_unrotate_point()`) so they
align correctly even when `Crop Rotation` is non-zero.

**Config**: options flow allows changing source/camera entity without re-adding the
integration, plus an optional LED entity override selector. LED entity auto-discovery
resolves the camera's device, finds `light` domain entities on it, auto-selects if
exactly one.

**Testing**: 32 pytest tests (colour detection, calibration, solver logic), 13 synthetic
sample images in `tests/samples/`.

**Open**: cube net display verification.

---

## Phase 2 — Solver ✅

Take the cube state string and produce a move sequence.

`solver.py`: camera grid index → kociemba face-position index remap per scan position
(`CAMERA_TO_KOCIEMBA_REMAP` for Phase 1/2, `ROBOT_CAMERA_TO_KOCIEMBA_REMAP` for the robot
— see `docs/orientation.md`); populates `kociemba_faces` after calibration.
`kociemba>=1.0` wraps `kociemba.solve()` via `async_add_executor_job`, with a
`_is_solved()` short-circuit (the library returns a non-trivial sequence for an
already-solved input otherwise). Kociemba Input and Solution sensors expose the string
and move sequence. Verified against a physical cube end-to-end.

**Open**: cube net display verification.

---

## Phase 3 — Robot

Physically solve the cube using an ESP32-S3 robot adapted from CUBOTino. Automates both
scanning and solution execution. Architecture: `docs/robot.md`. Cross-servo timing:
`docs/collision-prevention.md`.

**Kociemba runs in HA, not the ESP32** — the two-phase pruning tables need 10-20MB RAM;
the ESP32-S3 has 8MB PSRAM.

### ESP32-S3 component

External C++ component (`esphome/components/rubiks_solver/`): `moves.h` (port of
`Cubotino_moves.py` — orientation tracking, `MOVES_TABLE`, `robot_required_moves()`),
`rubiks_solver.cpp` (`plan_flip_/spin_/rotate_/ensure_cover_*`, `plan_solution_()`,
non-blocking `loop()`). Servo position/timing defaults from `Cubotino_settings.txt`,
converted to ESPHome -1.0..1.0 via `duty_to_esphome()`. All values YAML-configurable
live via HA number entities. `auto_detach_time: 5s` on both servos (must exceed the
longest step duration to avoid mid-travel dropout).

### Scan flow

`start_scan()`/`advance_scan()` plan each face's moves (`SCAN_FACES = {"W","B","Y","G","R","O"}`,
matching `SCAN_SEQUENCE`), fire `esphome.rubiks_face_ready` per face, and after all 6,
run a `flip → spin_home → flip` return-to-start sequence (no `rotate`, so no D-layer
side effect) before firing `esphome.rubiks_scan_complete`. HA automation
(`ha_automations/rubiks_robot.yaml`) bridges `rubiks_face_ready` → `rubiks.robot_scan_face`
→ `face_scan_done`, and `rubiks_scan_complete` → `rubiks.solve` → `execute_solution`.

### Solve flow

`execute_solution()` translates the kociemba string through `moves.h` into a full servo
step queue, drained non-blocking by `loop()`. Fires `esphome.rubiks_solve_done` on
completion and returns straight to `IDLE` (no separate lingering `DONE` state).

### ESP32 API actions / events

Actions (HA→ESP32): `start_scan`, `face_scan_done`, `execute_solution` (returns
`{accepted, move_count}` via `api.respond`), `stop`, `confirm_safe_and_home`.
Events (ESP32→HA): `rubiks_face_ready {face}`, `rubiks_scan_complete`,
`rubiks_solve_done`.

### Safety / state machine

Full mechanism detail lives in the dedicated docs, not here — this is just the
inventory of what exists:

- Unclean-reset boot gate + `needs_confirm_before_move_` (also set when `stop()`
  interrupts a non-`IDLE` state) — `docs/robot.md` "Safety and timing".
- Two-layer cross-servo timing guard (plan-time + dispatch-time) —
  `docs/collision-prevention.md`.
- `SERVO_TEST` state drains a planned step queue then returns to `IDLE`; used by every
  diagnostic test button and the boot glide.
- `believed_home_` / `binary_sensor.rubiks_solver_believed_home` — optimistic home
  tracking, hard-blocks `start_scan()`/`execute_solution()` like
  `needs_confirm_before_move_` — `docs/servo-tuning.md` "Believed-home safeguard".

### Diagnostic entities

`solver_status` text sensor drives the TM1638 display, RTTTL beeps, and LED routines —
full status→feedback mapping in `docs/tm1638.md`. Servo test buttons (raw position
writes + planned cycles: rotate/spin/flip/scan-cycle/return-home). 18 single
kociemba-notation move buttons (`U`/`U2`/`U3`.../`B3`) call `execute_solution()`
directly for isolated move testing. 16 of 17 conceived calibration number entities are
live (`Top: Release Offset` remains commented out — its parameter sits at 0, a no-op
matching `Cubotino_settings.txt`'s own default); current values in `docs/servo-tuning.md`.
`Speed Multiplier` scales all step durations at plan time (currently 1.0× — the jam
cause turned out to be a servo calibration issue, not timing, so the earlier
precautionary bump was reverted). `reset_reason` diagnostic sensor.

### Versioning

`INTEGRATION_VERSION` (`const.py`) reads `manifest.json` at import time — single source
of truth, shown as `sw_version` on every HA device page. `esphome.project.name`/`version`
does the same for the ESP32 device page.

### HA side

`rubiks.robot_scan_face` service (`{face}`) runs illuminate→capture→detect→store,
schema-validated against `SCAN_SEQUENCE`. `rubiks.solve` service
(`SupportsResponse.OPTIONAL`) shared with the Solve button via `async_handle_solve()`.
4 robot control buttons (Start Scan / Stop / Abort / Advance Face) fire HA events rather
than calling ESPHome services directly, so automations are the single coupling point.

**Open**: soft guard in `ScanFaceButton` to refuse a press while the robot is scanning —
low priority.

### Hardware

Pinout, power, and calibration history: `docs/robot.md` "Hardware",
`docs/servo-tuning.md`.

### TM1638 display + buzzer + LEDs

Display, buzzer, LED routines, and physical-button actions all implemented — full
detail, current status→feedback mapping, and remaining pipelined items in
`docs/tm1638.md`.

### Future features (post-launch)

Not yet implemented, roughly in priority order: solve statistics sensors (time, move
count, personal best, history), calibration-health monitoring (auto-prompt
recalibration on drift or LED brightness change), dry-run mode (log moves without
moving servos), demo/fun modes (scramble-solve loop, speed leaderboard). Physical
TM1638 buttons and LED-bar progress indication are implemented — see `docs/tm1638.md`
for remaining pipelined items in that space (true standalone-without-HA operation
isn't one of them — the button actions route through HA, they don't bypass it).

#### Scrambler — implemented (plain random-move version)

No firmware changes — reuses `execute_solution()` entirely, so every existing guard
(`state_ == IDLE`, `needs_confirm_before_move_`, `believed_home_`) applies automatically,
same as a real solve.

- **Generator**: `generate_scramble()` (`button.py`) — picks N random moves from
  `{U,D,L,R,F,B} × {1,2,3}` (digit-suffixed form, what `normalize_solution()` already
  accepts), filtered to never repeat the same face on consecutive moves. Plain
  random-move scrambling, not WCA's random-state method — see "kociemba-compression"
  below for the more statistically rigorous option, not built.
- **Move count**: `Scramble Move Count` number entity (`number.py`), range 15-50,
  default **26** — the researched minimum for a random-move sequence to be reasonably
  well-mixed (below that, sequences tend to leave recognisable partially-solved
  patterns).
- **Entity**: `ScrambleButton` (`button.py`) generates the string in `async_press()` and
  fires `rubiks_scramble_requested` with `{solution}` as event data — same decoupling
  convention as `RobotStartScanButton`/etc. Automation 7
  (`ha_automations/rubiks_robot.yaml`) relays it to
  `esphome.rubiks_solver_execute_solution`.
- Tests: `tests/test_button.py`.

**Not built — kociemba-compression option**, if scramble statistical quality ever
matters more than it does now: simulate a long (60-100) random-move sequence against a
virtual cube state, run *that* through the existing kociemba solver, and use the
*inverse* of its solution (reversed order, each move's direction flipped: 1↔3, 2
unchanged) as the actual scramble. Gets proper random-state-equivalent mixing with a
comparable-or-shorter physical move count, at the cost of needing a new facelet-move
simulator (apply one move to a 54-character cube string, all 18 move types) — a
correctness-sensitive addition (a wrong permutation index is a *silent* bug, not an
obvious one) that would need real unit tests, not just implementation.

**Lowest priority — code health, no behavior change**: split `button.py` into
`scan_pipeline.py` (shared async helpers) + a thinned `button.py` (just entity
classes), and `camera_processor.py` into `calibration.py` (calibration/validation) +
a thinned `camera_processor.py` (detection/annotation). Pure readability/maintainability
for whoever else works on this later — not blocking anything currently.

---

## Known Issues / Limitations

| Issue | Notes |
|-------|-------|
| Red/Orange separation | ~20 LAB units apart on this camera — loading-position enforcement assigns labels by scan position, not centre classification, eliminating the ambiguity; LAB warning still fires if a scan looks wrong |
| White centre has brand logo | 5-point majority vote handles it but confidence may be low |
| Full permutation parity not checked | `kociemba.solve()` rejects unsolvable states implicitly |
| LED never auto-turns-off | User controls it via normal HA UI |
| No real servo position feedback | Neither this project nor the original CUBOTino has any — see `docs/collision-prevention.md` |
