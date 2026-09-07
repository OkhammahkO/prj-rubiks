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
[Andrea Favero's own settings reference](../CUBOTino_Files/ESP32_files/Cubotino_settings.md)
(local copy, gitignored) — his **Default**/**AF** columns (Default = stock, AF = his own
tuned unit) are kept here for context when diffing behavior, not as numbers to copy onto
this build's different camera/servos. For what's actually live *here*, see "Current
values" below (points at the **Report: Servo Parameters** dashboard button, not a stale
hardcoded number) — this table is about completeness against the original, including the
handful of his parameters this port doesn't have an equivalent for.

### Top servo (flip lever) — positions

| HA entity | C++ member | Plain English | Original name | Default | AF |
|---|---|---|---|---|---|
| `Top: Flip Pos` | `d_t_flip_` → `t_flip_v_` | Same servo as Open/Close Pos below, but at this position it swings a separate, smaller flip lever up through the turntable's slots to tip the cube forward (front face → bottom) — see `docs/robot.md` "Physical Mechanism" | `t_servo_flip` | -0.9 | -0.9 |
| `Top: Open Pos` | `d_t_open_` → `t_open_v_` | The "rest"/idle position — cover raised clear above the cube, *and* the flip lever retracted below the turntable (not poking through it). Required before the turntable can spin freely | `t_servo_open` | -0.32 | -0.32 |
| `Top: Close Pos` | `d_t_close_` → `t_close_v_` | Lever lowered onto the cube, constraining the top two layers — required before a bottom-layer `Rotate` | `t_servo_close` | 0 | 0 |
| *not implemented* | — | Andrea's arm position for reading a face with an arm-mounted PiCamera. Not applicable here — this build uses a fixed top-mounted camera, so face capture doesn't depend on arm position | `t_servo_read` | -0.5 | -0.5 |

### Top servo — timings (ms, between the positions above)

| HA entity | C++ member | Plain English | Original name | Default | AF |
|---|---|---|---|---|---|
| `Top: Flip-Close` | `t_flip_to_close_time_` | Travel time, Flip position → Close position | `t_flip_to_close_time` | 600 | 380 |
| `Top: Close-Flip` | `t_close_to_flip_time_` | Travel time, Close position → Flip position (reverse direction, separate constant since geometry/gravity differ) | `t_close_to_flip_time` | 600 | 420 |
| `Top: Flip-Open` | `t_flip_open_time_` | Travel time between Flip and Open positions, either direction | `t_flip_open_time` | 500 | 340 |
| `Top: Open-Close` | `t_open_close_time_` | Travel time between Open and Close positions, either direction — the shortest top-servo move, since Open/Close sit close together (only Flip is the far extreme) | `t_open_close_time` | 300 | 100 |

### Top servo — release (currently inert)

| HA entity | C++ member | Plain English | Original name | Default | AF |
|---|---|---|---|---|---|
| `Top: Release Offset` (commented out in YAML) | `d_t_rel_offset_` → `t_rel_v_ = t_close_v_ - offset` | Small pull-back from Close to relieve clamping pressure on the cube — the top-servo equivalent of `Extra Sides` below | `t_servo_rel_delta` | 0.02 | 0.06 |
| *not implemented* | — | Time for the release pull-back above — no dedicated HA entity here, since Release Offset is disabled this reuses whichever cover-transition duration is already in play (see `solver()`'s docstring in `rubiks_solver.cpp`) | `t_rel_time` | 200ms | 0ms |

Release Offset sits at `0` (a no-op — `t_rel_v_` currently equals `t_close_v_` exactly)
since the entity was never uncommented — matches Andrea's own Default of `0` too, so this
isn't a regression, just an unfinished feature (see `docs/features.md`). Worth noting his
own AF-tuned value is `0` as well, for both the top *and* bottom release — see the
`Bottom: Release` row below.

### Bottom servo (turntable) — positions

| HA entity | C++ member | Plain English | Original name | Default | AF |
|---|---|---|---|---|---|
| `Bottom: CCW Pos` | `d_b_ccw_` → `b_ccw_v_` | Raw full ~90° CCW endpoint from home. Used directly as `Rotate`'s CCW target, and combined with `Extra Sides` to form `Spin`'s CCW resting point | `b_servo_CCW` | -1 | -1 |
| `Bottom: Home Pos` | `d_b_home_` → `b_home_v_` | Center/neutral resting position — the reference point everything else (CCW/CW Pos, Extra Home) is measured relative to | `b_home` | 0 | 0 |
| `Bottom: CW Pos` | `d_b_cw_` → `b_cw_v_` | Raw full ~90° CW endpoint from home, mirror of CCW Pos | `b_servo_CW` | 1 | 1 |
| `Bottom: Extra Sides` | `d_b_extra_sides_` | Delta subtracted (CW) / added (CCW) from CW/CCW Pos to get the **release** position (`b_cw_rel_v_`/`b_ccw_rel_v_`) — a small back-off from the raw extreme that relieves tension between cube, holder, and cover. Used as `Spin`'s actual resting point, and as `Rotate`-out's second (short) step. Andrea's original has separate CW/CCW values (`b_rel_CCW`/`B_rel_CW`); this port shares one across both — see "Known gap" below | `b_rel_CCW` / `B_rel_CW` | 0.04 / 0.04 | 0.06 / 0.06 |
| `Bottom: Extra Home` | `d_b_extra_home_` | Delta from Home Pos used for the **intermediate overshoot waypoint** in `Rotate`-*home*'s first step only. Does **not** affect the final resting position — that's always exactly `Home Pos` (see confirmed finding below). Same one-shared-value simplification as Extra Sides | `b_extra_home_CCW` / `b_extra_home_CW` | 0.12 / 0.12 | 0.1 / 0.1 |

### Bottom servo — timings (ms)

| HA entity | C++ member | Plain English | Original name | Default | AF |
|---|---|---|---|---|---|
| `Bottom: Spin` | `b_spin_time_` | Duration for every `plan_spin_()` move — whole-cube spin, cover open, both spin-out and spin-home | `b_spin_time` | 700 | 440 |
| `Bottom: Rotate` | `b_rotate_time_` | Duration for the **long** leg of every `plan_rotate_()` call — home→target on rotate-out, target→near-home on rotate-home. One shared value for both CW and CCW | `b_rotate_time` | 800 | 540 |
| `Bottom: Release` | `b_rel_time_` | Duration for the **short** leg of every `plan_rotate_()` call — the final few-unit settle to the exact resting position, both directions. This build needs far more than either of Andrea's values (~500ms vs his 0-200ms) — looks like servo/gear-train stiction rather than a bug, see the tuning log below | `b_rel_time` | 200 | 0 |

### Not tunable per-servo in this build

| Original name | Default | AF | Why not |
|---|---|---|---|
| `t_min_pulse_width` / `t_max_pulse_width` | 1 / 2 | 1 / 2 | Fixed in this build's ESPHome `servo:` config (`min_level`/`max_level`) for both servos, not an HA entity |
| `b_min_pulse_width` / `b_max_pulse_width` | 1 / 2 | 0.98 / 1.98 | Same — fixed in ESPHome config |
| `t_srv_pw_range` / `b_srv_pw_range` | 'small' / 'small' | 'small' / 'small' | Named pulse-width-range presets from Andrea's own calibration tooling. This build's ESPHome config states the range directly instead of picking a preset |

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
- **`Bottom: CCW Pos` at 10 was silently clamped.** ESPHome's `Servo::write()` clamps
  every value to `[-1.0, 1.0]` before output. `CCW Pos=10` computed to -1.304 (out of
  range) — clamped to exactly -1.0, the same output as `Bottom: Extra Sides`' release
  position (also clamped, since 10+extra_sides still couldn't clear the boundary with
  extra_sides capped at 15). CCW rotate and CCW release were physically identical moves
  until this was found — a genuine bug in its own right. Tried `CCW Pos=28` (just
  inside range, restoring a real distinct release position) — didn't move the separate
  `Bottom: Release` timing-floor issue below, so **reverted back to 10** (see tuning
  log). The clamping bug itself is still real and could resurface if CCW Pos is ever
  lowered again for an unrelated reason — worth re-checking the computed value against
  ±1.0 whenever it changes.
- **The `Bottom: Release` floor (~500ms) is a genuine servo characteristic, not a
  bug.** Doubling `Extra Sides`/`Extra Home` (4→8, 2→4) and fixing the CCW clamp above
  both landed cleanly but didn't move the floor. Confirmed it's not distance-related
  either: CW was never clamped (always had a real, distinct release position) and
  still hits the same ~500ms floor as CCW. Points to a stiction/static-friction
  property of this servo's gear train — it needs sustained torque for a while before
  it actually turns, regardless of how far it's asked to travel. Physically inspected
  the bottom servo's gear train/horn (same spot as the earlier CCW Pos slip) — no
  fault found, so **500ms is accepted as this hardware's real floor**, not something
  left to keep chasing via tuning.
- **Scan flips did an unwanted extra reversal.** `plan_flip_()` always auto-opened the
  cover after the last flip unless a rotate immediately followed — during scanning the
  caller closes the cover again right after anyway, so every scan flip did
  FLIP→OPEN→CLOSE (two reversals) instead of FLIP→CLOSE. Looked like "the flip cuts
  short and goes back down." Fixed by adding a scan-only `next_token=='X'` sentinel to
  `plan_flip_()` that leaves the arm at FLIP for the caller's own
  `plan_ensure_cover_closed_()` to finish directly. Doesn't affect solve/scramble —
  `'X'` never appears in a real kociemba move string.
- **A redundant top "release" step was costing a full leg's duration for zero
  motion.** `plan_ensure_cover_closed_()` and `plan_flip_()`'s close-then-rotate branch
  both queued a second top-servo step at the release position — but with `Top: Release
  Offset` at its permanent `0`, that position is identical to Close, so the step never
  actually moved anything. Now skipped whenever the offset is `0` (i.e. always, until
  that feature is finished) — removes one full `Top: Open-Close`/`Top: Flip-Close`
  duration of dead time per bottom-layer turn, at zero cost.

## Current values

Numbers here go stale the moment anyone retunes a slider, so none are duplicated in
this doc anymore. To see what's actually live right now: press **Report: Servo
Parameters** on the dashboard, which calls `dump_config()` and logs every raw duty
setting, computed servo position, and timing value in one shot — read that log instead
of trusting any number written here. If you retune anything, also write the new value
back into the YAML's `initial_value` once confirmed, so a fresh flash doesn't regress
behind the dashboard.

## Tuning log

Running record of specific value changes while this is still being dialled in — newest
first. Once tuning settles down, this can be trimmed back to just the current values
note above; until then it's cheaper to log a change here than to lose track of why a
number is what it is.

- **2026-09-06** — YAML `initial_value`s synced to live dashboard state after the
  speed-up pass below: `Top: Flip-Close` 400→450, `Top: Close-Flip` 400→550,
  `Top: Open-Close` 300→**100** (matches Andrea's own AF-tuned value exactly),
  `Bottom: Home Pos` 77→76, `Bottom: Extra Sides` 4→8, `Bottom: Extra Home` 2→4,
  `Bottom: Release` 700→550, `Bottom: Spin` 700→400, `Bottom: Rotate` 700→500. Compiled
  clean; a fresh flash now boots straight into the currently-confirmed values.
- **2026-09-06** — `Top: Close-Flip` 400→**500ms**, `Top: Flip-Open` 300→**400ms**.
  Fixed scan flips cutting short (see "Confirmed findings" — the redundant-open-step
  bug had masked whether duration was ever the real problem; once that was fixed, a
  clean retest showed it was). Found via push-high-then-dial-back: tested 800/600ms
  first to confirm duration was the lever, then walked both down until they held.
- **2026-09-06** — `Bottom: CCW Pos` 10→28→**10 (reverted)**. Tried un-clamping the
  CCW release position (see "Confirmed findings"); didn't move the `Bottom: Release`
  timing floor, so reverted rather than keep the (small) reduction in CCW travel for
  no benefit.

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
