#include "rubiks_solver.h"
#include "moves.h"
#include "esphome/core/log.h"
#include "esphome/core/application.h"
#include <algorithm>
#include <esp_system.h>

namespace esphome {
namespace rubiks_solver {

static const char *const TAG = "rubiks_solver";

// Reset reasons that indicate the previous session ended deliberately (fresh power-up,
// a requested restart such as OTA, an external reset button press, or a developer
// actively connected via SDIO/USB/JTAG) — i.e. the last commanded servo position, if
// any, is trustworthy. Anything else (panic, any watchdog, brownout, power glitch, CPU
// lockup, or an unrecognised reason) means the firmware could have been interrupted
// mid-motion, leaving the arm/turntable somewhere setup()'s boot glide doesn't expect —
// see setup()'s comment and confirm_safe_and_home().
static bool is_clean_reset_reason(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_POWERON:
    case ESP_RST_SW:
    case ESP_RST_EXT:
    case ESP_RST_SDIO:
    case ESP_RST_USB:
    case ESP_RST_JTAG:
      return true;
    default:
      return false;
  }
}

// Face labels in scan order (White up, Green front starting position).
// Scan order: cube loaded White=top, Green=front; camera looks at top face.
// 0=W(start) 1=B(flip) 2=Y(flip) 3=G(flip) 4=R(spinCW+flip) 5=O(flip×2)
//
// R/O at positions 4/5 were flip-flopped twice on 2026-07-26 based on verbal "hardware
// confirmed" reads of the camera image — Red and Orange are a documented visual-confusion
// pair on this camera/lighting (see REFERENCE_LAB comment in camera_processor.py), and the
// two live tests that day gave contradictory answers. This value is instead derived
// mathematically from the stated Loading Position (W=U,G=F,O=L,Rd=R) and the Flip/Spin
// definitions in docs/orientation.md, tracing full (U,D,F,B,L,R) state through each step:
// position 4 = spin CW + flip → Top=Red; position 5 = flip×2 → Top=Orange. Every derived
// Front/Left/Right value at each step matches what was already independently agreed on,
// and both opposite-colour-pair validity and a spin-direction sanity check (CCW breaks the
// agreed Left=White/Right=Yellow fact at position 4, confirming CW is correct) support it.
// Do not re-flip this without an objective check (e.g. compare the raw LAB reading logged
// as "Centre colour overridden: detected X" against REFERENCE_LAB["R"] vs ["O"] distance) —
// eyeballing this pair on this camera has proven unreliable twice.
static const char *const SCAN_FACES[] = {"W", "B", "Y", "G", "R", "O"};
static const int NUM_FACES = 6;

// ── Duty → ESPHome conversion ─────────────────────────────────────────────────
// Extended pulse range: 0.5–2.5 ms at 50 Hz → 2.5%–12.5% duty.
// ESPHome maps: min_level (2.5%) → -1.0,  idle_level (7.5%) → 0.0,  max_level (12.5%) → +1.0.
// Formula: (pct - 7.5) / 5.0  →  maps 2.5%→-1, 7.5%→0, 12.5%→+1.
// Duty values are raw MicroPython 0–1023 scale from Cubotino_settings.txt.
// Absolute pulse widths are preserved — e.g. duty=76 still sends 1.49ms regardless of range.

float RubiksSolverComponent::duty_to_esphome(int duty) {
  float pct = duty / 1023.0f * 100.0f;   // 0-1023 → % duty cycle
  return (pct - 7.5f) / 5.0f;            // maps 2.5%→-1, 7.5%→0, 12.5%→+1
}

// ── Setup ──────────────────────────────────────────────────────────────────────

void RubiksSolverComponent::recompute_positions() {
  t_flip_v_          = duty_to_esphome(d_t_flip_);
  t_open_v_          = duty_to_esphome(d_t_open_);
  t_close_v_         = duty_to_esphome(d_t_close_);
  t_rel_v_           = duty_to_esphome(d_t_close_ - d_t_rel_offset_);

  b_ccw_v_           = duty_to_esphome(d_b_ccw_);
  b_home_v_          = duty_to_esphome(d_b_home_);
  b_cw_v_            = duty_to_esphome(d_b_cw_);
  b_ccw_rel_v_       = duty_to_esphome(d_b_ccw_ + d_b_extra_sides_);
  b_cw_rel_v_        = duty_to_esphome(d_b_cw_  - d_b_extra_sides_);
  b_home_from_cw_v_  = duty_to_esphome(d_b_home_ - d_b_extra_home_);
  b_home_from_ccw_v_ = duty_to_esphome(d_b_home_ + d_b_extra_home_);
}

void RubiksSolverComponent::setup() {
  recompute_positions();

  esp_reset_reason_t reason = esp_reset_reason();
  if (!is_clean_reset_reason(reason)) {
    // The previous session ended via crash/watchdog/brownout, not a deliberate reset —
    // the arm and turntable's actual physical position is unknown and may not match
    // what queue_boot_glide_() assumes (idle/home). Driving them blindly risks the
    // lifter jamming against the cube holder if the turntable isn't at one of its
    // slot-aligned positions (see docs/robot.md; investigated 2026-08-01). The servo
    // platform itself won't move anything on its own here — with `restore:` unset in
    // YAML, its own setup() just detaches (silences the PWM signal) rather than driving
    // to a position — so simply not queuing a move is enough to actually prevent motion.
    // Stay in IDLE and wait for a human to check before calling confirm_safe_and_home().
    ESP_LOGW(TAG, "Unclean previous reset (reason=%d) — skipping auto-home. Check the "
                  "arm/turntable aren't in a colliding position, then call "
                  "confirm_safe_and_home().", (int) reason);
    publish_status_("CHK ARM");
    state_ = SolverState::IDLE;
    needs_confirm_before_move_ = true;
    return;
  }

  queue_boot_glide_();
}

void RubiksSolverComponent::confirm_safe_and_home() {
  if (state_ != SolverState::IDLE) {
    ESP_LOGW(TAG, "confirm_safe_and_home ignored — not idle (state=%d)", (int) state_);
    return;
  }
  ESP_LOGI(TAG, "confirm_safe_and_home — proceeding to home");
  needs_confirm_before_move_ = false;
  queue_boot_glide_();
}

// Glide to rest position (cover open, bottom home) rather than snapping. Queues 10 top
// steps that sweep the cover from wherever it starts to open over ~1s, then settles the
// bottom to home. Shared by setup() (on a clean reset) and confirm_safe_and_home() (after
// an unclean one, once a human has confirmed it's safe). Uses SERVO_TEST so loop() drains
// the queue and returns to IDLE on its own.
void RubiksSolverComponent::queue_boot_glide_() {
  steps_.clear();
  const int N = 10;
  for (int i = 1; i <= N; i++)
    append_step_(ServoStep::TOP, t_open_v_ * i / (float)N, 100);
  append_step_(ServoStep::BOTTOM, b_home_v_, 200);

  // This is what the glide actually drives both servos to — keep the plan-time tracking
  // self-consistent with that rather than relying on every future caller to reset it
  // themselves before planning anything new (currently true of start_scan()/
  // execute_solution(), but not guaranteed for whatever's added next).
  plan_top_cover_ = TopCover::OPEN;
  plan_b_home_    = true;
  plan_b_cw_pos_  = false;
  plan_b_ccw_pos_ = false;

  step_idx_ = 0;
  state_    = SolverState::SERVO_TEST;
  enable_loop();
}

// ── Status publishing ──────────────────────────────────────────────────────────

void RubiksSolverComponent::publish_status_(const std::string &s) {
  ESP_LOGI(TAG, "status: %s", s.c_str());
  if (status_sensor_ != nullptr)
    status_sensor_->publish_state(s);
}

// Optimistic only — see the field comment in the header. Not a physical confirmation.
void RubiksSolverComponent::set_believed_home_(bool home) {
  believed_home_ = home;
  if (believed_home_sensor_ != nullptr)
    believed_home_sensor_->publish_state(home);
}

// ── Main loop ─────────────────────────────────────────────────────────────────

void RubiksSolverComponent::loop() {
  if (state_ == SolverState::IDLE ||
      state_ == SolverState::SCAN_WAIT) return;

  // All steps done?
  if (step_idx_ >= steps_.size()) { fire_done_(); return; }

  auto now = App.get_loop_component_start_time();
  if (now - step_start_ms_ < steps_[step_idx_].duration_ms) return;

  const auto &step = steps_[step_idx_];

  // Cross-servo dispatch guard — see top_dispatch_ms_ etc. in the header. Checks,
  // against the real clock, whether the *other* servo's last dispatched step should
  // actually be finished yet. This is independent of (and should always already be
  // satisfied by) the plan-time duration math in append_step_() — it only matters if
  // that bookkeeping was ever wrong, so tripping it is a real anomaly worth a warning.
  uint32_t other_dispatch_ms = (step.target == ServoStep::TOP) ? bottom_dispatch_ms_
                                                                 : top_dispatch_ms_;
  uint32_t other_duration_ms = (step.target == ServoStep::TOP) ? bottom_step_duration_ms_
                                                                 : top_step_duration_ms_;
  if (now - other_dispatch_ms < other_duration_ms) {
    if (!dispatch_guard_warned_) {
      ESP_LOGW(TAG, "step %d/%d held — other servo not yet confirmed settled (%ums remaining)",
               (int) step_idx_ + 1, (int) steps_.size(),
               (unsigned) (other_duration_ms - (now - other_dispatch_ms)));
      dispatch_guard_warned_ = true;
    }
    return;
  }
  dispatch_guard_warned_ = false;

  step_idx_++;
  if (step.target == ServoStep::TOP)    top_servo_->write(step.position);
  if (step.target == ServoStep::BOTTOM) bottom_servo_->write(step.position);

  // Purely observational — advances robot_actions_done_ as step_idx_ crosses the
  // boundaries mark_action_boundary_() recorded at plan time. Never influences
  // step timing/positions above.
  bool crossed_boundary = false;
  while (robot_actions_done_ < action_boundaries_.size() &&
         step_idx_ >= action_boundaries_[robot_actions_done_]) {
    robot_actions_done_++;
    crossed_boundary = true;
  }
  if (crossed_boundary && moves_remaining_sensor_) {
    int remaining = robot_move_count_ - (int) robot_actions_done_;
    moves_remaining_sensor_->publish_state(remaining < 0 ? 0 : remaining);
  }

  uint32_t &my_dispatch_ms = (step.target == ServoStep::TOP) ? top_dispatch_ms_
                                                               : bottom_dispatch_ms_;
  uint32_t &my_duration_ms = (step.target == ServoStep::TOP) ? top_step_duration_ms_
                                                               : bottom_step_duration_ms_;
  my_dispatch_ms = now;
  my_duration_ms = step.duration_ms;

  ESP_LOGV(TAG, "step %d/%d  %s  %.3f  (%ums)",
           (int) step_idx_, (int) steps_.size(),
           step.target == ServoStep::TOP ? "TOP" : "BOT",
           step.position, (unsigned) step.duration_ms);

  step_start_ms_ = now;
}

// ── API action handlers ────────────────────────────────────────────────────────

void RubiksSolverComponent::start_scan() {
  if (state_ != SolverState::IDLE) {
    ESP_LOGW(TAG, "start_scan ignored — not idle (state=%d); call stop() first", (int) state_);
    return;
  }
  if (needs_confirm_before_move_) {
    ESP_LOGW(TAG, "start_scan ignored — call confirm_safe_and_home() first "
                  "(position unconfirmed after a reset or an abort)");
    return;
  }
  if (!believed_home_) {
    ESP_LOGW(TAG, "start_scan ignored — call confirm_safe_and_home() first "
                  "(not believed to be home, e.g. after a test move)");
    return;
  }
  ESP_LOGI(TAG, "start_scan");
  scan_face_idx_  = 0;
  steps_.clear();
  publish_status_("SCAN 1");

  plan_top_cover_ = TopCover::OPEN;   // arm is up after boot glide
  plan_b_home_    = true;
  plan_b_cw_pos_  = false;
  plan_b_ccw_pos_ = false;

  plan_scan_move_(scan_face_idx_);
  plan_ensure_cover_closed_();        // lower arm: camera at right angle, light hood blocks ambient

  step_idx_      = 0;
  step_start_ms_ = 0;    // 0 → first step fires on the next loop() tick
  state_         = SolverState::SCANNING;
  enable_loop();
}

void RubiksSolverComponent::advance_scan() {
  if (state_ != SolverState::SCAN_WAIT) {
    ESP_LOGW(TAG, "advance_scan ignored — not waiting for a face (state=%d)", (int) state_);
    return;
  }
  scan_face_idx_++;
  steps_.clear();

  // Do NOT reset plan_top_cover_ — carry CLOSED from previous face's scan position.
  // plan_flip_() calls plan_ensure_cover_open_() first, which sees CLOSED and adds the open step.
  plan_b_home_    = true;
  plan_b_cw_pos_  = false;
  plan_b_ccw_pos_ = false;

  if (scan_face_idx_ >= NUM_FACES) {
    ESP_LOGI(TAG, "advance_scan: all faces done — returning cube to White-up, Green-front");
    // Distinct from "SCAN END" (fired later, once physically back home) — gives immediate
    // feedback the instant the 6th face is captured, before the return moves even start.
    publish_status_("HOMING");
    // After scanning O (face 5), the turntable is physically at CW (from R face's spin_out
    // in plan_scan_move_(4), which was never followed by a spin_home).
    // advance_scan() reset plan_b_home_=true above — correct that to match physical state.
    plan_b_home_    = false;
    plan_b_cw_pos_  = true;
    plan_b_ccw_pos_ = false;
    // plan_top_cover_ is CLOSED, carried from the O scan close step.
    //
    // (2026-08-01) The previous version of this sequence ended with plan_rotate_(1) to
    // bring the turntable home — but rotate is cover-closed (top 2 layers held), so
    // bringing it home that way twists the D layer by 90° *after* the cube had already
    // been fully scanned and its kociemba string computed, leaving the physical cube one
    // quarter-turn away from the state the solution was actually calculated for. A
    // from-scratch BFS search over pure flip/spin sequences (verified against the actual
    // FLIP/SPIN_CW/SPIN_CCW permutation formulas, not manual derivation — an earlier
    // manual attempt wrongly concluded no such sequence exists) found this 3-move
    // sequence, which reaches White-up/Green-front with the turntable at home using only
    // whole-cube moves — no rotate, no D-layer side effect, no compensation needed:
    //   flip:       U=O,F=B,L=W,R=Y → U=G,F=O (L,R unchanged: L=W,R=Y)
    //   spin_home (CW→HOME): U=G,F=O,L=W,R=Y → U=G,F=Y,L=O,R=B
    //   flip:       U=G,F=Y,L=O,R=B → U=W,F=G  ← target ✓ (L,R unchanged: L=O,R=B)
    //
    // Settle pads bracketing this sequence: the O-face close step just before this and
    // the final flip's own declared duration are both calibrated-duration estimates,
    // not physical confirmation — this specific handoff (into, and out of, the return
    // sequence) is where jamming has actually been observed. A short extra dwell at the
    // current position on each end buys real margin without changing the moves.
    // Pre-pad is 900ms, not a token 400 — the "HOMING" RTTTL clip itself (2 notes +
    // gap at d=8/120bpm) takes ~750ms to play; a shorter pad would let the real flip
    // motion start (loud) while the beep is still going, drowning out the second note.
    // Long enough for the beep to fully finish in the quiet window before motion starts.
    append_step_(ServoStep::TOP, t_close_v_, 900);  // pre-pad: let the O-face close fully settle
    plan_flip_(1, 0);
    plan_spin_(1);      // spin_home from CW (dir arg unused on this branch — plan_b_home_
                         // is already false, so plan_spin_() takes the spin_home path
                         // regardless of what's passed here)
    plan_flip_(1, 0);
    append_step_(ServoStep::TOP, t_open_v_, 400);   // post-pad: let the final flip fully settle
                                                     // before SCAN END/execute_solution can follow
    // fire_done_() will publish "SCAN END" + esphome.rubiks_scan_complete once steps drain.
  } else {
    ESP_LOGI(TAG, "advance_scan: face %d (%s)", scan_face_idx_, SCAN_FACES[scan_face_idx_]);
    publish_status_("SCAN " + std::to_string(scan_face_idx_ + 1));
    plan_scan_move_(scan_face_idx_);
    plan_ensure_cover_closed_();      // lower arm for scan: camera at right angle, hood blocks ambient
  }

  step_idx_      = 0;
  step_start_ms_ = 0;
  state_         = SolverState::SCANNING;
  enable_loop();
}

void RubiksSolverComponent::execute_solution(const std::string &solution) {
  // Both guards below clear these explicitly rather than leaving them at whatever a
  // previous call left behind — api.respond reports them unconditionally, so a rejected
  // call must not report a stale prior success.
  if (state_ != SolverState::IDLE) {
    ESP_LOGW(TAG, "execute_solution ignored — not idle (state=%d); call stop() first", (int) state_);
    solution_accepted_ = false;
    robot_move_count_  = 0;
    return;
  }
  if (needs_confirm_before_move_) {
    ESP_LOGW(TAG, "execute_solution ignored — call confirm_safe_and_home() first "
                  "(position unconfirmed after a reset or an abort)");
    solution_accepted_ = false;
    robot_move_count_  = 0;
    return;
  }
  if (!believed_home_) {
    ESP_LOGW(TAG, "execute_solution ignored — call confirm_safe_and_home() first "
                  "(not believed to be home, e.g. after a test move)");
    solution_accepted_ = false;
    robot_move_count_  = 0;
    return;
  }
  ESP_LOGI(TAG, "execute_solution: %s", solution.c_str());
  solution_       = solution;
  steps_.clear();
  publish_status_("SOLVING");

  plan_top_cover_ = TopCover::OPEN;
  plan_b_home_    = true;
  plan_b_cw_pos_  = false;
  plan_b_ccw_pos_ = false;

  plan_solution_();

  solution_accepted_ = !steps_.empty();
  if (!solution_accepted_) {
    ESP_LOGW(TAG, "no steps planned — solution may be empty or invalid");
    return;
  }

  ESP_LOGI(TAG, "planned %d steps (%d robot moves)", (int) steps_.size(), robot_move_count_);
  step_idx_      = 0;
  step_start_ms_ = 0;
  state_         = SolverState::SOLVING;
  enable_loop();
}

void RubiksSolverComponent::stop() {
  // Reset immediately rather than deferring to stop_requested_ (checked only inside
  // loop()) — loop() is disabled in SCAN_WAIT and DONE, so a deferred flag would never
  // actually be processed in those states, leaving the component stuck (2026-07-26:
  // observed as "stop requested" followed by "start_scan ignored — not idle (state=5)").
  ESP_LOGW(TAG, "stop requested");
  if (state_ != SolverState::IDLE) {
    // Something was actually queued/paused (mid-motion, or settled mid-scan at some
    // non-home face) — start_scan()/execute_solution() unconditionally assume home when
    // planning next, and that assumption is no longer trustworthy after an interruption
    // like this. Require confirm_safe_and_home() before believing it again. A stop()
    // called while already IDLE is a no-op here — nothing was interrupted.
    needs_confirm_before_move_ = true;
  }
  reset_();
}

// ── Step queue helpers ─────────────────────────────────────────────────────────

// Cross-servo timing guard — the non-blocking equivalent of the original CUBOTino
// firmware's b_servo_operable / b_servo_stopped interlock (Cubotino_servos.py). That
// original is a blocking script: every function is "command, then sleep_ms(this exact
// command's own duration)", so the language's execution order makes it impossible to
// fire one servo before the other's declared travel time has elapsed. Our step queue
// decouples "what to do" from "how long to wait before doing it" into separate fields,
// which is what let a duration meant for one servo's move get silently applied to the
// other servo's *next* move instead (found twice: plan_flip_() and
// plan_ensure_cover_open_() each ignored a just-queued bottom-servo travel time).
//
// This is the single choke point every queued step passes through, so the guard is
// automatic for all current and future callers — no call site needs to remember it:
//   1. Before queuing, extend this step's duration to cover any outstanding travel
//      time still owed by the *other* servo's most recently queued move.
//   2. After queuing, record this step's own duration as what the *other* servo's next
//      move must wait for in turn.
// Like the original, this is still a calibrated-duration estimate, not a real physical
// completion signal — these servos have no position feedback — but it can no longer be
// misattributed to the wrong action.
void RubiksSolverComponent::append_step_(ServoStep::Target target, float pos, uint32_t dur_ms) {
  // Any queued move means we're no longer confirmed at rest — see fire_done_() for
  // where this gets set true again, once (and if) the sequence actually completes there.
  if (believed_home_) set_believed_home_(false);

  // Scale to real-time units first — everything from here on (the owed comparison, the
  // stored "owed by me" value, and the pushed step) must stay in the same (scaled) unit
  // system. Comparing/stretching in raw units and scaling afterward (an earlier version
  // of this fix did that) double-scales whenever the owed value wins the max(), since
  // the owed value was itself already scaled.
  uint32_t scaled_dur_ms = (uint32_t) (dur_ms * speed_mul_ + 0.5f);

  uint32_t &owed_to_me = (target == ServoStep::TOP) ? pending_bottom_travel_ms_
                                                      : pending_top_travel_ms_;
  scaled_dur_ms = std::max(scaled_dur_ms, owed_to_me);
  owed_to_me = 0;

  uint32_t &owed_by_me = (target == ServoStep::TOP) ? pending_top_travel_ms_
                                                      : pending_bottom_travel_ms_;
  owed_by_me = scaled_dur_ms;

  steps_.push_back({target, pos, scaled_dur_ms});
}

void RubiksSolverComponent::mark_action_boundary_() {
  action_boundaries_.push_back(steps_.size());
}

// ── Cover transition planners ─────────────────────────────────────────────────

void RubiksSolverComponent::plan_ensure_cover_open_() {
  if (plan_top_cover_ == TopCover::OPEN) return;
  uint32_t dur = (plan_top_cover_ == TopCover::FLIP)
                   ? t_flip_open_time_
                   : t_open_close_time_;
  // Cross-servo timing guard lives in append_step_() now — see its comment.
  append_step_(ServoStep::TOP, t_open_v_, dur);
  plan_top_cover_ = TopCover::OPEN;
}

void RubiksSolverComponent::plan_ensure_cover_closed_() {
  if (plan_top_cover_ == TopCover::CLOSED) return;
  uint32_t cover_dur = (plan_top_cover_ == TopCover::FLIP)
                         ? t_flip_to_close_time_
                         : t_open_close_time_;
  // Cross-servo timing guard lives in append_step_() now — see its comment.
  append_step_(ServoStep::TOP, t_close_v_, cover_dur);
  // Release is a no-op while Top: Release Offset is disabled (0) — t_rel_v_ then
  // equals t_close_v_ exactly, so this step would otherwise cost a full
  // t_open_close_time_ of dead time for zero motion. Skip it until the offset
  // feature is actually finished; behavior is unchanged for a nonzero offset.
  if (d_t_rel_offset_ != 0)
    append_step_(ServoStep::TOP, t_rel_v_, t_open_close_time_);
  plan_top_cover_ = TopCover::CLOSED;
}

// ── Primitive planners ────────────────────────────────────────────────────────

// Flip cube n times (front face → bottom).
// next_token: the move character immediately after this F block ('R', 'S', 0, or the
// scan-only sentinel 'X' — see plan_scan_move_()). Used to decide whether to leave the
// cover closed (→ R), open (→ S / end), or untouched at FLIP (→ X, caller closes it).
// 'X' never appears in a real kociemba move string (only F/S/R), so plan_solution_()'s
// calls are unaffected.
void RubiksSolverComponent::plan_flip_(int count, char next_token) {
  for (int i = 0; i < count; i++) {
    // flip_up(): raise arm to flip position
    uint32_t dur = (plan_top_cover_ == TopCover::CLOSED)
                     ? t_close_to_flip_time_
                     : t_flip_open_time_;
    // Cross-servo timing guard lives in append_step_() now — see its comment. This
    // matters most here: a spin may have just been queued immediately before this flip
    // (e.g. the "S3F1..." token sequence used for kociemba R/L moves, and scan
    // position 4's spin+flip) — without the guard, the flip would fire dur ms after the
    // spin was *queued*, not after the bottom servo actually finished travelling.
    append_step_(ServoStep::TOP, t_flip_v_, dur);
    plan_top_cover_ = TopCover::FLIP;
    mark_action_boundary_();  // one physical flip = one action, matching count_moves()'s F<n>=n

    if (i < count - 1) {
      // Between flips: open cover so arm can swing back for next flip
      append_step_(ServoStep::TOP, t_open_v_, t_flip_open_time_);
      plan_top_cover_ = TopCover::OPEN;
    }
  }

  // After last flip: transition cover based on what comes next
  if (next_token == 'R') {
    // Rotate follows — close cover to constrain top 2 layers.
    append_step_(ServoStep::TOP, t_close_v_, t_flip_to_close_time_);
    // Same no-op skip as plan_ensure_cover_closed_() — see comment there.
    if (d_t_rel_offset_ != 0)
      append_step_(ServoStep::TOP, t_rel_v_, t_flip_to_close_time_);
    plan_top_cover_ = TopCover::CLOSED;
  } else if (next_token == 'X') {
    // Scan caller — leave the arm at FLIP. plan_ensure_cover_closed_() runs next (in
    // plan_scan_move_()'s caller) and already picks t_flip_to_close_time_ for a direct
    // FLIP→CLOSE leg when it sees plan_top_cover_ == FLIP, so opening here first would
    // just be a wasted extra reversal (this was the "flip cuts short, goes back down"
    // bug during scanning — the auto-open below fired, then the caller closed again).
  } else {
    // Spin or end — open cover so cube can rotate freely
    append_step_(ServoStep::TOP, t_open_v_, t_flip_open_time_);
    plan_top_cover_ = TopCover::OPEN;
  }
}

// Spin full cube 90°.  dir: 1 = CW, 3 = CCW.
// Alternates between spin_out (from home) and spin_home (from end position).
void RubiksSolverComponent::plan_spin_(int dir) {
  if (plan_b_home_) {
    // spin_out: stop at release position (matching original Cubotino spin_out → b_servo_CW_rel / CCW_rel)
    float    target = (dir == 3) ? b_ccw_rel_v_ : b_cw_rel_v_;
    append_step_(ServoStep::BOTTOM, target, b_spin_time_);
    plan_b_home_    = false;
    plan_b_cw_pos_  = (dir != 3);
    plan_b_ccw_pos_ = (dir == 3);
  } else {
    // spin_home: return to centre (this IS the opposing spin of the cube)
    append_step_(ServoStep::BOTTOM, b_home_v_, b_spin_time_);
    plan_b_home_    = true;
    plan_b_cw_pos_  = false;
    plan_b_ccw_pos_ = false;
  }
  mark_action_boundary_();  // one spin token ("S1"/"S3") = one action, matching count_moves()
}

// Rotate bottom layer 90°.  dir: 1 = CW, 3 = CCW.
// Alternates between rotate_out (from home) and rotate_home (from end position).
// Manages cover internally: closes before rotating, opens after.
void RubiksSolverComponent::plan_rotate_(int dir) {
  if (plan_b_home_) {
    // rotate_out: close cover, rotate to end with slight overshoot, release, open cover
    plan_ensure_cover_closed_();

    float target     = (dir == 3) ? b_ccw_v_     : b_cw_v_;
    float target_rel = (dir == 3) ? b_ccw_rel_v_ : b_cw_rel_v_;
    // Corrected 2026-08-15: these two durations were swapped relative to the original
    // (Cubotino_servos.py rotate_out()) — target (the real ~90° travel from home) was
    // getting t_open_close_time_ (300ms, nowhere near enough), while target_rel (a tiny
    // few-unit release nudge) got the full b_rotate_time_ (1200ms) it didn't need. The
    // original always pairs the long duration with the far move and the short one with
    // the nudge; matching that here. The cover-settling concern the old comment cited is
    // already handled independently by append_step_()'s cross-servo guard, which
    // stretches this step to cover the just-queued cover-close regardless of what's
    // declared here.
    append_step_(ServoStep::BOTTOM, target,     b_rotate_time_);
    append_step_(ServoStep::BOTTOM, target_rel, b_rel_time_);

    plan_b_home_    = false;
    plan_b_cw_pos_  = (dir != 3);
    plan_b_ccw_pos_ = (dir == 3);
    mark_action_boundary_();  // one rotate token ("R1"/"R3") = one action, matching count_moves()

    plan_ensure_cover_open_();

  } else {
    // rotate_home: close cover, overshoot toward home, settle, open cover
    plan_ensure_cover_closed_();

    // Overshoot: go slightly past home in the direction we're travelling,
    // then come back.  This releases the friction between cube and holder.
    float overshoot;
    if (dir == 3) {
      // Coming back CCW from a CW position
      overshoot = plan_b_cw_pos_ ? b_home_from_cw_v_ : b_home_v_;
    } else {
      // Coming back CW from a CCW position
      overshoot = plan_b_ccw_pos_ ? b_home_from_ccw_v_ : b_home_v_;
    }
    // Same correction as rotate_out above — overshoot (the real far-to-near-home
    // travel) gets the long duration, the final tiny nudge to exact home gets the short
    // one, matching Cubotino_servos.py rotate_home()/rotate_home_test().
    append_step_(ServoStep::BOTTOM, overshoot, b_rotate_time_);
    append_step_(ServoStep::BOTTOM, b_home_v_, b_rel_time_);

    plan_b_home_    = true;
    plan_b_cw_pos_  = false;
    plan_b_ccw_pos_ = false;
    mark_action_boundary_();  // one rotate token ("R1"/"R3") = one action, matching count_moves()

    plan_ensure_cover_open_();
  }
}

// ── Solution planner ──────────────────────────────────────────────────────────

void RubiksSolverComponent::plan_solution_() {
  action_boundaries_.clear();
  robot_actions_done_ = 0;

  std::string robot_moves = moves::robot_required_moves(solution_);
  if (robot_moves.empty()) {
    ESP_LOGW(TAG, "robot_required_moves returned empty — invalid solution?");
    robot_move_count_ = 0;
    return;
  }
  robot_move_count_ = moves::count_moves(robot_moves);
  ESP_LOGI(TAG, "robot moves: %s  (%d actions)", robot_moves.c_str(), robot_move_count_);
  if (moves_remaining_sensor_) moves_remaining_sensor_->publish_state(robot_move_count_);

  for (size_t i = 0; i + 1 < robot_moves.size(); i += 2) {
    char token     = robot_moves[i];
    int  num       = robot_moves[i + 1] - '0';
    char next_tok  = (i + 3 < robot_moves.size()) ? robot_moves[i + 2] : 0;

    if      (token == 'F') plan_flip_  (num, next_tok);
    else if (token == 'S') plan_spin_  (num);
    else if (token == 'R') plan_rotate_(num);
  }
}

// ── Scan planner ──────────────────────────────────────────────────────────────

void RubiksSolverComponent::plan_scan_move_(int face_idx) {
  ESP_LOGD(TAG, "plan_scan_move_ %d (%s)", face_idx, SCAN_FACES[face_idx]);
  // plan_top_cover_ carries CLOSED from previous face; caller adds ensure_closed after.
  switch (face_idx) {
    case 0: break;                          // White — already on top, no movement
    case 1: plan_flip_(1, 'X'); break;      // Blue  — 1 flip (back → top)
    case 2: plan_flip_(1, 'X'); break;      // Yellow — 1 flip (bottom → top)
    case 3: plan_flip_(1, 'X'); break;      // Green  — 1 flip (front → top)
    case 4:                                 // Red    — cover is CLOSED from prev; open first, then spin CW + flip
      plan_ensure_cover_open_();
      plan_spin_(1);
      plan_flip_(1, 'X');
      break;
    case 5: plan_flip_(2, 'X'); break;      // Orange — 2 flips
  }
}

// ── Event signalling ──────────────────────────────────────────────────────────

void RubiksSolverComponent::fire_ha_event_(const std::string &event, const std::string &data) {
  ESP_LOGI(TAG, "→ HA event: %s  data=%s", event.c_str(), data.c_str());
  if (!data.empty()) {
    this->fire_homeassistant_event(event, {{"face", data}});
  } else {
    this->fire_homeassistant_event(event);
  }
}

void RubiksSolverComponent::fire_done_() {
  if (state_ == SolverState::SCANNING && scan_face_idx_ < NUM_FACES) {
    // Face in position — publish "FACE N" to trigger beep via on_state automation
    publish_status_("FACE " + std::to_string(scan_face_idx_ + 1));
    fire_ha_event_("esphome.rubiks_face_ready", SCAN_FACES[scan_face_idx_]);
    state_ = SolverState::SCAN_WAIT;
    disable_loop();

  } else if (state_ == SolverState::SCANNING) {
    publish_status_("SCAN END");
    fire_ha_event_("esphome.rubiks_scan_complete");
    set_believed_home_(plan_top_cover_ == TopCover::OPEN && plan_b_home_);
    reset_();

  } else if (state_ == SolverState::SOLVING) {
    // Returns straight to IDLE — used to linger in a separate DONE state, requiring an
    // explicit stop() before any further action even though a normal solve completion
    // doesn't leave physical position uncertain the way an abort or unclean reset does
    // (see needs_confirm_before_move_ for those). Status text still shows "DONE" until
    // the next command publishes something else, since nothing here overwrites it.
    publish_status_("DONE");
    fire_ha_event_("esphome.rubiks_solve_done");
    set_believed_home_(plan_top_cover_ == TopCover::OPEN && plan_b_home_);
    state_ = SolverState::IDLE;
    // Same reasoning as the SERVO_TEST branch below: this can be reached with an
    // unconsumed pending value left over, and IDLE is now immediately actionable
    // (no lingering DONE state), so don't let the next command inherit a stale wait.
    pending_bottom_travel_ms_ = 0;
    pending_top_travel_ms_    = 0;
    disable_loop();

  } else if (state_ == SolverState::SERVO_TEST) {
    ESP_LOGI(TAG, "test move complete");
    set_believed_home_(plan_top_cover_ == TopCover::OPEN && plan_b_home_);
    state_ = SolverState::IDLE;
    // Unlike reset_(), this path can be reached with an unconsumed pending value left
    // over (e.g. a test ending on a bottom-servo move) — clear both so the next test
    // button press doesn't inherit a stale wait from this one.
    pending_bottom_travel_ms_ = 0;
    pending_top_travel_ms_    = 0;
    disable_loop();
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────────

void RubiksSolverComponent::reset_() {
  state_                     = SolverState::IDLE;
  pending_bottom_travel_ms_  = 0;
  pending_top_travel_ms_     = 0;
  steps_.clear();
  step_idx_ = 0;
  publish_status_("IDLE");
  disable_loop();
}

void RubiksSolverComponent::dump_config() {
  ESP_LOGCONFIG(TAG, "Rubiks Solver:");
  ESP_LOGCONFIG(TAG, "  Raw duty settings:");
  ESP_LOGCONFIG(TAG, "    Top:    flip=%d  open=%d  close=%d  rel_offset=%d",
                d_t_flip_, d_t_open_, d_t_close_, d_t_rel_offset_);
  ESP_LOGCONFIG(TAG, "    Bottom: ccw=%d  home=%d  cw=%d  extra_sides=%d  extra_home=%d",
                d_b_ccw_, d_b_home_, d_b_cw_, d_b_extra_sides_, d_b_extra_home_);
  ESP_LOGCONFIG(TAG, "  Computed servo positions (ESPHome -1..1):");
  ESP_LOGCONFIG(TAG, "    Top:    flip=%.3f  open=%.3f  close=%.3f  rel=%.3f",
                t_flip_v_, t_open_v_, t_close_v_, t_rel_v_);
  ESP_LOGCONFIG(TAG, "    Bottom: ccw=%.3f  home=%.3f  cw=%.3f  ccw_rel=%.3f  cw_rel=%.3f",
                b_ccw_v_, b_home_v_, b_cw_v_, b_ccw_rel_v_, b_cw_rel_v_);
  ESP_LOGCONFIG(TAG, "  Timing (ms):  t_flip_open=%u  t_open_close=%u  t_flip_close=%u  t_close_flip=%u",
                t_flip_open_time_, t_open_close_time_, t_flip_to_close_time_, t_close_to_flip_time_);
  ESP_LOGCONFIG(TAG, "  Timing (ms):  b_spin=%u  b_rotate=%u  b_rel=%u",
                b_spin_time_, b_rotate_time_, b_rel_time_);
}

// ── Servo test / calibration helpers ──────────────────────────────────────────
// These bypass the step queue and drive servos directly.
// Only intended for use from dashboard buttons when state is IDLE.

void RubiksSolverComponent::servo_centre() {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "servo_centre: not idle"); return; }
  ESP_LOGI(TAG, "servo test: both → centre (7.5%% / idle_level)");
  if (top_servo_)    top_servo_->write(0.0f);
  if (bottom_servo_) bottom_servo_->write(0.0f);
}

void RubiksSolverComponent::servo_top_flip() {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "servo test: not idle"); return; }
  ESP_LOGI(TAG, "servo test: top → flip (%.3f)", t_flip_v_);
  if (top_servo_) top_servo_->write(t_flip_v_);
}

