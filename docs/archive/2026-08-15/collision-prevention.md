# Preventing Competing-Move Collisions

How this project keeps the top servo (flip lever) and bottom servo (turntable) from
colliding with each other, what's actually been fixed, and what limitations remain.
Written up as a standalone reference because the topic spans mechanical design, two
separate layers of software timing guards, and a real bug that connected them —
scattered across `robot.md`/`features.md` otherwise.

## The physical mechanism

The flip lever and turntable slot only interlock safely two ways:

- **Open** — lever fully retracted, clear of the turntable; the turntable can spin freely.
- **Closed** — lever dropped through the slot, locking the top two layers while the
  turntable turns just the bottom layer.

A collision happens one of two ways:

1. **Wrong position** — the lever tries to close while the turntable isn't sitting at a
   slot-aligned angle (home / CW / CCW). It lands on the solid rim instead of the slot.
2. **Wrong timing** — the turntable starts moving before the lever has actually finished
   clearing, even though both are heading to the *correct* final positions. Two
   independently-timed servos with no shared clock can race each other here.

Everything below is about preventing #2. Position correctness (#1) is handled by the
scan/solve move planner always using slot-aligned targets — see `docs/robot.md`.

## Software timing safeguards — two layers

**Layer 1 — plan-time duration stretching**, in `append_step_()`
(`rubiks_solver.cpp:362`). Every queued step passes through this single choke point,
which tracks "how long does the *other* servo's most recently queued move still need"
(`pending_bottom_travel_ms_` / `pending_top_travel_ms_`, `rubiks_solver.h:143`) and
stretches the current step's duration to cover it. Centralizing this closed a bug found
twice earlier in the project, where a duration meant for one servo's move was silently
being applied to the other servo's *next* move instead — each call site had to remember
the guard manually, and two of them (`plan_flip_()`, `plan_ensure_cover_open_()`) didn't.

**Layer 2 — dispatch-time verification**, in `loop()` (`rubiks_solver.cpp:157-177`,
fields at `rubiks_solver.h:156`). Independent of the plan-time math above: right before
firing a step, checks in real wall-clock time whether the *other* servo's last
**dispatched** step should actually be finished by now (`top_dispatch_ms_` /
`bottom_dispatch_ms_`). If not, it holds and retries next tick, logging a warning. This
mirrors the original CUBOTino firmware's `b_servo_operable` / `b_servo_stopped` flags
(`Cubotino_servos.py`) — "don't move me until the other side is confirmed settled" — but
checked live against the clock rather than pre-baked into a duration at plan time.

Layer 2 exists so that if layer 1's bookkeeping is ever wrong — a bug, a future call site
that bypasses `append_step_()`, stale state after an abort — the physical collision it
protects against still can't happen. It's meant to never actually trigger in normal
operation.

### The bug that connected them

`append_step_()` was recording the "owed" travel time using the **unscaled** duration,
while the actual queued step ran at `duration × speed_mul_`. Whenever the speed
multiplier isn't exactly `1.0` (it's currently `1.1`, nudged up during the R1/L1 jam
investigation before the real cause was found), layer 1 under-protected relative to
reality — and layer 2 would silently compensate with an unplanned pause rather than let
a collision happen. That's the most likely explanation for the "something a bit odd"
hesitation seen after the post-scan return sequence. Fixed by scaling before recording
the owed value, not after.

## What actually caused the R1/L1 jams — not timing at all

Despite all of the above, the real cause of the jams was mechanical, not a timing race:
the bottom servo's CCW spin was under-rotating, most likely the servo horn slipping a
tooth on the spline — the same failure mode `features.md` already recorded once before
(fixed then via a physical spline adjustment). Diagnosed by isolating with
`test_spin_ccw_home()` alone: ruled out time (raising `b_spin_time_` didn't help) and
ruled out a hard obstruction (increasing the CCW target *did* fix it, meaning it was
under-commanded travel, not a blockage).

Fixed in software this time — `"Bottom: CCW Pos"` moved from 51 to 40 — but worth
watching. If that value keeps needing to move further over time, the horn needs
re-seating, not more software compensation. See `docs/robot.md` "Bottom CCW
recalibration" for the full diagnosis.

### A related, still-open gap

The original CUBOTino's settings format (`Cubotino_settings.txt`) keeps CW/CCW release
delta and home-overshoot as **four separate parameters**
(`b_rel_CCW`/`B_rel_CW`, `b_extra_home_CCW`/`b_extra_home_CW`) specifically to allow this
kind of per-direction asymmetry. This port shares one `d_b_extra_sides_` and one
`d_b_extra_home_` pair across both directions — so there's currently no way to tune
CCW's release/overshoot independently of CW's. Not changed, since moving CCW Pos alone
was enough this time, but worth splitting into direction-specific pairs if asymmetric
tuning is ever needed again.

## Position-uncertainty gap — separate issue, now fixed

`start_scan()` and `execute_solution()` used to unconditionally assume the servos were
at home/open when planning, guarded only by `state_ == IDLE` — which confirms nothing is
currently queued, not that the servos are actually where assumed. An abort mid-motion
(`stop()`) or an unclean reset at boot could leave things anywhere, and the next command
would still blindly assume home — directly risking the "lever closes over a
non-slot-aligned turntable" collision mode above.

Fixed with `needs_confirm_before_move_` (`rubiks_solver.h:179`): set whenever position
becomes uncertain (an unclean reset, or `stop()` interrupting anything that wasn't
already `IDLE`), and checked by `start_scan()`/`execute_solution()`
(`rubiks_solver.cpp:199`, `:292`), refusing until `confirm_safe_and_home()` is called.
This also closed a pre-existing gap: the `CHK ARM` unclean-reset display was previously
advisory only — `state_` was already `IDLE` by the time a human could react, so nothing
in the state machine actually stopped a command from running immediately after a crash.

## The one limitation nothing here fixes

Neither the original CUBOTino nor this port has any real physical position feedback —
no limit switches, no encoders, nothing beyond what's internal to a standard positional
servo. Every layer of protection described above — CUBOTino's flags, this project's
plan-time duration math, the dispatch-time guard — can only catch **misattributed or
underestimated timing**. None of it can detect a servo that's mechanically stalled or
obstructed and genuinely never reaches its commanded target.

That's exactly what the CCW spin issue turned out to be, and it was only caught because
a human noticed the physical symptom directly — no software guard flagged it, because
from the firmware's perspective the step completed exactly as planned; the servo simply
didn't end up where that plan assumed. Closing this gap for real would mean adding actual
position-feedback hardware, not another layer of duration bookkeeping.
