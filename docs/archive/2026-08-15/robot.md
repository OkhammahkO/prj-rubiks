# Rubiks Robot — Architecture & Design

## Overview

```
┌─────────────────────────────────┐     ┌──────────────────────────────────────┐
│   Home Assistant (HA)           │     │   ESP32-S3 (ESPHome)                 │
│                                 │     │                                      │
│  custom_components/rubiks/      │◄───►│  esp32_camera  (OV2640)              │
│  ├─ camera_processor.py         │     │  light         (LED ring)            │
│  ├─ solver.py (kociemba)        │     │  components/rubiks_solver/           │
│  └─ button.py / sensor.py       │     │  ├─ top servo  (flipper arm)         │
│                                 │     │  ├─ bottom servo (rotating base)     │
│                                 │     │  ├─ TM1638 display (status/buttons)  │
│                                 │     │  └─ buzzer (audio feedback)          │
└─────────────────────────────────┘     └──────────────────────────────────────┘
         Phase 1 ✅  Phase 2 ✅                       Phase 3 🔧
```

One ESP32-S3 handles everything: camera, LED, and both servos. HA handles colour
detection and solving. The two sides coordinate over the ESPHome API via entities.

---

## Hardware

### ESP32-S3 pin usage

| Block | Pins | Status |
|-------|------|--------|
| OV2640 camera | GPIO 6–13, 15–18 (data, clock, sync) | ✅ |
| Camera I2C | GPIO 4, 5 | ✅ |
| LED (LEDC ch 0) | GPIO 3 | ✅ hardware tested |
| Top servo (LEDC ch 2) | GPIO 43 — UART0 TX sacrificed | ✅ hardware tested |
| Bottom servo (LEDC ch 4) | GPIO 44 — UART0 RX sacrificed | ✅ hardware tested |
| TM1638 STB | GPIO 14 | ✅ hardware tested |
| TM1638 CLK | GPIO 41 | ✅ hardware tested |
| TM1638 DIO | GPIO 42 | ✅ hardware tested |
| Buzzer (RTTTL, LEDC ch 6) | GPIO 1 | ✅ hardware tested |

Free pins remaining: GPIO 0, 46, 47, 48.
UART logging sacrificed for GPIO 43/44 — USB-JTAG logger used instead (`logger: baud_rate: 0`).

**LEDC channel plan:** ch0=LED(timer0), ch2=topServo(timer1), ch4=botServo(timer2), ch6=buzzer(timer3).
Each output is on a separate timer pair — this matters because on ESP32-S3, channels ch0+1 share timer0,
ch2+3 share timer1, ch4+5 share timer2, ch6+7 share timer3. Putting two outputs with different
frequencies on the same timer pair silently breaks one of them. Buzzer was originally ch5 (same timer2
as bottom servo on ch4) which caused bottom servo PWM to appear dead — fixed by moving buzzer to ch6.
The camera (OV2640) uses its own internal LEDC timer for XCLK and does NOT occupy user channels.

### Servos

- **Top servo** — flipper arm: raises/lowers to flip the cube or constrain the top two layers
- **Bottom servo** — rotating base: spins the full cube (cover open) or rotates the bottom layer only (cover closed)

Both are standard 50 Hz servos. Extended pulse range (0.5–2.5 ms) is used rather than
the standard 1–2 ms — the servos only just reached ~180° at standard range, so the
clamp was widened to give calibration headroom. Absolute pulse widths at the servo
arms are unchanged; only the software clamp is wider.

ESPHome servo config:
```yaml
min_level: 2.5%    # 0.5 ms at 50 Hz (extended range)
idle_level: 7.5%   # 1.5 ms — centre
max_level: 12.5%   # 2.5 ms at 50 Hz (extended range)
auto_detach_time: 1s
```

### Power

Servos need an external 5 V / 1 A+ supply — cannot draw from ESP32-S3 GPIO directly.
A shared 5 V rail (e.g. from the same USB supply as the ESP32-S3) with a common ground
is the simplest approach.

**Decoupling capacitors:** Servos draw large inrush current spikes when activating, which
can droop the shared supply rail and glitch or reset the ESP32 mid-solve.

Recommended placement for a **16 V 220 µF electrolytic** (+ 100 nF ceramic in parallel):

| Priority | Location | What it fixes |
|----------|-----------|---------------|
| 1st | Branch point where 5 V splits to servos vs. ESP32 power input | Stops servo inrush from drooping the upstream rail; guards both paths |
| 2nd | Close to the servo connectors | Second local reservoir for two servos activating simultaneously |
| 3rd | ESP32-S3 3V3 / GND pins | WiFi TX current spikes (~250 mA bursts); lowest priority as the module already has onboard decoupling and the LDO provides isolation |

If you only have one cap, place it at the **5 V branch point**. If you see reboots during
active API calls (WiFi TX), add one at 3V3 / GND as well.

### TM1638 display

8-digit 7-segment LED display with 8 physical buttons. Connected on GPIO 14 (STB) / 41 (CLK) / 42 (DIO). Hardware tested.

**Basic use:** Display solver state — `IDLE`, `SCN 1-6`, `SOLVE`, `DONE`, `ERROR`. Driven from the `solver_status` text sensor via a `display: platform: tm1638` lambda in YAML.

**Advanced use:** Physical buttons as local triggers — S1 start scan, S2 stop, S3 manual face advance. Enables fully standalone operation without opening the HA dashboard. Step counter during solve (`STP 042`) and face label during scanning (`FACE  G`) are also planned.

### Buzzer

RTTTL buzzer on GPIO 1 (LEDC ch 6). Hardware tested.