void RubiksSolverComponent::servo_top_open() {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "servo test: not idle"); return; }
  ESP_LOGI(TAG, "servo test: top → open (%.3f)", t_open_v_);
  if (top_servo_) top_servo_->write(t_open_v_);
}

void RubiksSolverComponent::servo_top_close() {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "servo test: not idle"); return; }
  ESP_LOGI(TAG, "servo test: top → close (%.3f)", t_close_v_);
  if (top_servo_) top_servo_->write(t_close_v_);
}

void RubiksSolverComponent::servo_bottom_ccw() {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "servo test: not idle"); return; }
  ESP_LOGI(TAG, "servo test: bottom → CCW (%.3f)", b_ccw_v_);
  if (bottom_servo_) bottom_servo_->write(b_ccw_v_);
}

void RubiksSolverComponent::servo_bottom_home() {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "servo test: not idle"); return; }
  ESP_LOGI(TAG, "servo test: bottom → home with release (overshoot=%.3f settle=%.3f)", b_home_from_cw_v_, b_home_v_);
  steps_.clear();
  // Step 0 fires immediately (step_start_ms_=0); put the travel wait on step 1.
  append_step_(ServoStep::BOTTOM, b_home_from_cw_v_, 0);
  append_step_(ServoStep::BOTTOM, b_home_v_,         b_rotate_time_);
  step_idx_ = 0;
  state_    = SolverState::SERVO_TEST;
  enable_loop();
}

