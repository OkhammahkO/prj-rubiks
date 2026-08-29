# Servo Tuning Reference

Practical companion to `docs/robot.md` and `docs/collision-prevention.md` — what each
calibration number actually controls, how to diagnose a bad value, and the current
tuning state. Update the table below as values change; this doc is meant to stay a
living reference, not a changelog (see `docs/archive/` for session history).

## Diagnostic method

Worked reliably across every servo issue found this session, in this order:

1. **Isolate with the narrowest test button that reproduces it** — a single-leg test
   (`test_rotate_cw_home()`, `test_spin_ccw_home()`, etc.) before a composite move
   (`D1`, `U1`...) before a full scan. Composite moves make it hard to tell which
   sub-step is actually at fault.
2. **Rule out time before position.** Push the relevant duration well above its current
   value and retest. If that fixes it, it was genuinely under-timed — dial back to find
   the minimum. If it makes *no* difference, time was never the bottleneck — stop
   touching durations and look at the target position instead.
3. **Rule out mechanical before software.** Physically check for play/slippage (the
   bottom servo horn has needed re-seating before — see `docs/robot.md`). If the
   mechanism is solid, the cause is a wrong number, not a wrong assumption about what
   "should" be enough time.
4. **Remember CW and CCW are asymmetric but often share one constant.** A value tuned
   against one direction's required distance isn't guaranteed to cover the other — see
   "Known gap" below. If one direction works and its mirror doesn't, check whether the
   shared constant simply needs to cover the *larger* of the two distances.
5. **Check whether the parameter you're tuning actually governs the thing you're
   observing.** More than one round of tuning here targeted the wrong number because it
   *sounded* related but didn't actually touch the observed symptom — see "Confirmed
   findings" below for two examples. Trace the actual code path
   (`plan_rotate_()`/`plan_spin_()` in `rubiks_solver.cpp`) before assuming a name
   implies function.

## Calibration entity glossary

Every entry cross-checked against the current `rubiks_solver.cpp`/`.h` and against
`Cubotino_settings.txt`'s own parameter names and `Info` column. "Raw tuple index" is
that parameter's position in the settings file's one-line tuple
(`(54,68,76,0,900,1000,800,300,51,76,101,2,3,1100,1200,100,'small','small')`) — the
source our header defaults were originally seeded from.

### Top servo (flip lever) — positions

| HA entity | C++ member | Plain English | Original name (raw tuple idx) |
|---|---|---|---|
| `Top: Flip Pos` | `d_t_flip_` → `t_flip_v_` | Where the lever goes to physically flip the cube (front face → bottom) | `t_servo_flip` (0) |
| `Top: Open Pos` | `d_t_open_` → `t_open_v_` | Lever fully raised, clear of the cube and turntable — the "rest"/idle position, and required before the turntable can spin | `t_servo_open` (1) |
| `Top: Close Pos` | `d_t_close_` → `t_close_v_` | Lever lowered onto the cube, constraining the top two layers — required before a bottom-layer `Rotate` | `t_servo_close` (2) |

### Top servo — timings (ms, between the positions above)

| HA entity | C++ member | Plain English | Original name (raw tuple idx) |
|---|---|---|---|
| `Top: Flip-Close` | `t_flip_to_close_time_` | Travel time, Flip position → Close position | `t_flip_to_close_time` (4) |
| `Top: Close-Flip` | `t_close_to_flip_time_` | Travel time, Close position → Flip position (reverse direction, separate constant since geometry/gravity differ) | `t_close_to_flip_time` (5) |
| `Top: Flip-Open` | `t_flip_open_time_` | Travel time between Flip and Open positions, either direction | `t_flip_open_time` (6) |
| `Top: Open-Close` | `t_open_close_time_` | Travel time between Open and Close positions, either direction — the shortest top-servo move, since Open/Close sit close together (only Flip is the far extreme) | `t_open_close_time` (7) |

### Top servo — release (currently inert)

| HA entity | C++ member | Plain English | Original name (raw tuple idx) |
|---|---|---|---|
| `Top: Release Offset` (commented out in YAML) | `d_t_rel_offset_` → `t_rel_v_ = t_close_v_ - offset` | Small pull-back from Close to relieve clamping pressure on the cube — the top-servo equivalent of `Extra Sides` below | `t_servo_rel_delta` (3) |

Sits at `0` (a no-op — `t_rel_v_` currently equals `t_close_v_` exactly) since the entity
was never uncommented. Matches `Cubotino_settings.txt`'s own default of `0` too, so this
isn't a regression, just an unfinished feature — see `docs/features.md`.

### Bottom servo (turntable) — positions

