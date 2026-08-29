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
```

One ESP32-S3 handles camera, LED, and both servos. HA handles colour detection and
solving. The two sides coordinate over the ESPHome native API via typed actions/events,
not entity-state polling.

---

## Hardware

| Block | Pins |
|-------|------|
| OV2640 camera | GPIO 6-13, 15-18 (data/clock/sync), I2C on 4/5 |
| LED (LEDC ch 0) | GPIO 3 |
| Top servo (LEDC ch 2) | GPIO 1 |
| Bottom servo (LEDC ch 4) | GPIO 43 |
| TM1638 (STB/CLK/DIO) | GPIO 14 / 41 / 42 |
| Buzzer, RTTTL (LEDC ch 6) | GPIO 44 |

UART logging sacrificed for the servo pins — USB-JTAG logger used instead
(`logger: baud_rate: 0`).

**TM1638 DIO (GPIO42) briefly looked dead but wasn't** — the display worked on a
second, otherwise identical board but not on this one, even wired directly with test
jumpers (harness ruled out) and on a completely different DIO pin (GPIO47, also
ruled out). A raw `switch: platform: gpio` toggle test (bypassing the TM1638 driver
entirely) eventually found the real cause: a stray wire in the harness shorting the
DIO line to ground. Repeatedly driving a GPIO output into that short is the likely
reason it looked electrically dead under earlier testing. Once the short was
resolved and the harness resoldered, GPIO42 tested fine again and was kept as DIO.
GPIO47 and GPIO46 were also confirmed working during this process and are kept as
spares; GPIO46 is an ESP32-S3 strapping pin (selects ROM print verbosity at boot) so
it's a lower-priority spare. GPIO48 gave no response on this board — likely reserved
for an onboard RGB LED on this board family.

**LEDC timer pairing matters**: ch0+1 share timer0, ch2+3 timer1, ch4+5 timer2, ch6+7
timer3 on ESP32-S3. Two different-frequency outputs sharing a timer pair silently break
one of them — this is why the buzzer is on ch6, not ch5 (which shares a timer with the
bottom servo on ch4). The camera uses its own internal LEDC timer for XCLK, not a user
channel.

**Servos**: standard 50Hz, extended pulse range 0.5-2.5ms (not the standard 1-2ms — these
units only just reached ~180° at standard range). `auto_detach_time: 5s` on both
(must exceed the longest step duration to avoid mid-travel dropout).

**Power**: servos need an external 5V/1A+ supply, not ESP32-S3 GPIO. Decoupling
capacitors recommended at (in priority order): the 5V branch point, near the servo
connectors, and the ESP32's 3V3/GND pins if reboots occur during active WiFi TX.

**Framework: `arduino`, not `esp-idf`** (`esp32: framework:` in `rubiks-solver.yaml`) —
inherited unexamined from the original CUBOTino camera template
(`esp32-s3-cam-rubiks.yaml`), not a deliberate choice. `esp-idf` is arguably the better
fit for a camera+PSRAM ESP32-S3 project — Arduino is itself built as a component on top
of ESP-IDF, so it adds a compatibility-layer memory overhead on top, and the OV2640
`esp32_camera` driver has a known track record of being less stable under Arduino than
native IDF (more prone to init failures and heap fragmentation under memory pressure).
Not worth switching right now though: plenty of headroom on the current build (~37%
RAM, ~53% flash used), no camera stability issues actually observed, and a framework
switch is a real behavioral change (GPIO/LEDC timing can shift subtly) that would need
re-verifying camera, servo timing, and WiFi stability all over again. Revisit only if
something concrete comes up that `esp-idf` would specifically fix — camera crashes,
memory pressure, WiFi drops under load.

**Physical mechanism**: adapted from [CUBOTino](https://www.instructables.com/CUBOTino-Autonomous-Small-3D-Printed-Rubiks-Cube-R/)
(Andrea Favero). Key adaptations: ESP32-S3+OV2640 replaces Raspberry Pi+Pi Camera and a
separate MicroPython servo controller (one device instead of two); HA dashboard
entities replace the PC GUI for calibration; a non-blocking step queue replaces blocking
`sleep_ms()` execution (see `docs/collision-prevention.md` for why, and what that
trade-off costs).

---

## Robot Primitives

| Token | Meaning | Top cover | Bottom servo |
|-------|---------|-----------|--------------|
| `F<n>` | Flip cube n times (front → bottom) | Open | Stationary |
| `S<1\|3>` | Spin full cube CW(1)/CCW(3) 90° | Open | Moves |
| `R<1\|3>` | Rotate bottom layer CW(1)/CCW(3) 90° | Closed (constrains top 2 layers) | Moves |

Example: `F1R1S3` = 1 flip, 1 CW bottom-layer rotation, 1 CCW full-cube spin. Cover must
be closed before `R` and open before `S`/`F` — the planners manage this automatically.
Correct *ordering* isn't sufficient on its own though; see
`docs/collision-prevention.md` for the timing guards needed on top of it.

---

## Starting Orientation

User places the cube: **White up, Green facing the camera (front)**. Maps directly to
kociemba's face assignment in `solver.py`: `W=U, Y=D, G=F, B=B, O=L, R=R`. Matches
CUBOTino's own default starting orientation — no remapping needed since the user always
loads the cube this way before the robot takes over, and the robot always returns it to
this exact orientation after scanning, before solving.

---

## Scan Flow

```
User places cube (White up, Green front)
  → HA calls esphome.rubiks_solver_start_scan
  → Robot moves to face 1, fires esphome.rubiks_face_ready {face}
  → HA automation: rubiks.robot_scan_face {face} (illuminate→capture→detect→store,
    calibrates after face 6) → esphome.rubiks_solver_face_scan_done
  → repeat ×6, then robot returns cube to White-up/Green-front,
    fires esphome.rubiks_scan_complete
  → HA automation: kociemba solve → esphome.rubiks_solver_execute_solution
  → Robot executes, fires esphome.rubiks_solve_done