void RubiksSolverComponent::servo_bottom_cw() {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "servo test: not idle"); return; }
  ESP_LOGI(TAG, "servo test: bottom → CW (%.3f)", b_cw_v_);
  if (bottom_servo_) bottom_servo_->write(b_cw_v_);
}

void RubiksSolverComponent::test_rotate_cw_home() {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "test_rotate_cw_home: not idle"); return; }
  ESP_LOGI(TAG, "test: rotate CW then home-with-release");
  steps_.clear();
  plan_top_cover_ = TopCover::OPEN;
  plan_b_home_    = true;
  plan_b_cw_pos_  = false;
  plan_b_ccw_pos_ = false;
  plan_rotate_(1);  // CW out (closes cover, rotates CW with overshoot, opens cover)
  plan_rotate_(3);  // return home (closes cover, overshoots home, releases, opens cover)
  step_idx_ = 0;
  state_    = SolverState::SERVO_TEST;
  enable_loop();
}

void RubiksSolverComponent::test_rotate_ccw_home() {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "test_rotate_ccw_home: not idle"); return; }
  ESP_LOGI(TAG, "test: rotate CCW then home-with-release");
  steps_.clear();
  plan_top_cover_ = TopCover::OPEN;
  plan_b_home_    = true;
  plan_b_cw_pos_  = false;
  plan_b_ccw_pos_ = false;
  plan_rotate_(3);  // CCW out
  plan_rotate_(1);  // return home from CCW
  step_idx_ = 0;
  state_    = SolverState::SERVO_TEST;
  enable_loop();
}