**Basic use:** Single beep when robot signals `face_ready`, longer beep for `scan_complete`, short melody on `solve_done`. Fired directly from `fire_done_()` in C++ via `rtttl.play`.

**Advanced use:** Distinct error tones, countdown beeps before robot starts moving.

### Physical mechanism

Adapted from [CUBOTino](https://www.instructables.com/CUBOTino-Autonomous-Small-3D-Printed-Rubiks-Cube-R/)
(Andrea Favero, April 2022).

Key adaptations from the original CUBOTino design:

| Original | Adapted |
|----------|---------|
| Raspberry Pi + Pi Camera | ESP32-S3 with OV2640 (ESPHome) |
| MicroPython ESP32 for servos (UART) | Same ESP32-S3 — one device total |
| PC GUI for servo calibration | HA dashboard entities |
| Blocking `sleep_ms()` execution | Non-blocking state machine in `loop()` |

The 3D printed parts are expected to need minimal changes.
The main physical risk is the camera bracket — the ESP32-S3-CAM module
(~40×27 mm including antenna) is larger than the Pi Camera (~25×24 mm).
Being wireless removes the ribbon cable constraint, which gives more flexibility
in bracket positioning.

---

## Robot Primitives

Three physical actions (from CUBOTino), expressed as a move string:

| Token | Meaning | Top cover | Bottom servo |
|-------|---------|-----------|-------------|
| `F<n>` | Flip cube n times (front face → bottom) | Open (moves through flip position) | Stationary |
| `S<1\|3>` | Spin full cube CW (`1`) or CCW (`3`) 90° | Open | Moves |
| `R<1\|3>` | Rotate bottom layer CW (`1`) or CCW (`3`) 90° | Closed (constrains top 2 layers) | Moves |

Example: `F1R1S3` = 1 flip, 1 CW bottom-layer rotation, 1 CCW full-cube spin.

Cover must be **closed** before `R` moves and **open** before `S`/`F` moves.
The servo primitives manage this ordering automatically — but ordering alone isn't
enough; see "Cross-servo timing & state-guard fixes (2026-08-01)" below for a real bug
where the *ordering* was correct but the *timing* wasn't, letting one servo start moving
before the other's prior move had actually finished.

---

## Starting Orientation

The user places the cube in the robot with:

```
White face UP
Green face facing the camera (FRONT)
```

This is the canonical starting position for both scanning and solving.

It maps directly to kociemba's face assignment already in `solver.py`:

```python
W=U, Y=D, G=F, B=B, O=L, R=R
```

CUBOTino's `starting_cube_orientation()` initialises:

```
h_faces = {L: Orange(L), F: Green(F), R: Red(R)}
v_faces = {D: Yellow(D), F: Green(F), U: White(U)}
```

This is CUBOTino's default — no remapping needed because the user always
places the cube in this exact orientation before the robot takes over.

**Why this eliminates the orientation problem:**
With manual scanning (Phase 1/2), the user follows a barrel-roll sequence that
ends with the cube in a non-canonical orientation. With robot-controlled scanning,
the robot tracks orientation throughout and always returns the cube to
White-up, Green-front before solving — the kociemba face assignment is always valid.

---

## Scan Flow

The robot automates face presentation, replacing the manual Scan Face button.

```
User places cube (White up, Green front)
        │
        ▼ HA calls: esphome.rubiks_solver_start_scan
        │
        ▼ Robot: moves cube to scan position for face 1
        │        fires HA event: esphome.rubiks_face_ready {face: "G"}
        │
        ▼ HA automation: trigger on esphome.rubiks_face_ready
        │   → rubiks.robot_scan_face {face: event.data.face}
        │     (illuminate → capture → detect → store; calibrates after face 6)
        │   → calls: esphome.rubiks_solver_face_scan_done
        │
        ▼ Robot: advances to face 2 ... repeat × 6
        │
        ▼ Robot: returns cube to White-up, Green-front
        │        fires HA event: esphome.rubiks_scan_complete
        │
        ▼ HA automation: trigger on esphome.rubiks_scan_complete
        │   → runs kociemba solver (existing pipeline)
        │   → calls: esphome.rubiks_solver_execute_solution {solution: "U2 R1 ..."}
        │
        ▼ Robot: executes solution
        │        fires HA event: esphome.rubiks_solve_done
```

### Scan sequence

Camera is **top-down** — the cube's top face is always in view.
Cube loaded with White=top, Green=front.

| Step | Face | Robot moves | kociemba face |
|------|------|-------------|---------------|
| 0 | White | (none) → close arm | U |
| 1 | Blue | open → 1 flip → close arm | B |
| 2 | Yellow | open → 1 flip → close arm | D |
| 3 | Green | open → 1 flip → close arm | F |
| 4 | Red | open → spin CW → 1 flip → close arm | R |
| 5 | Orange | open → 2 flips → close arm | L |
| — | Return | flip → spin_home → flip | — |

Return-to-start fires `esphome.rubiks_scan_complete` on completion and parks the cube White=top, Green=front with the turntable at home. Implemented in `advance_scan()` when `scan_face_idx_ >= NUM_FACES`. The turntable is physically at CW after face 5 (left there by the R face spin_out in step 4 — never returned home); plan state is corrected before planning the return steps.

**Corrected 2026-08-01** — this used to be `open → spin_home → flip → spin_CCW → rotate_home`,
ending on a cover-closed `rotate_home` to bring the turntable back to HOME. That's a real bug:
`rotate` only moves the bottom layer (cover closed, top 2 layers held), so it twists the D
layer 90° — and it did so *after* the cube had already been fully scanned and its kociemba
string computed, leaving the physical cube one quarter-turn away from the state the solution
was actually calculated for. Found while reviewing what happens between scan and solve.

A brute-force BFS search over the actual FLIP/SPIN permutation formulas (not manual
derivation — an earlier hand-derivation attempt wrongly concluded no rotate-free solution
existed) found a shorter, correct sequence using only whole-cube moves: **flip → spin_home
→ flip**. No rotate, no D-layer side effect, no compensation needed elsewhere. Verified step
by step:
```
start:               U=O,F=Bl,D=Rd,Bk=G,L=W,R=Y   (turntable CW)
flip:                U=G,F=O,D=Bl,Bk=Rd            (L,R unchanged: W,Y)
spin_home(CW→HOME):  U=G,F=Y,D=Bl,Bk=W             (L,R now: O,Rd)   turntable HOME
flip:                U=W,F=G,D=Y,Bk=Bl             (L,R unchanged: O,Rd)  ← target ✓
```

The arm closes for every scan: the camera is arm-mounted (at right angle to the top face) and the closed arm forms the light hood blocking ambient light. `plan_ensure_cover_closed_()` is appended after `plan_scan_move_()` in both `start_scan()` and `advance_scan()`. The `plan_top_cover_` state is **not** reset between faces so flip planners see the correct CLOSED state and add an open step at the start of each move.

Implemented in `plan_scan_move_()`. `SCAN_FACES[] = {"W","B","Y","G","R","O"}` in `rubiks_solver.cpp`.

kociemba string assembly (URFDLB order): U=scan[0], R=scan[4], F=scan[3], D=scan[2], L=scan[5], B=scan[1].

Because the robot controls all cube movements during scanning, the face
at the camera viewpoint is always known — `override_centre` in
`detect_face_colors()` is set from the robot's declared face order,
not from classifying the centre square.

---

## Solve Flow

After scanning, kociemba outputs a solution string (e.g. `"U2 R1 F3 D2 ..."`).

```
HA: kociemba solution string
        │
        ▼ HA calls: esphome.rubiks_solver_execute_solution {solution: "U2 R1 F3 D2 ..."}
        │
        ▼ ESP32: strip spaces → "U2R1F3D2..."
        │
        ▼ robot_required_moves() — Cubotino_moves.py logic (C++ port):
        │   for each 2-char block:
        │     adapt_move() — map abstract face to current physical position
        │     moves_dict lookup → robot primitive string
        │     cube_orient_update() — track orientation change
        │   optimize_moves() — strip cancelling pairs (S1S3, S3S1)
        │   → robot move string e.g. "F1R1S3R1S3F2R1S3..."
        │
        ▼ plan_solution() — build full step queue (ServoStep[])
        │   for each token in robot move string:
        │     call plan_flip_up / plan_spin_out / plan_rotate_out etc.
        │     each appends {servo, position, duration_ms} entries
        │
        ▼ loop() drains queue — one step per tick, millis() for timing
        │
        ▼ fires HA event: esphome.rubiks_solve_done
```

---

## HA ↔ ESP32 Interface

The two sides use ESPHome's API actions system — direct typed calls rather than
entity state polling. This is cleaner and more reliable than writing to text entities
and watching for state changes.

### HA → ESP32 (ESPHome API actions)

Defined in `rubiks_solver.yaml` under `api: actions:`. Appear in HA as
`esphome.rubiks_solver_<action>` services, callable from automations or scripts.

```yaml
api:
  actions:
    - action: start_scan
      then:
        - lambda: 'id(solver).start_scan();'

    - action: face_scan_done
      # HA calls this after processing each face snapshot
      then:
        - lambda: 'id(solver).advance_scan();'

    - action: execute_solution
      supports_response: optional   # returns {accepted: bool, move_count: int}
      variables:
        solution: string   # kociemba solution e.g. "U2 R1 F3 D2 ..."
      then:
        - lambda: 'id(solver).execute_solution(solution);'
        - api.respond:
            data: !lambda |-
              root["accepted"]   = id(solver).solution_accepted();
              root["move_count"] = id(solver).move_count();

    - action: stop
      then:
        - lambda: 'id(solver).stop();'
```

### ESP32 → HA (HA events fired from C++)

The C++ component fires Home Assistant events directly via the ESPHome API server.
HA automations listen for these events.

```cpp
// cube positioned, ready for face scan:
api::global_api_server->send_homeassistant_event(
    "esphome.rubiks_face_ready", {{"face", face_label}});

// all 6 faces scanned, cube returned to start:
api::global_api_server->send_homeassistant_event(
    "esphome.rubiks_scan_complete", {});

// solve finished:
api::global_api_server->send_homeassistant_event(
    "esphome.rubiks_solve_done", {{"status", "solved"}});
```

### HA automations

Six automations bridge the HA custom component and the ESPHome component.
All are implemented in `ha_automations/rubiks_robot.yaml`.

In the dev environment, `configuration.yaml` uses:
```yaml
automation: !include_dir_merge_list ha_automations/
```
with a symlink `config/ha_automations` → `prj-rubiks/ha_automations/`.
`ha_automations/automations.yaml` (empty `[]`) is the HA UI's write target;
`rubiks_robot.yaml` holds the rubiks automations — both are merged automatically.

**Automation 1 — Scan coordinator:**
```
trigger:  event esphome.rubiks_face_ready  {face: "G"}
action:
  1. delay 300ms  (servo settle before camera capture)
  2. rubiks.robot_scan_face {face: event.data.face}
     (illuminate → capture → detect → store; calibrates after face 6)
  3. call esphome.rubiks_solver_face_scan_done
```

**Automation 2 — Solve dispatcher:**
```
trigger:  event esphome.rubiks_scan_complete
action:
  1. rubiks.solve → response_variable: solve_result
  2. call esphome.rubiks_solver_execute_solution
       {solution: "{{ solve_result.solution }}"}
     response_variable: exec_result
     (exec_result.accepted / exec_result.move_count)
```

Note: Automation 2 uses `rubiks.solve` with a response variable — no button press,
no delay, no sensor polling. `execute_solution` also returns a response (accepted,
move_count) for immediate validation.

**Automation 3 — Solve-done notification:**
```
trigger:  event esphome.rubiks_solve_done
action:   log / notify with status
```

**Automation 4 — Robot Start Scan:**
```
trigger:  event rubiks_robot_start_requested   (fired by HA Robot Start Scan button)
action:   call esphome.rubiks_solver_start_scan
```

**Automation 5 — Robot Stop:**
```
trigger:  event rubiks_robot_stop_requested    (fired by HA Robot Stop / Robot Abort button)
action:   call esphome.rubiks_solver_stop
```

**Automation 6 — Robot Advance Face:**
```
trigger:  event rubiks_robot_advance_face_requested  (fired by HA Robot Advance Face button)
action:   call esphome.rubiks_solver_face_scan_done
```

Automations 4–6 decouple HA button classes from ESPHome service names — the automation
YAML is the only place `esphome.rubiks_solver_*` service names appear. If the ESPHome
device name changes, only the automation file needs updating.

### `execute_solution` action response

`execute_solution` has `supports_response: optional` — HA can read back whether the
solution was accepted and how many robot moves were planned:

```yaml
- action: execute_solution
  supports_response: optional
  variables:
    solution: string
  then:
    - lambda: "id(solver).execute_solution(solution);"
    - api.respond:
        data: !lambda |-
          root["accepted"]   = id(solver).solution_accepted();
          root["move_count"] = id(solver).move_count();
```

C++ exposes `solution_accepted()` and `move_count()` public accessors; both members
are set during `execute_solution()` / `plan_solution_()` before `api.respond` runs.

### Status sensor (optional, for dashboard)

A `text_sensor` on the ESP32 can still publish human-readable status
(`idle`, `scanning face 2 of 6`, `solving step 12 of 34`, `done`) for
display on the HA dashboard — but it is not used for control flow.
Control flow uses actions and events only.

---

## HA Component Integration

How `custom_components/rubiks/` connects to the robot scan pipeline.
This section covers the gaps between the Phase 1/2 manual scan design
and what the Phase 3 robot scan needs.

### Development setup

`/workspaces/core/config/custom_components/rubiks` is a symlink to
`/workspaces/prj-rubiks/custom_components/rubiks` — edits are live
immediately in the HA core instance. Restart HA (or reload the
integration) after changes to Python files.

Tests run directly from the repo root:
```bash
cd /workspaces/prj-rubiks
pytest   # runs custom_components/rubiks/tests/
```

### What the existing HA component does

`ScanFaceButton.async_press()` (in `button.py`):
1. Looks up the current face via `SCAN_SEQUENCE[len(scanned_faces)]`
   (barrel-roll order `W,B,Y,G,O,R` — defined in `const.py`)
2. Captures a camera image, turns on LED first (`_illuminate()`)
3. Calls `detect_face_colors(image, crop_box, refs, face_label)`
   where `face_label` is passed as `override_centre` — always
   replaces the detected centre sticker with the declared face,
   because the sequence position is ground truth
4. Stores result in `scanned_faces[face_label]`
5. After all 6 faces: calls `_run_calibration()` → greedy constrained
   LAB assignment, centroid refinement, parity check, fires
   `rubiks_calibrated` event

`build_kociemba_faces()` (in `solver.py`):
- Maps colour code → kociemba face label: W→U, Y→D, G→F, B→B, O→L, R→R
- Applies `CAMERA_TO_KOCIEMBA_REMAP` per-face to reorder camera
  grid indices to kociemba canonical sticker positions

### Robot scan service: `rubiks.robot_scan_face`

**Implemented** in `custom_components/rubiks/` (`button.py` handler, `__init__.py` registration).

The service accepts `{face: "W"|"B"|"Y"|"G"|"R"|"O"}` (schema-validated against
`SCAN_SEQUENCE` — see the correction in the "`SCAN_SEQUENCE`" section below; there is
no separate robot-specific list). It runs the same illuminate→capture→detect→store pipeline
as `ScanFaceButton` but uses the supplied face label directly instead of
`SCAN_SEQUENCE[len(scanned)]`. After the 6th face it calls `_async_run_calibration()`
with `remap=ROBOT_CAMERA_TO_KOCIEMBA_REMAP`.

`_async_run_calibration()` is a module-level helper in `button.py` extracted from
`ScanFaceButton`; it accepts an optional `remap` parameter so both the manual button
(Phase 1/2, no remap) and the robot service (top-down camera remap) share the same
calibration logic.

The automation sequence (in `ha_automations/rubiks_robot.yaml`):
```
trigger: esphome.rubiks_face_ready {face: "W"}
  → rubiks.robot_scan_face {face: "W"}   ← illuminate + capture + detect + store
  → esphome.rubiks_solver_face_scan_done
```

### Sticker remap: `ROBOT_CAMERA_TO_KOCIEMBA_REMAP`

> **Superseded** — the derivation below (index-permutation remap applied after detection)
> predates a later refactor. The live implementation now applies rotation via
> `FACE_SCAN_ROTATIONS` in `camera_processor.py` *before* detection instead, with
> `ROBOT_CAMERA_TO_KOCIEMBA_REMAP` left as identity for all faces. See `docs/orientation.md`
> for the current, hardware-validated derivation (2026-07-26) — it independently arrives at
> the same 90° rotation for R/O that this section found, which is good corroboration since
> this section was written before the `SCAN_FACES` label bug existed.

`CAMERA_TO_KOCIEMBA_REMAP` in `solver.py` was derived from the Phase 1/2
barrel-roll scan (front-facing camera). The robot uses a **top-down camera**
with a different fixed frame — all remaps differ.

**Confirmed camera frame** (empirically verified via Preview Crop):
- Row 0 (image top) = Green (F) side — arm mounted behind cube, Green faces away
- Row 2 (image bottom) = Blue (B) side
- Col 0 (image left) = Red (R) side ← confirmed from White face scan image
- Col 2 (image right) = Orange (L) side

**Derivation** (cube state when face is on top, then camera frame vs kociemba canonical):

| Face | State (top) | Cam row0 | Cam col0 | Kocie canonical (top, left) | Transform | Remap |
|------|------------|----------|----------|-----------------------------|-----------|-------|
| W | start: F=G | Green | Red | U: (Blue, Orange) | 180° | `[8,7,6,5,4,3,2,1,0]` |
| B | 1 flip: F=W | White | Red | B: (White, Red) | identity | `[0,1,2,3,4,5,6,7,8]` |
| Y | 2 flips: F=B | Blue | Red | D: (Green, Orange) | 180° | `[8,7,6,5,4,3,2,1,0]` |
| G | 3 flips: F=Y | Yellow | Red | F: (White, Orange) | 180° | `[8,7,6,5,4,3,2,1,0]` |
| R | spinCW+flip: F=G, L=W | Green | White | R: (White, Green) | 90° CCW | `[2,5,8,1,4,7,0,3,6]` |
| O | +2 flips: F=B, L=W | Blue | White | L: (White, Blue) | 90° CCW | `[2,5,8,1,4,7,0,3,6]` |

Note: for R and O the turntable's CW spin (Red face) shifts L=White, R=Yellow to the
left/right columns of the camera image, hence the 90° CCW transform.

Implemented as `ROBOT_CAMERA_TO_KOCIEMBA_REMAP` in `solver.py` alongside the
existing `CAMERA_TO_KOCIEMBA_REMAP` (Phase 1/2 kept intact).
The robot scan service passes this remap to `build_kociemba_faces()` via the
optional `remap` parameter added to that function (`None` defaults to Phase 1/2
`CAMERA_TO_KOCIEMBA_REMAP`).

### `SCAN_SEQUENCE`

**Corrected 2026-08-01** — this section previously described a `ROBOT_SCAN_SEQUENCE`
constant separate from `SCAN_SEQUENCE`. That constant never actually existed in the
codebase; this was aspirational/stale documentation, not a description of shipped code.

There is exactly one list: `SCAN_SEQUENCE = ["W","B","Y","G","R","O"]` in `const.py`.
`ScanFaceButton` uses it directly (`SCAN_SEQUENCE[len(scanned)]`) to label each manual
capture. `__init__.py` uses the same list as the schema validator for the
`rubiks.robot_scan_face` service (`vol.In(SCAN_SEQUENCE)`) — but the robot flow doesn't
look anything up in it at scan time; `async_handle_robot_scan_face` uses whatever `face`
value arrives in the service call payload, which originates from `SCAN_FACES` in
`rubiks_solver.cpp` on the ESP32 side. Both lists must stay in the same order — see
`docs/orientation.md` for the full derivation of that order and the saga of getting it
right (it was flip-flopped twice on 2026-07-26 based on contradictory eyeballed camera
reads before being settled mathematically).

### Manual scan guard (low priority)

`ScanFaceButton` has no awareness of robot scan state. If pressed during
robot scanning it stores the face under `SCAN_SEQUENCE[len(scanned)]`
which may not match the robot's current face. A soft guard (refuse if
a `robot_scanning` flag is set) prevents accidental corruption.
Not needed for MVP — just don't press the manual button during a robot scan.