```

Camera is top-down; cube loaded White=top, Green=front.

| Step | Face | Robot moves | kociemba face |
|------|------|-------------|---------------|
| 0 | White | (none) → close arm | U |
| 1 | Blue | open → 1 flip → close | B |
| 2 | Yellow | open → 1 flip → close | D |
| 3 | Green | open → 1 flip → close | F |
| 4 | Red | open → spin CW → 1 flip → close | R |
| 5 | Orange | open → 2 flips → close | L |
| — | Return | flip → spin_home → flip | — |

`SCAN_FACES[] = {"W","B","Y","G","R","O"}` in `rubiks_solver.cpp`, matching
`SCAN_SEQUENCE` in `const.py` — one shared list for both the manual scan button and the
robot service schema. The arm closes for every scan (camera is arm-mounted, closed arm
forms the light hood); `plan_top_cover_` isn't reset between faces so each flip planner
sees the correct carried-over state.

The return sequence deliberately avoids `rotate` — a `rotate`-based return would twist
the bottom layer 90° *after* the kociemba string was already computed from the scan,
leaving the cube one quarter-turn off from what the solution assumes. `flip → spin_home
→ flip` reaches White-up/Green-front with the turntable at home using only whole-cube
moves, verified step by step:
```
start:               U=O,F=Bl,D=Rd,Bk=G,L=W,R=Y   (turntable CW)
flip:                U=G,F=O,D=Bl,Bk=Rd            (L,R unchanged: W,Y)
spin_home(CW→HOME):  U=G,F=Y,D=Bl,Bk=W             (L,R now: O,Rd)   turntable HOME
flip:                U=W,F=G,D=Y,Bk=Bl             (L,R unchanged: O,Rd)  ← target ✓
```

kociemba string assembly (URFDLB order): `U=scan[0], R=scan[4], F=scan[3], D=scan[2],
L=scan[5], B=scan[1]`. Because the robot controls all cube movement during scanning,
`override_centre` in `detect_face_colors()` is always set from the robot's declared
face — never from classifying the centre square.

---

## Solve Flow

```
HA: kociemba solution string "U2 R1 F3 D2 ..."
  → esphome.rubiks_solver_execute_solution {solution}
  → robot_required_moves() (moves.h, C++ port of Cubotino_moves.py):
      adapt_move() maps abstract face → current physical position
      MOVES_TABLE lookup → robot primitive string
      cube_orient_update() tracks orientation change
      optimize_moves() strips cancelling S1/S3 pairs
  → plan_solution_() builds the full ServoStep queue
  → loop() drains it non-blocking
  → fires esphome.rubiks_solve_done, returns to IDLE