void RubiksSolverComponent::test_flip(int count) {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "test_flip: not idle"); return; }
  ESP_LOGI(TAG, "test: flip ×%d", count);
  steps_.clear();
  plan_top_cover_ = TopCover::OPEN;
  plan_b_home_    = true;
  plan_b_cw_pos_  = false;
  plan_b_ccw_pos_ = false;
  plan_flip_(count, 0);
  step_idx_ = 0;
  state_    = SolverState::SERVO_TEST;
  enable_loop();
}

void RubiksSolverComponent::test_spin_cw_home() {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "test_spin_cw_home: not idle"); return; }
  ESP_LOGI(TAG, "test: spin CW then home");
  steps_.clear();
  plan_top_cover_ = TopCover::CLOSED;  // assume worst case so ensure_open adds the step
  plan_b_home_    = true;
  plan_b_cw_pos_  = false;
  plan_b_ccw_pos_ = false;
  plan_ensure_cover_open_();  // cover must be open for whole-cube spin
  plan_spin_(1);  // spin out CW
  plan_spin_(1);  // spin home (cover open → whole cube spins back)
  step_idx_ = 0;
  state_    = SolverState::SERVO_TEST;
  enable_loop();
}

void RubiksSolverComponent::test_spin_ccw_home() {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "test_spin_ccw_home: not idle"); return; }
  ESP_LOGI(TAG, "test: spin CCW then home");
  steps_.clear();
  plan_top_cover_ = TopCover::CLOSED;  // assume worst case so ensure_open adds the step
  plan_b_home_    = true;
  plan_b_cw_pos_  = false;
  plan_b_ccw_pos_ = false;
  plan_ensure_cover_open_();  // cover must be open for whole-cube spin
  plan_spin_(3);  // spin out CCW
  plan_spin_(3);  // spin home
  step_idx_ = 0;
  state_    = SolverState::SERVO_TEST;
  enable_loop();
}

