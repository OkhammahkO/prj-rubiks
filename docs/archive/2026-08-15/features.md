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

**Testing & Configuration**
- [x] Unit tests — 32 pytest tests for colour detection, calibration, and solver logic
- [x] Sample images — 13 synthetic test images in `tests/samples/` for CI/regression testing

### To Do

- [x] Options flow — allow changing source/camera entity without re-adding integration; options flow also includes an optional LED entity override selector (`EntitySelector(domain="light")`) for multi-light device edge cases
- [x] LED entity auto-discovery — `config_flow._discover_led()` resolves the camera entity's `device_id` from the entity registry, finds all `light` domain entities on that device, auto-selects if exactly one; result stored as `led_entity_id` in entry data; `Platform.TEXT` removed, `text.py`/`LedEntityIdText` removed, `hass.data` key changed from `led_entity_id_entity` to `led_entity_id`
- [ ] Cube net display verification
- [x] Grid rotation — `CROP_ROTATION` number entity (0–359°, slider); `detect_face_colors` accepts `rotation: float = 0.0`; PIL `rotate(-rotation, expand=False, fillcolor=(0,0,0))` applied after crop, before colour sampling; implemented across `const.py`, `number.py`, `camera_processor.py`, `button.py`, `strings.json`, `translations/en.json`, dashboard

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

**Verification**
- [x] Kociemba remapping verified with physical cube — scanned, solved, moves executed successfully

### To Do

- [ ] Cube net display verification

---

## Phase 3 — Robot

Goal: physically solve the cube using an ESP32-S3-based robot adapted from the CUBOTino design.
The robot automates both face scanning and solution execution. See `docs/robot.md` for architecture.

**Architecture decision:** kociemba solver runs in HA, not on the ESP32. The two-phase kociemba
pruning tables require 10–20 MB RAM; the ESP32-S3 has 8 MB PSRAM. HA already assembles the cube
state string — `kociemba.solve()` is one more step in the same pipeline.

### ESP32-S3 ESPHome component

- [x] External C++ component structure (`esphome/components/rubiks_solver/`) — `__init__.py`, `moves.h`, `rubiks_solver.h`, `rubiks_solver.cpp`
- [x] `moves.h` — complete C++ port of `Cubotino_moves.py`; orientation tracking, MOVES_TABLE, `robot_required_moves()` pipeline, verified against 5 test vectors
- [x] `rubiks_solver.cpp` — all servo primitive planners implemented: `plan_flip_()`, `plan_spin_()`, `plan_rotate_()`, `plan_ensure_cover_open_/closed_()`; `plan_solution_()` iterates robot move string; `loop()` drains step queue non-blocking
- [x] Servo position/timing defaults from `Cubotino_settings.txt` — member variables in header with defaults; converted to ESPHome −1.0..1.0 in `setup()` via `duty_to_esphome()`
- [x] All 16 values YAML-configurable — optional fields in `__init__.py` schema, generated `set_*` calls, commented override block in `rubiks_solver.yaml`
- [x] `auto_detach_time: 1s` — in YAML servo blocks

### Scan flow (robot-controlled)

Replaces the manual Scan Face button workflow.