```

---

## HA ↔ ESP32 Interface

Typed ESPHome API actions/events, not entity-state polling.

**Actions** (`api: actions:` in `rubiks-solver.yaml`, appear in HA as
`esphome.rubiks_solver_<action>`): `start_scan`, `face_scan_done`, `execute_solution`
(`supports_response: optional`, returns `{accepted, move_count}` via `api.respond`),
`stop`, `confirm_safe_and_home`.

**Events** (fired from C++ via `fire_homeassistant_event()`, requires the component to
inherit `api::CustomAPIDevice` and `homeassistant_services: true` in YAML):
`esphome.rubiks_face_ready {face}`, `esphome.rubiks_scan_complete`,
`esphome.rubiks_solve_done`.

```cpp
class RubiksSolverComponent : public Component, public api::CustomAPIDevice { ... };
this->fire_homeassistant_event("esphome.rubiks_face_ready", {{"face", "G"}});
```

### HA automations (`ha_automations/rubiks_robot.yaml`)

Six automations bridge the two sides — the only place `esphome.rubiks_solver_*` service
names appear, so an ESPHome device rename only touches this file. Dev setup:
`configuration.yaml` uses `automation: !include_dir_merge_list ha_automations/`, with
`config/ha_automations` symlinked to this repo's `ha_automations/`.

1. **Scan coordinator** — trigger `esphome.rubiks_face_ready` → 300ms delay →
   `rubiks.robot_scan_face {face}` → `esphome.rubiks_solver_face_scan_done`.
2. **Solve dispatcher** — trigger `esphome.rubiks_scan_complete` → `rubiks.solve`
   (`response_variable`) → `esphome.rubiks_solver_execute_solution` (`response_variable`).
3. **Solve-done notification** — trigger `esphome.rubiks_solve_done` → log/notify.
4. **Robot Start Scan** — trigger `rubiks_robot_start_requested` → `esphome.rubiks_solver_start_scan`.
5. **Robot Stop** — trigger `rubiks_robot_stop_requested` → `esphome.rubiks_solver_stop`.
6. **Robot Advance Face** — trigger `rubiks_robot_advance_face_requested` → `esphome.rubiks_solver_face_scan_done`.

The `solver_status` text sensor drives the TM1638 display and RTTTL beeps for dashboard
feedback but plays no role in control flow — that's actions/events only.

---

## HA Component Integration

### What `ScanFaceButton` does (Phase 1/2, manual)

Looks up the current face via `SCAN_SEQUENCE[len(scanned_faces)]`, illuminates + captures
+ detects (with `override_centre` always set from the sequence position, never from
classification), stores it, and after face 6 runs `_async_run_calibration()`. Kept
intact alongside the robot path — useful for debugging camera crop/calibration without
hardware, and shares the same `scanned_faces` store and calibration logic (not in
conflict if not run simultaneously with a robot scan).

### `rubiks.robot_scan_face` service

Accepts `{face}`, schema-validated against `SCAN_SEQUENCE` — there is only one such
list, used both as the manual button's lookup key and the robot service's schema.
Handler in `button.py` (`async_handle_robot_scan_face`), registered in `__init__.py`.
Runs the same illuminate→capture→detect→store pipeline as `ScanFaceButton` but with the
face label supplied directly. After face 6, calibrates with
`remap=ROBOT_CAMERA_TO_KOCIEMBA_REMAP`.

### `ROBOT_CAMERA_TO_KOCIEMBA_REMAP`

Kept as identity for all six faces — rotation via `FACE_SCAN_ROTATIONS`
(`camera_processor.py`) happens *before* detection instead of an index-permutation remap
applied after. See `docs/orientation.md` for the full derivation.

---

## ESPHome Component Design

```
esphome/
  rubiks-solver.yaml              ← device config (camera, LED, servos, component ref)
  components/rubiks_solver/
    __init__.py                   ← YAML schema, defaults, codegen
    moves.h                       ← C++ port of Cubotino_moves.py (pure logic)
    rubiks_solver.h               ← component class, ServoStep type, state enums
    rubiks_solver.cpp             ← primitive builders, planner, loop() drainer
```

**Kociemba runs in HA, not the ESP32** — the two-phase pruning tables need 10-20MB RAM;
the ESP32-S3 has 8MB PSRAM. HA already assembles the cube state string, so
`kociemba.solve()` is one more line in `solver.py`. The ESP32 only needs to faithfully
execute the solution string — it never needs to understand the cube.

**Why a C++ component, not YAML lambdas**: the servo logic
(`Cubotino_servos.py`, ~900 lines) has real state — 16 position/timing settings,
multi-step primitives with conditional branching, orientation tracking across a full
move sequence. YAML lambdas can't share state cleanly; C++ classes/enums/arrays map much
more directly to the Python source.

### Key types

```cpp
enum class TopCover { OPEN, CLOSED, FLIP };
// Bottom servo position is tracked by three plan-time booleans
// (plan_b_home_, plan_b_cw_pos_, plan_b_ccw_pos_), not an enum.

