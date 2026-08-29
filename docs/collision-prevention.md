# Preventing Competing-Move Collisions

How the top servo (flip lever) and bottom servo (turntable) are kept from colliding.

## The physical mechanism

The flip lever and turntable slot only interlock safely two ways:

- **Open** — lever fully retracted; turntable can spin freely.
- **Closed** — lever dropped through the slot, locking the top two layers while the
  turntable turns just the bottom.

A collision happens either from (1) the lever trying to close while the turntable isn't
at a slot-aligned angle (home/CW/CCW), or (2) the turntable moving before the lever has
actually finished clearing, even with correct final positions. Position correctness is
handled by the planner always using slot-aligned targets (`docs/robot.md`); everything
below is about timing.

## Two independent timing layers

**Plan-time** (`append_step_()`, `rubiks_solver.cpp`): tracks "how long does the other
servo's most recently queued move still need" (`pending_bottom_travel_ms_` /
`pending_top_travel_ms_`) and stretches the current step's duration to cover it.
Centralized here so no call site can forget it — closed a bug found twice where a
duration meant for one servo silently got applied to the other's next move.

**Dispatch-time** (`loop()`): an independent, real-wall-clock check
(`top_dispatch_ms_`/`bottom_dispatch_ms_`) right before firing a step — verifies the
*other* servo's last dispatched step should actually be done by now. Mirrors CUBOTino's
`b_servo_operable`/`b_servo_stopped` flags, but checked live instead of pre-baked into a
duration. Exists so a bug in the plan-time math, or a future call site that bypasses
`append_step_()`, can't turn into a physical collision — normal operation should never
trip it.

Both layers must stay in the same (scaled-by-`speed_mul_`) unit system; a past bug had
the plan-time bookkeeping recording the unscaled value while the pushed step used the
scaled one, silently under-protecting whenever the multiplier wasn't exactly 1.0.

## Why blocking delays aren't the answer

CUBOTino's blocking `sleep_ms()` model gives a *structural* guarantee — the interpreter
is suspended, so overlap is impossible by construction, no bookkeeping required. This
project can't adopt that: the same ESP32 also holds the WiFi connection, the HA API
link, the camera pipeline, and the display, so blocking for the seconds a multi-step
sequence takes would risk exactly the kind of WiFi/API reliability problems documented
in `docs/robot.md`'s HA integration notes. The two-layer software guard above is the
trade-off for keeping the chip responsive to everything else it has to do.

## Settle pads at the scan-return boundary

Separate from the two timing layers above: the return-to-home sequence
(`advance_scan()`'s `scan_face_idx_ >= NUM_FACES` branch) also has two short
same-position dwell steps bracketing it — one before the first flip, one after the
last. These aren't cross-servo guards; they're plain settle margin at a boundary that's
had observed jamming — the O-face close step just before, and the final flip's own
declared duration, are both calibrated-duration estimates same as everywhere else, not
physical confirmation. The pre-pad is sized to also let the `HOMING` beep finish before
the real (loud) flip motion starts.

## What actually caused the R1/L1 jams

Not a timing race at all — the bottom servo's CCW spin was under-rotating, most likely
a servo horn slipping a tooth on the spline (a repeat failure — see `docs/servo-tuning.md`
"Confirmed findings" for the full history and current value). Fixed via `"Bottom: CCW
Pos"`. If it keeps drifting further, re-seat the horn rather than keep compensating in
software.

**Related open gap**: `Cubotino_settings.txt` keeps CW/CCW release-delta and
home-overshoot as four separate parameters, allowing per-direction asymmetry. This port
shares one pair across both directions — not changed since moving CCW Pos alone was
enough, but worth splitting if asymmetric tuning is needed again.

## The limitation nothing here fixes

Neither project has real position feedback — no limit switches, no encoders. Every
layer described above can only catch misattributed or underestimated *timing*. None of
it can detect a servo that's mechanically stalled and never reaches its target — which
is exactly what the CCW issue was, caught only because a human noticed the physical
symptom, not because any software guard flagged it. Closing that gap for real needs
position-feedback hardware.