- [x] HA calls `esphome.rubiks_solver_start_scan` → action wired to `solver.start_scan()`
- [x] HA calls `esphome.rubiks_solver_face_scan_done` → action wired to `solver.advance_scan()`
- [x] `fire_ha_event_()` implemented — `CustomAPIDevice::fire_homeassistant_event()` (requires `homeassistant_services: true` in YAML); `api::global_api_server` API removed in ESPHome 2026.x
- [x] **HA↔ESP32 API loop bench tested** — `start_scan` → 6× `face_scan_done` → `scan_complete` verified end-to-end via HA Developer Tools (stub `plan_scan_move_()` fires events immediately with no servo movement); face sequence G→W→B→Y→O→R confirmed; `SCAN END` melody and `IDLE` return confirmed
- [x] `plan_scan_move_()` — implemented; camera arm-mounted top-down; cube White=top, Green=front; arm closes for every scan (hood blocks ambient, camera perpendicular to top face); sequence: W(close) → B(open+flip+close) → Y(open+flip+close) → G(open+flip+close) → R(open+spinCW+flip+close) → O(open+2×flip+close); `SCAN_FACES[] = {"W","B","Y","G","R","O"}`; `plan_top_cover_` not reset between faces so flip planners see CLOSED and open correctly
- [x] Return-to-start implemented in `advance_scan()` after all 6 faces — corrects plan state (turntable physically at CW after R face spin_out), then: `plan_flip_(1,0)` → `plan_spin_(1)` spin_home from CW → `plan_flip_(1,0)`, landing on White-up/Green-front with the turntable at home; `fire_done_()` then fires `esphome.rubiks_scan_complete` and resets to IDLE
- [x] **Correction (2026-08-01):** the sequence above used to end with a cover-closed `plan_rotate_(1)` to bring the turntable home instead of the second flip. That's a real bug — `rotate` only moves the bottom layer, so it twisted the D layer 90° *after* the kociemba string had already been computed from the scan, leaving the physical cube one quarter-turn away from the state the solution was calculated for (the resulting solve would not actually finish the cube). Found while reviewing what happens between scan-complete and solve-start; a BFS search over the real FLIP/SPIN permutations found the shorter flip→spin_home→flip sequence above, which needs no rotate and no compensation. See `docs/robot.md` for the full verified derivation
- [x] HA automation: trigger on `esphome.rubiks_face_ready` → `rubiks.robot_scan_face {face: event.data.face}` → `esphome.rubiks_solver_face_scan_done`; implemented in `ha_automations/rubiks_robot.yaml`
- [x] HA automation: trigger on `esphome.rubiks_scan_complete` → solve button → `esphome.rubiks_solver_execute_solution`; implemented in `ha_automations/rubiks_robot.yaml`

### Solve flow

- [x] Robot receives solution string via `execute_solution` API action — wired to `solver.execute_solution(solution)`
- [x] Translates kociemba string → robot move tokens (`moves.h`) → full servo step queue (`plan_solution_()`)
- [x] Drains step queue in non-blocking `loop()` using `App.get_loop_component_start_time()`; `step_start_ms_ = 0` on start → first step fires immediately
- [x] Fires `esphome.rubiks_solve_done` — fired via `fire_ha_event_()` in `fire_done_()`

### ESP32 API actions (HA calls ESP32)

Appear in HA as `esphome.rubiks_solver_<action>` services.

- [x] `start_scan` — wired, bench tested
- [x] `face_scan_done` — wired, bench tested
- [x] `execute_solution` (variable: `solution: string`) — wired; `supports_response: optional` added — returns `{accepted: bool, move_count: int}` via `api.respond`; C++ exposes `solution_accepted()` and `move_count()` accessors
- [x] `stop` — wired

### ESP32 HA events (ESP32 fires into HA)

- [x] `esphome.rubiks_face_ready` `{face: "G"}` — fired in `fire_done_()` via `fire_ha_event_()`; bench tested, event visible in HA
- [x] `esphome.rubiks_scan_complete` — fired after all 6 faces done; bench tested
- [x] `esphome.rubiks_solve_done` — fired after solve execution completes

### ESP32 utility entities