struct ServoStep {
    enum Target { TOP, BOTTOM } target;
    float    position;      // ESPHome normalised -1.0..1.0
    uint32_t duration_ms;   // wait after the PREVIOUS step fires before issuing this one
};
```

### Step queue pattern

All steps for a scan or solve are pre-planned into a `std::vector<ServoStep>` before
execution begins; orientation and cover state update *as steps are planned*, not during
execution — this keeps conditional logic ("if cover is already closed, skip") at plan
time where it's easy to reason about, and keeps `loop()` itself trivial: check the timer,
fire the next step.

`loop()` runs every ~16ms and must never block — `sleep_ms()` throughout the MicroPython
source becomes timer checks here, using `App.get_loop_component_start_time()` (cached
per tick) rather than `millis()`. `step_start_ms_ = 0` when execution begins makes step 0
fire immediately regardless of its own `duration_ms` — travel time belongs on step 1, not
step 0. The component calls `disable_loop()` whenever idle (`IDLE`/`SCAN_WAIT`) so it's
removed from the active loop entirely, re-entering via `enable_loop()` when a scan/solve
starts.

**Not using `transition_length`**: ESPHome's servo component has a smoothing option, but
it snaps to idle at full speed on the first call after reboot and gives no completion
callback — explicit step durations in the queue give the timing control this robot needs.

### Safety and timing

Full detail lives in dedicated docs rather than duplicated here:
- **Cross-servo collision prevention** (plan-time + dispatch-time timing guards, why
  blocking delays aren't viable here): `docs/collision-prevention.md`.
- **Unclean-reset boot gate + `needs_confirm_before_move_`**: on a crash/brownout/
  watchdog reset, `setup()` skips the auto-home glide, shows `CHK ARM`, and requires
  `confirm_safe_and_home()` before any move — same requirement now applies after
  `stop()` interrupts anything non-`IDLE`. See `docs/features.md` "Safety / state
  machine".

### Servo settings conversion

`Cubotino_settings.txt` stores raw MicroPython PWM duty (0-1023 at 50Hz).
`duty_to_esphome()` converts to ESPHome's -1.0..1.0:

```cpp
static float duty_to_esphome(int duty) {
    float pct = duty / 1023.0f * 100.0f;
    return (pct - 7.5f) / 5.0f;   // -1.0..1.0 for 2.5%..12.5%, idle=7.5%
}
```

`__init__.py` only handles schema validation and codegen — all position arithmetic is
in C++.

**Bottom CCW position has needed recalibrating multiple times** — likely the servo horn
slipping a tooth on the spline, not a software issue. Current value and full history:
`docs/servo-tuning.md` ("Confirmed findings" / "Current values") — treat that doc, not
this one, as the source of truth for calibration numbers so they don't go stale in two
places.

---

## ESPHome Build Gotchas

| Symptom | Cause | Fix |
|---------|-------|-----|
| `'APIServer' has no member 'send_homeassistant_event'` | Removed in ESPHome 2026.x | Inherit `api::CustomAPIDevice`, call `this->fire_homeassistant_event()` |
| `fire_homeassistant_event() requires 'homeassistant_services: true'` | Guard disabled at compile time | Add `homeassistant_services: true` under `api:` |
| `text_sensor.h: No such file or directory` | `text_sensor` in `DEPENDENCIES` but sources not compiled | Use `AUTO_LOAD = ["text_sensor"]` instead |
| `Component rubiks_solver requires component text_sensor` | Same as above, `DEPENDENCIES` needs a user-facing config block | Same fix |
| `[on_state] is an invalid option` | ESPHome text sensors use `on_value` | Replace `on_state:` with `on_value:` |
| `cv.positive_time_period_milliseconds` validation error | Expects `"900ms"` strings, not raw ints | Use `cv.positive_int` for raw ms values into `uint32_t` members |

`DEPENDENCIES` requires the user to explicitly configure that component in their own
YAML; `AUTO_LOAD` pulls in a component's sources programmatically without that
requirement — use `AUTO_LOAD` for anything the custom component creates itself (e.g. a
text sensor via `text_sensor.new_text_sensor()` in `to_code()`).

---

## Source Reference Files

`CUBOTino_Files/ESP32_files/` (gitignored, drop files here manually).

| File | Role | Ported to |
|------|------|-----------|
| `Cubotino_moves.py` | kociemba → robot move string; orientation tracking | `moves.h` |
| `Cubotino_servos.py` | servo primitives + execution loop | `rubiks_solver.cpp` |
| `Cubotino_settings.txt` | 16 servo position/timing defaults | C++ constants + `duty_to_esphome()` |
| `esp32-s3-cam-rubiks.yaml` | Camera ESPHome config (starting point) | `rubiks-solver.yaml` camera section |
| `main.py` | MicroPython orchestration via UART | Replaced by HA automations |
| `servo_to_mid.py` | Assembly servo-centering utility | `sweep_top_servo`/`sweep_bottom_servo` scripts |
