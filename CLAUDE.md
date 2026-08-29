# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A two-sided system that scans a Rubik's cube with a fixed ESP32-CAM, solves it via
kociemba, and (optionally) physically executes the solution with a CUBOTino-derived
robot arm:

- `custom_components/rubiks/` — a HACS Home Assistant integration (Python). Camera
  capture, CIELAB colour detection, calibration, and the kociemba solve pipeline.
- `esphome/components/rubiks_solver/` — an external ESPHome C++ component running on a
  second ESP32-S3. Drives the two robot servos (flip lever + turntable) to scan faces
  and execute solved moves.

The two sides talk over the ESPHome native API (typed actions/events), bridged by
`ha_automations/rubiks_robot.yaml` — never entity-state polling.

## Commands

**Python (from repo root)**
```bash
pytest                          # full suite (testpaths is custom_components/rubiks/tests)
pytest custom_components/rubiks/tests/test_solver.py -v
pytest custom_components/rubiks/tests/test_camera_processor.py::test_name -v   # single test
ruff check .                    # lint
ruff format .                   # format
mypy custom_components/rubiks   # type check
```

**ESPHome firmware (from `esphome/`)**
```bash
esphome compile rubiks-solver.yaml   # verify the C++ component builds; catches real bugs, do this after any .cpp/.h change
esphome logs rubiks-solver.yaml      # stream live device log
```
There is no automated test harness for the C++ side — verification is compiling clean
plus the on-device diagnostic test buttons (single-move `execute_solution()` calls,
planned test-cycle buttons) described in `docs/robot.md`.

**Dev environment**: `custom_components/rubiks` is symlinked into a local HA core
checkout for live testing; Python edits need an HA restart (or integration reload) to
take effect. ESPHome changes need a reflash.

## Architecture — read `docs/` before making non-trivial changes

The docs were rewritten as a clean, current-state reference (not a changelog) — trust
them over any assumption, and update them alongside behavioral changes rather than letting them drift:

- `docs/spec.md` — HA integration: file structure, detection/calibration pipeline
  design decisions (why CIELAB not HSV, why L is weighted *above* a/b, why majority
  vote not median), shared `hass.data` schema, services/events.
- `docs/robot.md` — ESP32 robot: hardware pinout, scan/solve flow, HA↔ESP32 interface,
  ESPHome component internals (step-queue pattern, why non-blocking, why a C++
  component instead of YAML lambdas).
- `docs/orientation.md` — the camera/cube orientation model: scan sequence, per-face
  raw camera orientation, kociemba face mapping, required rotations. Get this wrong and
  detected colours land on the wrong sticker.
- `docs/collision-prevention.md` — how the two robot servos are kept from colliding
  (plan-time + dispatch-time timing guards) and why a blocking execution model (like
  the original CUBOTino) isn't viable given everything else this ESP32 has to do.
- `docs/features.md` — current feature/entity inventory and known limitations.
- `docs/servo-tuning.md` — what each servo calibration number controls, how to
  diagnose a bad value, and the current tuning state (source of truth for calibration
  numbers — other docs point here instead of repeating them).
- `docs/tm1638.md` — the display/buzzer/LEDs: pins, status→display/beep/LED mapping,
  physical-button actions, pipelined features.
- `docs/archive/` — dated snapshots of the docs from before the 2026-08-15 rewrite, if
  historical context on a specific past decision is needed.

`CUBOTino_Files/ESP32_files/` (untracked, drop in manually) is Andrea Favero's original
CUBOTino source — the ESPHome component is a deliberate port of `Cubotino_servos.py`/
`Cubotino_moves.py`. When touching servo timing or move-translation logic, diff against
these first; several real bugs in this project were found by comparing behavior against
the original rather than by reading the port in isolation.

## Non-obvious conventions

- **`SCAN_SEQUENCE`** (`const.py`) is the single source of truth for face scan order,
  shared by the manual scan button, the robot service schema, and the ESP32's
  `SCAN_FACES[]` (which must stay in the same order independently, since the ESP32
  doesn't import Python). Red/Orange ordering here has been a repeated source of bugs —
  don't change it without the derivation in `docs/orientation.md`.
- **Servo calibration is not hardcoded.** Every position/timing constant lives in an HA
  number entity (`rubiks-solver.yaml`, `restore_value: true`), tunable live on the
  dashboard. Header defaults in `rubiks_solver.h` are fallbacks, not the values actually
  in use — check the live entity state before assuming a default is what's running.
- **Kociemba runs in HA, not the ESP32** — the two-phase pruning tables need 10-20MB
  RAM; the ESP32-S3 has 8MB PSRAM. The ESP32 only ever executes a move string it's
  given; it has no cube-solving logic of its own.
- **No physical position feedback anywhere** — neither this project nor the original
  CUBOTino has servo encoders or limit switches. All timing is calibrated-duration
  estimates. A move can complete "successfully" from the firmware's perspective while
  the servo silently under-travelled — this class of bug won't jam anything and won't
  show up in logs, only in an incorrect cube state after the fact.