- [x] `solver_status` text_sensor — publishes human-readable state to HA dashboard; defined as `status_sensor:` sub-field of `rubiks_solver:` component
- [x] Servo test buttons (15, including `test_scan_return_home`) — Centre Both, Top Flip/Open/Close, Bottom CCW/Home/CW; Test: Bottom rotate CW+home, Bottom rotate CCW+home, Flip×1, Flip×2, Spin CW+home, Spin CCW+home, Scan Cycle, Return Home (Post-Scan) — `diagnostic` button entities in YAML; `Bottom → Home` button uses planned release overshoot (step queue, SERVO_TEST state) not a direct write; `duration_ms` on step N is the wait after step N-1 fires, not after step N. **Correction (2026-08-15):** the parenthetical here previously claimed `plan_spin_()` uses the full endpoints `b_cw_v_`/`b_ccw_v_` rather than the release positions — wrong, and already corrected in `docs/robot.md` "Servo settings conversion" but missed here; current code uses `b_cw_rel_v_`/`b_ccw_rel_v_` for spin-out, matching that section
- [x] `SERVO_TEST` solver state — drains step queue then returns to IDLE; used by diagnostic test buttons that need planned multi-step moves without triggering scan/solve events; also used for boot glide
- [x] Boot glide — extracted into `queue_boot_glide_()`: 10-step top-cover sweep (100ms each) from wherever it starts to `t_open_v_`, then settles bottom to home via `SERVO_TEST`
- [x] **(2026-08-01)** Boot glide is now conditional on reset reason — `setup()` checks `esp_reset_reason()`; on an unclean previous reset (panic/watchdog/brownout/power-glitch/CPU-lockup/unknown) it skips the glide entirely (arm/turntable's actual position is unknown and may not match what the glide assumes), shows `CHK ARM` on the display, and stays IDLE. New **Robot: Confirm Safe & Home** button/API action (`confirm_safe_and_home()`) triggers the same glide manually once a human has checked it's safe. New `debug:` component + `reset_reason` text sensor exposes the actual reason in HA
- [x] 16 of 17 conceived servo calibration number entities are active — `entity_category: config`, `restore_value: true`, live update via `on_value` → `set_*()` + `recompute_positions()`. **Correction (2026-08-15):** this used to say only 9/16 were active with the rest commented out pending calibration — stale; all top/bottom position and timing entities are now live (including bottom spin/rotate/release times), plus a `Speed Multiplier` entity added since. Only `Top: Release Offset` remains commented out (its parameter, `d_t_rel_offset_`, sits at 0 — a no-op matching `Cubotino_settings.txt`'s own default — so nothing currently exercises the release-tension behavior it exists for)
- [x] 4 robot control button entities (non-diagnostic, visible on dashboard): **Robot: Start Scan** (`mdi:cube-scan`), **Robot: Stop** (`mdi:stop-circle-outline`), **Robot: Advance Face** (`mdi:skip-next-circle-outline`), **Robot: Confirm Safe & Home** (`mdi:home-alert-outline`, diagnostic — see boot glide above); ESPHome-side companions to the HA robot buttons — can trigger the robot directly without going through HA events/automations (useful for hardware testing)
- [x] 18 single-move test buttons — U/U2/U3, D/D2/D3, R/R2/R3, L/L2/L3, F/F2/F3, B/B2/B3; `entity_category: diagnostic`; each calls `id(solver).execute_solution("U")` (etc.) directly; for debugging composite move translation issues
- [x] **(2026-08-01)** Cross-servo timing guard generalized into `append_step_()` — `pending_bottom_travel_ms_`/`pending_top_travel_ms_` now bidirectional and automatic for every queued step, not manually threaded through individual call sites (previously only `plan_ensure_cover_closed_()` respected it; `plan_flip_()` and `plan_ensure_cover_open_()` didn't, and nothing protected top-then-bottom transitions). See `docs/robot.md` "Cross-servo timing & state-guard fixes"
- [x] **(2026-08-01)** State guards added to `advance_scan()` (requires `SCAN_WAIT`) and `execute_solution()` (requires `IDLE`) — both previously had no guard at all, unlike every other entry point
- [x] **(2026-08-01)** `stop()` now calls `reset_()` directly instead of setting a `stop_requested_` flag that `loop()` never read while disabled in `SCAN_WAIT`/`DONE` — fixes Stop silently doing nothing mid-scan or post-solve; `stop_requested_` removed as dead code
- [x] **(2026-08-15)** Independent dispatch-time cross-servo guard added (`top_dispatch_ms_`/`bottom_dispatch_ms_` etc.) — belt-and-suspenders on top of `append_step_()`'s plan-time math, checked live against the clock at the moment a step fires. See `docs/collision-prevention.md`
- [x] **(2026-08-15)** `needs_confirm_before_move_` safeguard — blocks `start_scan()`/`execute_solution()` after an unclean reset or a `stop()` that interrupted anything non-`IDLE`, until `confirm_safe_and_home()` runs. Also closed a pre-existing gap: the `CHK ARM` unclean-reset display was advisory only before this — `state_` was already `IDLE`, so nothing actually enforced waiting for confirmation
- [x] **(2026-08-15)** Solve completion (`fire_done_()`'s `SOLVING` branch) now returns straight to `IDLE` instead of a separate lingering `DONE` state — no more needing an explicit `stop()` between operations. `SolverState::DONE` removed (unused elsewhere)
- [x] **(2026-08-15)** New `"HOMING"` status + distinct beep when the 6th scan face is captured, separate from the existing `"SCAN END"` beep once physically back home
- [x] **Bug fixes found via deep review (2026-08-15):**
  - `append_step_()`'s "owed" cross-servo bookkeeping was recorded in the wrong unit whenever `speed_mul_ != 1.0` (unscaled instead of scaled) — under-protected at plan time, silently compensated for by the dispatch-time guard as an unplanned pause rather than a collision. Fixed to scale once, upfront, and keep all comparison/storage in that unit
  - Same completion path that removed the `DONE` state didn't clear `pending_bottom_travel_ms_`/`pending_top_travel_ms_` on the way to `IDLE`, unlike the analogous `SERVO_TEST` branch — inconsistent, now matches
  - Dispatch guard was logging a warning every single `loop()` tick for the duration of a hold, not once per hold episode — rate-limited
  - `queue_boot_glide_()` physically drives both servos to open/home but never updated `plan_top_cover_`/`plan_b_home_`/etc. to match — harmless only because every current caller resets those fields itself first; now self-consistent
  - **`plan_rotate_()`'s two bottom-servo step durations were swapped in both branches**, found by comparing against `Cubotino_servos.py`'s `rotate_out()`/`rotate_home()`: the real ~90° traverse (`target`/`overshoot`) was given `t_open_close_time_` (300ms, far too short) while the tiny release nudge (`target_rel`/final home step) got the full `b_rotate_time_` (1200ms) it didn't need — backwards from the original, which always pairs the long duration with the far move. Unlike a spin-timing bug this wouldn't jam anything — it would just under-rotate the bottom layer silently, which is a plausible explanation for solves not fully completing even where no collision was ever observed. Fixed to match the original's pairing

### HA side

- [x] `rubiks.robot_scan_face` HA service — accepts `{face: "W"}` schema-validated against `SCAN_SEQUENCE` (there is only one such list — see correction below); runs illuminate→capture→detect→store pipeline; uses `ROBOT_CAMERA_TO_KOCIEMBA_REMAP` (top-down camera) when calling `build_kociemba_faces()` after the 6th face; registered in `__init__.py`, handler in `button.py`
- [x] `_async_run_calibration()` extracted from `ScanFaceButton` to module-level — accepts optional `remap` param; called by `ScanFaceButton` (Phase 1/2, no remap) and `async_handle_robot_scan_face` (robot, passes `ROBOT_CAMERA_TO_KOCIEMBA_REMAP`)
- [x] `ROBOT_CAMERA_TO_KOCIEMBA_REMAP` added to `solver.py` — W/Y/G=180°, B=identity, R/O=90°CCW; `build_kociemba_faces()` accepts optional `remap` param (defaults to Phase 1/2 `CAMERA_TO_KOCIEMBA_REMAP`)
- [x] **Correction (2026-08-01):** this doc previously claimed a separate `ROBOT_SCAN_SEQUENCE = ["W","B","Y","G","R","O"]` existed in `const.py` alongside `SCAN_SEQUENCE`. It never did — stale/aspirational documentation. There's one list, `SCAN_SEQUENCE`, used by both the manual button and as the robot service's schema validator; see `docs/robot.md` "`SCAN_SEQUENCE`" section
- [x] `rubiks.solve` HA service — registered with `SupportsResponse.OPTIONAL`; calls `async_handle_solve()` (module-level, shared with `SolveButton.async_press()`); returns `{solution, move_count, cube_string}` on success, `{error, solution:"", move_count:0}` on failure; fires `rubiks_solved` event on success
- [x] `async_handle_solve()` extracted to module-level in `button.py` — accepts `(hass, data)`, returns `dict | None`; allows `SolveButton` and the `rubiks.solve` service to share identical solve logic without duplication
- [x] 4 new HA robot control buttons: **Robot Start Scan** (clears all scan state, fires `rubiks_scan_reset` + `rubiks_robot_start_requested`), **Robot Stop** (fires `rubiks_robot_stop_requested`), **Robot Abort** (clears scan state + fires `rubiks_scan_reset` + `rubiks_robot_stop_requested`), **Robot Advance Face** (fires `rubiks_robot_advance_face_requested`); fire HA events rather than calling ESPHome services directly — automations are the single coupling point
- [x] Automations wired in dev HA — `configuration.yaml` uses `automation: !include_dir_merge_list ha_automations/`; symlink `config/ha_automations` → `prj-rubiks/ha_automations/`; `ha_automations/automations.yaml` (empty `[]`, for HA UI) and `rubiks_robot.yaml` are both merged automatically
- [x] Automation 2 (Solve Dispatcher): uses `rubiks.solve` with `response_variable: solve_result` — solution available in response immediately, no button.press + delay + sensor poll
- [x] Automation 3: trigger `esphome.rubiks_solve_done` → `system_log.write`
- [x] Automation 4: trigger `rubiks_robot_start_requested` → `esphome.rubiks_solver_start_scan`
- [x] Automation 5: trigger `rubiks_robot_stop_requested` → `esphome.rubiks_solver_stop` (mode: restart)
- [x] Automation 6: trigger `rubiks_robot_advance_face_requested` → `esphome.rubiks_solver_face_scan_done`
- [x] Automations installed on production HA — same instance as dev; symlink and `!include_dir_merge_list` already in place
- [ ] Soft guard in `ScanFaceButton` — refuse press if `robot_scanning` flag set; low priority for MVP

### Versioning & diagnostics (2026-08-01)

Added after repeated confusion this session about whether a fix had actually reached the
running device — flashes silently reverting (OTA rollback), HA not fully restarting, etc.

- [x] HA integration version visible on its device page — `INTEGRATION_VERSION` in `const.py` reads `manifest.json`'s `"version"` at import time (single source of truth, no separate constant to drift); passed as `sw_version` on all 7 `DeviceInfo` blocks (`button.py`, `sensor.py`, `number.py` ×3, `image.py`, `text.py`)
- [x] ESPHome device version visible on its own device page — `esphome.project.name`/`version` in `rubiks-solver.yaml`; HA's ESPHome integration (`homeassistant/components/esphome/manager.py`) feeds `project_version` into the same device-registry `sw_version` field, displayed as `"<version> (ESPHome <esphome_version>)"`; also replaces the device's Manufacturer/Model with the `project.name` (split on `.`) instead of the `espressif`/board-name defaults
- [x] `reset_reason` diagnostic sensor (see boot safety above) — same motivation, visibility into what actually happened on the device rather than inferring from symptoms

### Dashboard fixes (2026-08-01)

`custom_components/rubiks/rubiks_dashboard.yaml`:
- [x] Fixed broken entity reference — `number.rubiks_cube_scanner_grid_rotation` doesn't exist; the entity's key/translation_key is `crop_rotation` (`const.py`), `"Grid Rotation"` is only the display name (`strings.json`). Was silently showing as unavailable in the Crop card
- [x] Split the "Manual" glance card, which mixed two non-interoperable workflows (manual no-robot scanning vs. the robot's own advance-face debug control) under one ambiguous label — `robot_advance_face` moved into the Robot entities card labelled "Advance Face (debug)"; "Manual" renamed to "Manual Scan", now containing only `scan_face` + `reset_scan`

### Hardware

- [x] Servo GPIO pins confirmed — GPIO 43 (top, UART0 TX sacrificed) and GPIO 44 (bottom, UART0 RX sacrificed); hardware tested
- [x] External 5V power rail for servos (cannot power from ESP32-S3 GPIO)
- [x] Servo pulse range extended to 2.5%/12.5% (0.5–2.5ms at 50Hz) — servos measured at ~180° on standard 1–2ms range, extended clamp gives calibration headroom; `duty_to_esphome()` formula updated to match; absolute arm positions unchanged
- [x] Bottom servo CCW/CW positions calibrated — required one spline tooth adjustment (CCW wasn't reaching 90° at software limits); confirmed clean 90° lock at raw 5% (CCW) and 10% (CW), duty ≈ 51/102, home ≈ 7.5%/77
  - [x] **Correction (2026-08-02):** CCW duty 51 stopped reaching a full 90° again — caught via `R1`/`L1` jamming (both robot moves that start with a CCW spin-out), isolated with `test_spin_ccw_home()` alone. Ruled out a timing deficit first (`b_spin_time_` raised well above default, no change). CW at 102 (25 duty units from home 77) still works fine; CCW needed dropping to 40 (37 units from home) to reach a clean 90° again. Since this is the *same* duty value that a physical spline-tooth adjustment already fixed once (line above), the servo horn most likely slipped a tooth again rather than this being a new software issue — worth re-seating the horn if this value keeps needing to move further over time, rather than continuing to compensate purely in software. Also surfaced a real gap versus the original: `Cubotino_settings.txt` keeps CW/CCW release-delta and home-overshoot as four separate parameters (`b_rel_CCW`/`B_rel_CW`, `b_extra_home_CCW`/`b_extra_home_CW`) specifically to allow this kind of per-direction asymmetry; our port shares one `d_b_extra_sides_`/`d_b_extra_home_` pair across both directions. Not changed yet — flagged as a possible future improvement if further asymmetric tuning is needed
- [x] Firmware flashed and all servo entities verified working — default calibration values (top flip/open/close: 54/69/76, bottom CCW/home/CW: 51/77/102, sides extra: 8, home extra: 2) confirmed working on hardware; no adjustment needed beyond Cubotino defaults +1 on t_open/b_home/b_cw — **superseded 2026-08-02, bottom CCW is now 40, see correction above**
- [x] CUBOTino-adapted 3D printed mechanism (flipper arm + rotating base)
- [x] ESP32-S3-CAM bracket modification if needed (~40×27 mm vs Pi Camera ~25×24 mm)
- [x] Scan sequence order confirmed — camera top-down; cube White=top, Green=front; W(0)→B(1 flip)→Y(1 flip)→G(1 flip)→R(spin CW+flip)→O(2 flips); kociemba mapping: U=scan[0], R=scan[4], F=scan[3], D=scan[2], L=scan[5], B=scan[1]

### Auxiliary hardware — TM1638 display + buzzer

Hardware tested in `esphome/esp32-s3-cam-rubiks.yaml`: TM1638 8-digit 7-segment display (GPIO 14/41/42) and RTTTL buzzer (GPIO 1).

#### Basic (implement next)

- [x] TM1638 added to `rubiks_solver.yaml` (platform: tm1638, GPIO 14/41/42, intensity 1, 500ms update)
- [x] Buzzer (RTTTL) added to `rubiks_solver.yaml` (GPIO 1, LEDC ch 6)
- [x] `solver_status` drives TM1638 display — state text: `IDLE`, `SCAN N`, `FACE N`, `SCAN END`, `SOLVING`, `DONE`; display lambda pads to 8 chars
- [x] Confirmation beep when cube is in position (`FACE N` → `on_value` → `rtttl.play`)
- [x] Scan-complete beep (`SCAN END` → double beep)
- [x] Solve-done melody (`DONE` → ascending 4-note sequence)

#### Advanced (pipelined)

- [ ] TM1638 physical buttons as local triggers — S1 = start scan, S2 = stop, S3 = manual step (no HA required for basic operation)
- [ ] Step counter on display during solve — e.g. `STP 012` (updates each servo step)
- [ ] Scan face label on display while robot is positioning — e.g. `FACE  G`
- [ ] Error codes on display — distinct patterns for scan error, solve error, comms lost
- [ ] "READY" prompt on display when waiting for cube placement

### Future features (post-launch)

Ideas to implement once the robot is physically assembled and operating.

#### Scrambler

- [ ] `scramble` HA button — generates a random N-move scramble sequence and calls `execute_solution`
- [ ] Difficulty presets: Easy (10 moves), Medium (20), Hard (30) — HA input_select or number entity
- [ ] WCA-style scrambler: avoid consecutive same-face moves and redundant cancellations
- [ ] `esphome.rubiks_solver_scramble` API action — ESP32 requests scramble from HA (HA generates, calls execute_solution back)

#### Standalone operation (no HA dashboard needed)

- [ ] S1 short press = start scan (already planned)
- [ ] S2 short press = stop / emergency halt (already planned)
- [ ] S3 short press = manual face advance during scan
- [ ] S1 long press = one-touch mode: auto-scan all 6 faces → HA solves → robot executes (full autonomous loop)
- [ ] S1 + S2 = scramble mode (N-move scramble, no HA needed — requires ESP32-side scramble generator or cached sequence)
- [ ] S2 long press = home all servos

#### TM1638 LED bar (8 LEDs)

- [ ] Scan progress: LEDs 1–6 illuminate as each face is confirmed scanned; off on reset
- [ ] Solve progress: LEDs fill left-to-right as percentage of move steps executed
- [ ] LED 7 = HA API connected (solid) / disconnected (slow flash)
- [ ] LED 8 = error state (fast flash) or busy/moving (solid)
- [ ] Celebration flash: all 8 LEDs strobe on `solve_done`

#### Display enhancements

- [ ] Solve timer — count up from 0.0 s during `execute_solution`, freeze at completion (e.g. `12.3 S`)
- [ ] Move countdown — remaining moves during solve (e.g. `M 024` → `M 000`)
- [ ] Scan progress label — face colour on display while robot is positioning (`FACE  G`)
- [ ] Scrolling text for long messages (error descriptions, WiFi status)
- [ ] Personal best display on idle screen (`PB 8.4S`)

#### Solve statistics (HA)

- [ ] Solve time sensor — stopwatch start on `execute_solution`, stop on `esphome.rubiks_solve_done`
- [ ] Move count sensor — already available as `solution` sensor attribute; surface as standalone sensor
- [ ] Personal best sensor — HA template sensor tracking minimum solve time
- [ ] Total solves counter — increment on each `solve_done` event
- [ ] HA history graph — solve time over time (built-in with sensor history)
- [ ] Completion notification — HA notify on solve with time + move count

#### Calibration stability

With the light hood (LED-only illumination), colour readings are highly stable and calibration should be a one-time operation. The EMA blend (α=0.2) provides automatic long-term drift correction after every valid session.

- [x] Lock camera AWB and AEC in ESPHome config — `aec_mode: manual`, `aec_value: 1000`, `agc_mode: manual`, `agc_value: 8`, `wb_mode: sunny`; in `esphome/esp32-s3-cam-rubiks.yaml`
- [ ] Auto-prompt recalibration if parity errors exceed N consecutive sessions — HA automation watches `Scan Warnings` sensor, fires a persistent notification after threshold
- [ ] Recalibration trigger on LED brightness change — HA automation detects the LED brightness entity changing and surfaces a "recalibrate recommended" notification (LAB values scale with luminance)
- [ ] Calibration health sensor — expose last-calibration timestamp and session-over-session anchor drift as HA sensor attributes; surface warning if drift exceeds threshold

Recalibration is expected to be needed only on: first install, LED brightness change, physical reassembly, or new cube (sticker colours vary between brands).

#### Speed / tuning modes

- [ ] Speed multiplier — number entity (0.25×–2×); all `duration_ms` in servo step queue multiplied at plan time; 0.5× for calibration slow-mo, 2× for race mode
- [ ] Dry-run mode — execute solution logging only, no servo movement (useful for verifying move translation without hardware)

#### Fun / demo

- [ ] Demo loop mode — scramble → solve → repeat; runs until stopped; good for display purposes
- [ ] Solve challenge timer — physical stopwatch from cube placement to `solve_done` (includes scan time); display on TM1638
- [ ] Speed-solve leaderboard — HA helper tracking multiple users' personal bests

---

## Known Issues / Limitations

| Issue | Notes |
|-------|-------|
| Red/Orange separation | Only ~20 LAB units apart on OV2640 — loading position enforcement (fixed sequence) eliminates the ambiguity by assigning labels from position, not centre classification; LAB warning still fires if scan looks wrong |
| White centre square has brand logo | 5-point majority vote handles it (4 white pixels, 1 on text) but confidence may be low |
| Full permutation parity not checked | Requires face adjacency data; kociemba.solve() provides this implicitly by rejecting unsolvable states |
| LED turns on but never explicitly turns off | Left on after scan — user controls it via normal HA UI |