### Phase 1/2 manual scan path

Keep it intact — useful for debugging camera crop and calibration
without needing the robot hardware. The robot service and manual
button share the same `scanned_faces` store and `_run_calibration()`
path; they are not in conflict if not used simultaneously.

---

## ESPHome Component Design

### File structure

```
esphome/
  rubiks_solver.yaml              ← device config (camera, LED, servos, component ref)
  secrets.yaml                    ← gitignored (WiFi credentials)
  components/
    rubiks_solver/
      __init__.py                 ← YAML schema, defaults, codegen
      moves.h                     ← C++ port of Cubotino_moves.py (pure logic, no hardware)
      rubiks_solver.h             ← component class, ServoStep type, state enums
      rubiks_solver.cpp           ← primitive builders, planner, loop() drainer
```

### Why kociemba runs in HA, not on the ESP32

The two-phase kociemba algorithm requires precomputed pruning tables loaded at runtime.
The smallest viable implementations need 10–20 MB of RAM for those tables.
The ESP32-S3 has 8 MB PSRAM — the tables don't fit.

This is the right separation anyway: HA already runs the camera image processing and
assembles the cube state string. Calling `kociemba.solve(cube_string)` in the same
Python layer (one more line in `solver.py`) is natural. The ESP32's only job for solving
is to faithfully execute the solution string it receives — it never needs to understand
the cube. This also makes each side independently testable.