| HA entity | C++ member | Plain English | Original name (raw tuple idx) |
|---|---|---|---|
| `Bottom: CCW Pos` | `d_b_ccw_` → `b_ccw_v_` | Raw full ~90° CCW endpoint from home. Used directly as `Rotate`'s CCW target, and combined with `Extra Sides` to form `Spin`'s CCW resting point | `b_servo_CCW` (8) |
| `Bottom: Home Pos` | `d_b_home_` → `b_home_v_` | Center/neutral resting position — the reference point everything else (CCW/CW Pos, Extra Home) is measured relative to | `b_home` (9) |
| `Bottom: CW Pos` | `d_b_cw_` → `b_cw_v_` | Raw full ~90° CW endpoint from home, mirror of CCW Pos | `b_servo_CW` (10) |
| `Bottom: Extra Sides` | `d_b_extra_sides_` | Delta subtracted (CW) / added (CCW) from CW/CCW Pos to get the **release** position (`b_cw_rel_v_`/`b_ccw_rel_v_`) — a small back-off from the raw extreme that relieves tension between cube, holder, and cover. Used as `Spin`'s actual resting point, and as `Rotate`-out's second (short) step | `b_rel_CCW`/`B_rel_CW` (11) |
| `Bottom: Extra Home` | `d_b_extra_home_` | Delta from Home Pos used for the **intermediate overshoot waypoint** in `Rotate`-*home*'s first step only. Does **not** affect the final resting position — that's always exactly `Home Pos` (see confirmed finding below) | `b_extra_home_CCW`/`b_extra_home_CW` (12) |

### Bottom servo — timings (ms)

| HA entity | C++ member | Plain English | Original name (raw tuple idx) |
|---|---|---|---|
| `Bottom: Spin` | `b_spin_time_` | Duration for every `plan_spin_()` move — whole-cube spin, cover open, both spin-out and spin-home | `b_spin_time` (13) |
| `Bottom: Rotate` | `b_rotate_time_` | Duration for the **long** leg of every `plan_rotate_()` call — home→target on rotate-out, target→near-home on rotate-home. One shared value for both CW and CCW | `b_rotate_time` (14) |
| `Bottom: Release` | `b_rel_time_` | Duration for the **short** leg of every `plan_rotate_()` call — the final few-unit settle to the exact resting position, both directions | `b_rel_time` (15) |

### Global

| HA entity | C++ member | Plain English |
|---|---|---|
| `Speed Multiplier` | `speed_mul_` | Scales every step's duration uniformly at plan time — applied last, after all other duration math including the cross-servo stretch in `append_step_()`. No original-project equivalent; added for this port. |

## Confirmed findings this session

- **`plan_rotate_()`'s two steps were swapped for a long time** (found via comparing
  against `Cubotino_servos.py`) — the real long traverse was getting `Bottom: Release`-
  scale time and vice versa. Fixed 2026-08-15. If you're referencing old notes/logs from
  before that date, the duration pairing described there is wrong.
- **`Bottom: Extra Home` does not affect the final rotate-home resting position** — only
  an intermediate waypoint on the way there. The actual final-approach bottleneck is
  `Bottom: Release`. Confirmed empirically: `Extra Home` swept 2→15 with zero visible
  change in the final position; `Bottom: Release` 100ms→500ms fixed it immediately.
- **`Bottom: CCW Pos` and `Bottom: CW Pos` both needed moving further from home than
  their original-project defaults** — likely the servo horn slipping a tooth on the
  spline (documented happening once before in `features.md`), confirmed *not* a current
  loose-horn issue by physical check as of this session.
- **`Bottom: Rotate` is shared across CW/CCW but the two directions need different
  amounts** — CCW's home-to-target distance is larger than CW's, so a value tuned
  against CW's out-leg may under-serve CCW's.
- **`Bottom: CCW Pos` moved twice** — 51→40→10, with the entity's `min_value` widened
  each time it got hit (now 5). Each move was confirmed against a real test, not
  guessed; if it needs to go further still, that's a stronger signal for re-seating the
  horn than for continuing to widen the floor.

## Current values

The YAML's `initial_value` for every entity below is now kept in sync with the
last-confirmed-working live value (updated 2026-08-15) — treat the YAML itself as the
source of truth rather than duplicating numbers here, since they'll only go stale again.
Current known-good set: `CCW Pos=10`, `CW Pos=110`, `Home Pos=77`, `Extra Sides=4`,
`Extra Home=2`, `Spin=700ms`, `Rotate=700ms`, `Release=700ms`, `Speed Multiplier=1.0`,
`Top: Close Pos=77`, other Top values unchanged from original defaults. If you retune
anything, write the new value back into the YAML's `initial_value` once confirmed so a
fresh flash doesn't regress behind the dashboard.

## Believed-home safeguard

`binary_sensor.rubiks_solver_believed_home` — optimistic, derived from the commanded
move sequence (`plan_top_cover_`/`plan_b_home_`), not real position feedback. False the
instant any step is queued; recomputed true/false only when a sequence completes, based
on whether it ended at cover-open + bottom-home. `test_scan_cycle()` is the clearest
case where it goes false without anything being wrong — it deliberately parks at a scan
face, not home.

`start_scan()` and `execute_solution()` hard-block if this is false, same pattern as
`needs_confirm_before_move_` — refuse and require `confirm_safe_and_home()` first,
rather than silently assuming home like they used to.

## Known gap

CW/CCW share one `Bottom: Rotate` / `Bottom: Extra Sides` / `Bottom: Extra Home` value
each, rather than four independent per-direction parameters like
`Cubotino_settings.txt` (`b_rel_CCW`/`B_rel_CW`, `b_extra_home_CCW`/`b_extra_home_CW`).
Current approach is to tune the shared value to comfortably cover the *larger* of the
two directions' needs, accepting harmless slack on the smaller one. Splitting into
direction-specific pairs remains a possible future change if this stops being good
enough — see `docs/collision-prevention.md`.