void RubiksSolverComponent::test_scan_cycle() {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "test_scan_cycle: not idle"); return; }
  ESP_LOGI(TAG, "test_scan_cycle: face %d (%s)", test_scan_face_idx_, SCAN_FACES[test_scan_face_idx_]);
  steps_.clear();
  plan_b_home_    = true;
  plan_b_cw_pos_  = false;
  plan_b_ccw_pos_ = false;

  // Face 0: arm state unknown after other tests — treat as OPEN so ensure_closed always fires.
  // Faces 1-5: arm is CLOSED from the previous face's dwell; treat as CLOSED so
  //            plan_flip_() → plan_ensure_cover_open_() always adds the open step.
  plan_top_cover_ = (test_scan_face_idx_ == 0) ? TopCover::OPEN : TopCover::CLOSED;

  plan_scan_move_(test_scan_face_idx_);
  plan_ensure_cover_closed_();
  append_step_(ServoStep::TOP, t_close_v_, 1500);  // dwell 1.5 s in scan position

  test_scan_face_idx_ = (test_scan_face_idx_ + 1) % NUM_FACES;

  step_idx_ = 0;
  state_    = SolverState::SERVO_TEST;
  enable_loop();
}

// Isolates advance_scan()'s scan-complete branch (flip, spin_home, flip) without needing a
// real 6-face scan first. That sequence only makes physical sense from the exact state it
// normally runs in — cover CLOSED (carried from face O's own close step) and turntable at CW
// (carried from face R's spin, never spun back home during scanning) — so this reproduces
// that precondition manually before running the same three moves. See advance_scan()'s
// comment for the verified state trace.
void RubiksSolverComponent::test_scan_return_home() {
  if (state_ != SolverState::IDLE) { ESP_LOGW(TAG, "test_scan_return_home: not idle"); return; }
  ESP_LOGI(TAG, "test: post-scan return-to-home sequence (flip, spin_home, flip)");
  steps_.clear();

  plan_top_cover_ = TopCover::CLOSED;
  plan_b_home_    = false;
  plan_b_cw_pos_  = true;
  plan_b_ccw_pos_ = false;

  plan_flip_(1, 0);
  plan_spin_(1);      // spin_home from CW (dir arg unused — plan_b_home_ already false)
  plan_flip_(1, 0);

  step_idx_ = 0;
  state_    = SolverState::SERVO_TEST;
  enable_loop();
}

}  // namespace rubiks_solver
}  // namespace esphome