### Why an external C++ component

The servo logic (`Cubotino_servos.py`, ~900 lines) has complex state:
16 position/timing settings, multi-step primitives with conditional branching,
orientation tracking across the full move sequence. YAML lambdas can't share
state cleanly across a file. C++ gives proper classes, enums, and arrays —
much closer to the Python source structure and significantly easier to maintain.

### Key types

```cpp
enum class TopCover { OPEN, CLOSED, FLIP };
// Bottom servo position is tracked by three plan-time booleans
// (plan_b_home_, plan_b_cw_pos_, plan_b_ccw_pos_) rather than an enum.
// These are updated as steps are planned, not during execution.

struct ServoStep {
    enum Target { TOP, BOTTOM } target;
    float    position;      // ESPHome normalised -1.0..1.0
    uint32_t duration_ms;   // wait after the PREVIOUS step fires before issuing this step
};
```

### Step queue pattern

All steps for a scan or solve are pre-planned into a `std::vector<ServoStep>`
before execution begins. `loop()` drains it one step at a time.

**Why pre-plan:** Orientation state (`h_faces` / `v_faces`) and cover state
(`top_cover_`, `bottom_pos_`) are updated *as steps are planned*. This makes
the complex conditional logic (e.g. "if cover is already closed, skip the
close step") run at plan time where it's easy to reason about, and keeps
`loop()` trivially simple — just check the timer and fire the next step.

### Non-blocking constraint

ESPHome's `loop()` runs every ~16 ms and must never block. The MicroPython
source uses `sleep_ms()` throughout; these become timer checks in `loop()`.

Use `App.get_loop_component_start_time()` (cached per tick) rather than `millis()`:

```cpp
void loop() {
    if (state_ == SolverState::IDLE || state_ == SolverState::SCAN_WAIT ||
        state_ == SolverState::DONE) return;
    if (step_idx_ >= steps_.size()) { fire_done_(); return; }

    auto now = App.get_loop_component_start_time();
    if (now - step_start_ms_ < steps_[step_idx_].duration_ms) return;

    const auto &step = steps_[step_idx_++];
    if (step.target == ServoStep::TOP)    top_servo_->write(step.position);
    if (step.target == ServoStep::BOTTOM) bottom_servo_->write(step.position);
    step_start_ms_ = now;
}
// step_start_ms_ = 0 when execution begins → (now - 0) is always large → step 0 fires
// immediately regardless of its duration_ms. Put travel time on step 1, not step 0.
```

**2026-08-01:** `stop()` used to just set a `stop_requested_` flag for `loop()` to notice —
but `loop()` is disabled entirely in `SCAN_WAIT` and `DONE` (see below), so the flag was
never actually read in those states. Symptom: pressing Stop while paused mid-scan or after
a solve did nothing, and the next `start_scan()` was rejected as "not idle". `stop()` now
calls `reset_()` directly instead of deferring to a loop tick that might never come. The
flag was removed entirely as dead code. See "Cross-servo timing & state-guard fixes" below
for this and related fixes made the same day.

### Loop lifecycle: disable_loop / enable_loop

The component spends most of its life idle. Following ESPHome best practice,
call `disable_loop()` when idle so the component is removed from the active
loop entirely — only re-entering when a scan or solve is triggered:

```cpp
void setup() override { disable_loop(); }

void start_scan() {
    plan_scan_sequence();
    executing_ = true;
    enable_loop();   // start receiving loop() ticks
}

void fire_done() {
    executing_ = false;
    disable_loop();  // go quiet until next command
    // fire HA event...
}
```

### Why not servo transition_length

ESPHome's servo component has a `transition_length` setting that smooths movement.
Do not use it for sequencing: there are known issues (servo snaps to idle position
at full speed on first call after reboot), and it gives no callback when the
movement completes. Explicit step durations in the queue give the timing control
the robot requires.
```

### Cross-servo timing & state-guard fixes (2026-08-01)

Found while investigating a reported jam during the scan's spin+flip step (position 4).

**The timing bug.** A queued step's `duration_ms` is the wait *before that step fires*,
timed from when the *previous* step fired — not necessarily how long that previous
step's own physical move actually takes. `plan_spin_()` queues the bottom servo's spin
with duration `b_spin_time_`; the *next* queued step (raising the flip lever, or
opening/closing the cover) used its own unrelated duration constant. If that top-servo
constant is shorter than `b_spin_time_`, the lifter starts moving before the turntable
has physically finished — a structural race, not an occasional glitch, and it affects
ordinary solving too: the kociemba move table (`moves.h`) produces `S3F1R1`-style
sequences (spin immediately followed by flip) for every `R`/`L` face turn.

A narrow fix already existed for one direction — `pending_bottom_travel_ms_`, set by
`plan_spin_()`, consulted only by `plan_ensure_cover_closed_()` — but not by
`plan_flip_()` or `plan_ensure_cover_open_()`, and nothing protected the reverse
direction (a top move immediately followed by a bottom move, e.g. `plan_rotate_()`
closing the cover then moving the bottom servo).

**The fix:** generalized into `append_step_()` itself — the single choke point every
queued step passes through — so it's automatic for all current and future callers
rather than something each call site has to remember. The snippet below is the
*original* version of that fix; it was later found to record the "owed" value in the
wrong (unscaled) unit whenever `speed_mul_ != 1.0`, and a second, independent
dispatch-time guard was added on top of it. See `docs/collision-prevention.md` for the
current, complete picture — this section is kept for the historical diagnosis, not as
an up-to-date reference for `append_step_()`'s exact current implementation:

```cpp
// Historical — see docs/collision-prevention.md for the current version.
void RubiksSolverComponent::append_step_(ServoStep::Target target, float pos, uint32_t dur_ms) {
  uint32_t &owed_to_me = (target == ServoStep::TOP) ? pending_bottom_travel_ms_
                                                      : pending_top_travel_ms_;
  dur_ms = std::max(dur_ms, owed_to_me);
  owed_to_me = 0;

  uint32_t &owed_by_me = (target == ServoStep::TOP) ? pending_top_travel_ms_
                                                      : pending_bottom_travel_ms_;
  owed_by_me = dur_ms;

  steps_.push_back({target, pos, (uint32_t)(dur_ms * speed_mul_ + 0.5f)});
}
```

**Relationship to the original CUBOTino firmware:** the original's
`b_servo_operable`/`b_servo_stopped` flags (`Cubotino_servos.py`) are *not* a stronger
timing signal — those servos have no position feedback in either project, so the
original is also just `servo.duty(x); sleep_ms(calibrated_number)`. What it has instead
is a structural guarantee: being a single-threaded blocking script, every function is an
atomic "command, then sleep for *this exact command's* own duration" unit, so a duration
can never be misattributed to the wrong servo's move. Our non-blocking step queue
decouples "what to do" from "how long to wait before doing it," which is what let the
bug exist. The `append_step_()` fix is the honest port of that guarantee given the
constraint that these are open-loop servos: still calibrated-duration estimates, but
centralized so they can't be forgotten at a new call site the way they were twice here.

**Separate state-guard bugs found in the same investigation** (unrelated to timing):
- `advance_scan()` and `execute_solution()` had no state check at all — every other
  entry point (`start_scan()`, every `servo_*`/`test_*` helper) requires `state_ ==
  IDLE` first. Both now check the appropriate state (`SCAN_WAIT` for `advance_scan()`,
  `IDLE` for `execute_solution()`) before doing anything, matching the pattern
  everywhere else.
- `stop()`'s fix is documented in the "Loop lifecycle" section above.

### Boot safety: unclean-reset detection (2026-08-01)

`setup()` used to unconditionally queue a glide-to-rest move (see `queue_boot_glide_()`)
on every boot, assuming the arm is at idle and the turntable is wherever it last was.
That assumption is unsafe after a crash: if the previous session ended mid-motion
(panic, watchdog, brownout — anything other than a deliberate reset), the arm/turntable's
actual physical position is unknown and may not match what the glide assumes, risking the
lifter jamming against the cube holder if the turntable isn't at one of its slot-aligned
positions (see the physical mechanism discussion in the 2026-08-01 conversation — the
cube holder's lifter-clearance slot lines up only every 90°).

`setup()` now checks `esp_reset_reason()` and classifies it via `is_clean_reset_reason()`
(power-on, a deliberate `esp_restart()` such as OTA, external reset pin, or an active
SDIO/USB/JTAG debug connection all count as clean; panic, any watchdog, brownout, power
glitch, CPU lockup, or an unrecognised reason don't). On an unclean reset it skips the
glide entirely, logs a warning, shows `CHK ARM` on the TM1638 display, and stays in
`IDLE` — the ESPHome servo platform itself doesn't drive anything on its own here (with
`restore:` unset in YAML, its own `setup()` just detaches/silences the PWM signal rather
than commanding a position), so simply not queuing a move is sufficient to prevent
motion. A new API action + button, **Robot: Confirm Safe & Home**
(`confirm_safe_and_home()`), lets you trigger the same glide manually once you've
physically checked the arm/turntable aren't in a colliding position.

Also added: a standard ESPHome `debug:` component with a `reset_reason` text sensor, so
the actual reset reason is visible in HA going forward (`sensor.rubiks_solver_reset_reason`)
rather than only in the device log.

### Servo settings conversion

`Cubotino_settings.txt` stores raw MicroPython PWM duty values (0–1023 scale at 50 Hz).
`rubiks_solver.cpp` `setup()` converts each to ESPHome's normalised -1.0..1.0 via:

```cpp
static float duty_to_esphome(int duty) {
    float pct = duty / 1023.0f * 100.0f;  // → % duty cycle
    return (pct - 7.5f) / 5.0f;           // → -1.0..1.0 for 2.5%..12.5% (idle=7.5%)
}
```

`__init__.py` does not perform this conversion — it only handles schema validation and
servo-reference codegen. All position arithmetic lives in C++.

Values below were the confirmed-working set as of the last hardware pass, before the
CCW recalibration described after the table — kept for the duty→ESPHome-value worked
examples, but treat the specific numbers as historical, not current:

| Duty | Member | ESPHome value | Notes |
|------|--------|--------------|-------|
| 54 | `t_flip_v_` | −0.444 | |
| 69 | `t_open_v_` | −0.151 | Cubotino default was 68; +1 adjustment |
| 76 | `t_close_v_` / `t_rel_v_` | −0.014 | |
| 77 | `b_home_v_` | +0.005 | Cubotino default was 76; +1 adjustment |
| 102 | `b_cw_v_` | +0.494 | Cubotino default was 101; +1 adjustment |

`b_home` (duty 77) maps to +0.005, near-zero — the servo's geometric centre is at duty ≈ 76.6
so 77 is the nearest integer. Timing values pass through unchanged.

`plan_spin_()` uses `b_cw_rel_v_`/`b_ccw_rel_v_` (the release-offset positions, i.e. `b_cw_v_`/
`b_ccw_v_` adjusted by `d_b_extra_sides_`), not the raw full-endpoint values — this note used to
claim the opposite, which didn't match the code; corrected 2026-08-02.

### Bottom CCW recalibration (2026-08-02)

`R1`/`L1` were jamming — both robot moves start with a CCW spin-out (`S3`, see the
`MOVES_TABLE` in `moves.h`), and the turntable wasn't quite reaching 90° before the flip
lever engaged. Isolated with `test_spin_ccw_home()` alone (no flip/rotate involved), which
reproduced the same under-rotation on its own.

Ruled out timing first: raising `b_spin_time_` well above its default made no difference,
which rules out the servo simply running out of time. That also argues against a hard
mechanical obstruction — a real physical blockage wouldn't budge no matter how far the
target was pushed, but pushing the CCW target further *did* fix it (see below), so it was
under-commanded travel, not a stop.

CW (`"Bottom: CW Pos"` = 102, 25 duty units from home = 77) already reached a clean 90°.
CCW (`"Bottom: CCW Pos"`) needed dropping from 51 (only 26 units from home) to **40** (37
units from home) to reach a clean 90° — a genuine asymmetry between the two directions, not
explained by the commanded distance alone (CCW at the old value 51 was already traveling
slightly *more* raw distance than the working CW side, yet arriving short).

This is likely the same physical issue `features.md` already recorded once before — CCW
previously needed a spline-tooth adjustment on the servo horn to reach 90° at this same duty
51. If it needed compensating again, the horn most likely slipped a tooth again rather than
this being a new software deficiency. Worth re-seating the horn if `"Bottom: CCW Pos"` keeps
needing to move further over time.

`Cubotino_settings.txt` (the original project's own settings file) documents CW/CCW release
delta and home-overshoot as four separate parameters — `b_rel_CCW`/`B_rel_CW` and
`b_extra_home_CCW`/`b_extra_home_CW` — specifically to allow this kind of per-direction
difference. Our port shares one `d_b_extra_sides_` and one `d_b_extra_home_` pair across both
directions (`recompute_positions()`), so there's currently no way to tune CCW's release/
overshoot independently of CW's. Not changed as part of this fix (moving `"Bottom: CCW Pos"`
alone was sufficient), but worth splitting into direction-specific pairs if further
asymmetric tuning is ever needed.

---

## ESPHome build gotchas

Compilation issues hit during development — notes for future reference.

| Symptom | Cause | Fix |
|---------|-------|-----|
| `'APIServer' has no member 'send_homeassistant_event'` | Method removed in ESPHome 2026.x; modern API uses `send_homeassistant_action()` with `is_event=true` | Inherit from `api::CustomAPIDevice`; call `this->fire_homeassistant_event()` |
| `fire_homeassistant_event() requires 'homeassistant_services: true'` | Guard disabled at compile time | Add `homeassistant_services: true` under `api:` in YAML |
| `text_sensor.h: No such file or directory` (in core entity_includes.h) | `text_sensor` in `DEPENDENCIES` but sources not compiled | Change to `AUTO_LOAD = ["text_sensor"]` — `DEPENDENCIES` requires a user-facing config block; `AUTO_LOAD` pulls in sources silently |
| `Component rubiks_solver requires component text_sensor` (config validation) | `text_sensor` listed in `DEPENDENCIES` but no `text_sensor:` block in user YAML | Same fix: use `AUTO_LOAD` not `DEPENDENCIES` for internally-created sensors |
| `[on_state] is an invalid option for [status_sensor]` | ESPHome text sensors use `on_value`, not `on_state` | Replace `on_state:` with `on_value:` in text sensor automation blocks |
| `cv.positive_time_period_milliseconds` validation error | Expects strings like `"900ms"`, not integers | Use `cv.positive_int` for raw millisecond values passed to `uint32_t` members |

### `AUTO_LOAD` vs `DEPENDENCIES`

- **`DEPENDENCIES`** — the listed component must be explicitly configured by the user in their YAML (e.g. `servo:` must be present). Config validation fails if it isn't.
- **`AUTO_LOAD`** — ESPHome automatically pulls in the component's source files and initialises it without requiring a user config block. Use this for components the custom component creates programmatically (e.g. a text sensor created via `text_sensor.new_text_sensor()` in `to_code()`).

### `CustomAPIDevice` for HA events

Inheriting from `api::CustomAPIDevice` (alongside `Component`) gives `fire_homeassistant_event()` with the correct modern implementation. The old `api::global_api_server->send_homeassistant_event()` no longer exists.

```cpp
class RubiksSolverComponent : public Component, public api::CustomAPIDevice { ... };

// fire without data:
this->fire_homeassistant_event("esphome.rubiks_solve_done");
// fire with data:
this->fire_homeassistant_event("esphome.rubiks_face_ready", {{"face", "G"}});
```

Requires `homeassistant_services: true` in the YAML `api:` block — without it the `#ifdef USE_API_HOMEASSISTANT_SERVICES` guard disables the method at compile time.

---

## Source Reference Files

`CUBOTino_Files/ESP32_files/` (in repo, gitignored from tracking — drop files here manually).

| File | Role | Ported to |
|------|------|-----------|
| `Cubotino_moves.py` | kociemba → robot move string; orientation tracking | `moves.h` |
| `Cubotino_servos.py` | servo primitives + execution loop | `rubiks_solver.cpp` |
| `Cubotino_settings.txt` | 16 servo position/timing defaults | C++ constants + `duty_to_esphome()` in `rubiks_solver.cpp` `setup()` |
| `esp32-s3-cam-rubiks.yaml` | Camera ESPHome config (starting point) | `rubiks_solver.yaml` camera section |
| `main.py` | MicroPython orchestration via UART | Replaced by HA automations |
| `servo_to_mid.py` | Assembly servo-centering utility | ESPHome button entity (planned) |
