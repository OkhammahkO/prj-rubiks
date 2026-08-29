#pragma once

#include <string>
#include <vector>
#include "esphome/core/component.h"
#include "esphome/components/servo/servo.h"
#include "esphome/components/text_sensor/text_sensor.h"
#include "esphome/components/binary_sensor/binary_sensor.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/api/custom_api_device.h"

namespace esphome {
namespace rubiks_solver {

// ── Types ─────────────────────────────────────────────────────────────────────

enum class SolverState {
  IDLE,
  SCANNING,    // servo steps running to position cube at a face
  SCAN_WAIT,   // waiting for HA to call face_scan_done
  SOLVING,     // servo steps running for solution execution
  SERVO_TEST,  // planned test move running — returns to IDLE when steps exhausted
  ERROR,
};

enum class TopCover { OPEN, CLOSED, FLIP };

struct ServoStep {
  enum Target { TOP, BOTTOM } target;
  float    position;      // ESPHome normalised -1.0 .. 1.0
  uint32_t duration_ms;   // wait this long after issuing command before next step
};

// ── Component ─────────────────────────────────────────────────────────────────

class RubiksSolverComponent : public Component, public api::CustomAPIDevice {
 public:
  void setup() override;
  void loop()  override;
  void dump_config() override;

  // ── Wired by __init__.py codegen ─────────────────────────────────────────────
  void set_top_servo(servo::Servo *s)                    { top_servo_      = s; }
  void set_bottom_servo(servo::Servo *s)                 { bottom_servo_   = s; }
  void set_status_sensor(text_sensor::TextSensor *s)     { status_sensor_  = s; }
  void set_believed_home_sensor(binary_sensor::BinarySensor *s) { believed_home_sensor_ = s; }
  void set_moves_remaining_sensor(sensor::Sensor *s)     { moves_remaining_sensor_ = s; }

  // Top servo position settings (raw duty 0-1023, from Cubotino_settings.txt)
  void set_t_servo_flip(int v)        { d_t_flip_       = v; }
  void set_t_servo_open(int v)        { d_t_open_       = v; }
  void set_t_servo_close(int v)       { d_t_close_      = v; }
  void set_t_servo_rel_offset(int v)  { d_t_rel_offset_ = v; }
  // Top servo timing settings (ms)
  void set_t_flip_to_close_time(uint32_t v) { t_flip_to_close_time_ = v; }
  void set_t_close_to_flip_time(uint32_t v) { t_close_to_flip_time_ = v; }
  void set_t_flip_open_time(uint32_t v)     { t_flip_open_time_     = v; }
  void set_t_open_close_time(uint32_t v)    { t_open_close_time_    = v; }
  // Bottom servo position settings (raw duty 0-1023)
  void set_b_servo_ccw(int v)         { d_b_ccw_         = v; }
  void set_b_home(int v)              { d_b_home_        = v; }
  void set_b_servo_cw(int v)          { d_b_cw_          = v; }
  void set_b_extra_sides(int v)       { d_b_extra_sides_ = v; }
  void set_b_extra_home(int v)        { d_b_extra_home_  = v; }
  // Bottom servo timing settings (ms)
  void set_b_spin_time(uint32_t v)    { b_spin_time_   = v; }
  void set_b_rotate_time(uint32_t v)  { b_rotate_time_ = v; }
  void set_b_rel_time(uint32_t v)     { b_rel_time_    = v; }
  void set_speed_multiplier(float m)  { speed_mul_     = m; }

  // ── API action handlers ───────────────────────────────────────────────────────
  void start_scan();
  void advance_scan();
  void execute_solution(const std::string &solution);
  void stop();
  // Call after visually confirming the arm/turntable aren't in a colliding position —
  // only needed when setup() skipped the automatic boot glide (see setup()'s comment).
  void confirm_safe_and_home();

  // ── Servo test / calibration helpers (IDLE only, no state change) ─────────────
  void servo_centre();        // both servos → 7.5% idle position
  void servo_top_flip();      // top → flip position
  void servo_top_open();      // top → open position
  void servo_top_close();     // top → close/constrain position
  void servo_bottom_ccw();    // bottom → full CCW end
  void servo_bottom_home();   // bottom → home / centre
  void servo_bottom_cw();     // bottom → full CW end
  void test_rotate_cw_home();  // planned CW-out → home-with-release cycle
  void test_rotate_ccw_home(); // planned CCW-out → home-with-release cycle
  void test_flip(int count);   // flip cube N times (cover open→flip→open)
  void test_spin_cw_home();    // spin whole cube CW then back to home
  void test_spin_ccw_home();   // spin whole cube CCW then back to home
  void test_scan_cycle();      // each press advances to the next face scan position (W→B→Y→G→R→O, loops)
  void test_scan_return_home(); // isolates advance_scan()'s post-scan flip/spin_home/flip sequence

  // Recompute float position cache from raw duty members.
  // Called from setup() and from HA number entity on_value lambdas.
  void recompute_positions();

  // Accessors for api.respond in execute_solution action.
  bool solution_accepted() const { return solution_accepted_; }
  int  move_count()        const { return robot_move_count_; }

 protected:
  // ── Hardware ──────────────────────────────────────────────────────────────────
  servo::Servo              *top_servo_     {nullptr};
  servo::Servo              *bottom_servo_  {nullptr};
  text_sensor::TextSensor   *status_sensor_ {nullptr};
  binary_sensor::BinarySensor *believed_home_sensor_ {nullptr};
  sensor::Sensor            *moves_remaining_sensor_ {nullptr};

  // ── Raw duty settings (0-1023 MicroPython scale; defaults from Cubotino_settings.txt)
  // Set before setup() via YAML-generated set_* calls; converted to floats in setup().
  // Top servo
  int d_t_flip_        {54};   // flipper arm at flip position
  int d_t_open_        {68};   // flipper arm raised / clear
  int d_t_close_       {76};   // flipper arm lowered / constraining
  int d_t_rel_offset_  {0};    // release offset subtracted from close (reduces contact force)
  // Bottom servo
  int d_b_ccw_         {51};   // full CCW end
  int d_b_home_        {76};   // home / centre
  int d_b_cw_          {101};  // full CW end
  int d_b_extra_sides_ {2};    // over-rotation margin at CW/CCW ends (tension release)
  int d_b_extra_home_  {3};    // over-rotation margin when returning to home

  // ── Computed servo position values (ESPHome -1.0..1.0, filled in setup()) ─────
  // Top servo — flipper arm
  float t_flip_v_   {};   // raise arm to flip position
  float t_open_v_   {};   // raise arm to open/clear position
  float t_close_v_  {};   // lower arm to constrain top 2 layers
  float t_rel_v_    {};   // slight release after close (reduce contact force)
  // Bottom servo — cube holder / rotator
  float b_ccw_v_           {};   // full CCW end
  float b_home_v_          {};   // centre / home
  float b_cw_v_            {};   // full CW end
  float b_ccw_rel_v_       {};   // CCW end + extra_sides (tension release)
  float b_cw_rel_v_        {};   // CW end  - extra_sides
  float b_home_from_cw_v_  {};   // overshoot past home when returning from CW
  float b_home_from_ccw_v_ {};   // overshoot past home when returning from CCW

  float    speed_mul_                {1.0f};  // multiplies all step durations; >1 = slower; set via HA number entity

  // Cross-servo timing guard, maintained entirely inside append_step_() — see its
  // comment. Each holds "how long the other servo's most recently queued move still
  // needs before it's actually done"; consumed (and reset to 0) the next time a step
  // is queued for that other servo. This is plan-time bookkeeping — it shapes the
  // durations baked into steps_ before anything runs. See top_dispatch_ms_ etc.
  // below for the independent, dispatch-time check of the same constraint.
  uint32_t pending_bottom_travel_ms_ {0};
  uint32_t pending_top_travel_ms_    {0};

  // Cross-servo dispatch guard — belt-and-suspenders, independent of the plan-time
  // math above. Records, in real wall-clock time, when each servo's most recently
  // *dispatched* step should actually finish; loop() checks this before firing the
  // other servo's next step. Mirrors CUBOTino's b_servo_operable/b_servo_stopped
  // flags (Cubotino_servos.py) — "don't move me until the other side is confirmed
  // settled" — but checked live against the clock at the moment of dispatch rather
  // than baked into a duration at plan time. Normal operation should never trip
  // this (pending_*_travel_ms_ already keeps step durations long enough); it exists
  // so a bug in that bookkeeping, a future call site that bypasses append_step_(),
  // or stale plan state after an abort can't turn into an actual physical collision.
  uint32_t top_dispatch_ms_         {0};
  uint32_t top_step_duration_ms_    {0};
  uint32_t bottom_dispatch_ms_      {0};
  uint32_t bottom_step_duration_ms_ {0};
  // Logs once per hold episode, not once per loop() tick — a hold can last many ticks.
  bool     dispatch_guard_warned_   {false};

  // ── Timing values (ms; defaults from Cubotino_settings.txt) ───────────────────
  // Top servo travel times
  uint32_t t_flip_to_close_time_ {900};    // flip position  → close position
  uint32_t t_close_to_flip_time_ {1000};   // close position → flip position
  uint32_t t_flip_open_time_     {800};    // between flip and open positions
  uint32_t t_open_close_time_    {300};    // between open and close positions
  // Bottom servo travel times
  uint32_t b_spin_time_   {1100};   // 90° full-cube spin
  uint32_t b_rotate_time_ {1200};   // 90° bottom-layer rotation
  uint32_t b_rel_time_    {100};    // tension-release micro-move

  // Set whenever physical position becomes uncertain — an unclean reset (setup()) or
  // stop() interrupting a sequence that wasn't already IDLE (mid-motion, or paused
  // mid-scan at some non-home face). start_scan()/execute_solution() unconditionally
  // assume home/open when planning; this blocks that assumption from being trusted
  // again until a human confirms it's safe via confirm_safe_and_home(). Before this,
  // the unclean-reset case was advisory only (state_ was already IDLE by the time a
  // human could react) — this makes it actually enforced, for both trigger cases.
  bool needs_confirm_before_move_ {false};

  // Optimistic — derived from the commanded move sequence (plan_top_cover_/plan_b_home_),
  // not real position feedback (none exists). False the instant any step is queued
  // (append_step_()); recomputed true/false at each sequence completion in fire_done_()
  // based on whether that sequence's planned end state was cover-open + bottom-home.
  bool believed_home_ {false};

  // ── Execution state ───────────────────────────────────────────────────────────
  SolverState            state_                {SolverState::IDLE};
  std::vector<ServoStep> steps_                {};
  size_t                 step_idx_             {0};
  uint32_t               step_start_ms_        {0};
  int                    scan_face_idx_        {0};
  int                    test_scan_face_idx_   {0};  // persists between test_scan_cycle() presses
  std::string            solution_             {};
  bool                   solution_accepted_    {false};
  int                    robot_move_count_     {0};

  // Progress tracking for moves_remaining_sensor_ — populated once per plan_solution_()
  // by mark_action_boundary_(), called from plan_flip_/plan_spin_/plan_rotate_ right
  // after each physical robot action's steps are appended. Each entry is the step_idx_
  // value at which that action's steps are fully queued; loop() advances
  // robot_actions_done_ as step_idx_ crosses each boundary. Purely additive bookkeeping
  // — never affects step timing/positions, so it can't introduce a collision risk.
  std::vector<size_t>   action_boundaries_    {};
  size_t                robot_actions_done_   {0};

  // ── Plan-time state (reset before each plan_solution_ / plan_scan_) ───────────
  // Tracks cover and bottom position AS STEPS ARE PLANNED (not during execution).
  TopCover plan_top_cover_  {TopCover::OPEN};
  bool     plan_b_home_     {true};
  bool     plan_b_cw_pos_   {false};
  bool     plan_b_ccw_pos_  {false};

  // ── Internal helpers ──────────────────────────────────────────────────────────
  static float duty_to_esphome(int duty);   // raw 0-1023 duty → ESPHome -1.0..1.0

  void append_step_(ServoStep::Target target, float pos, uint32_t dur_ms);
  void mark_action_boundary_();  // records steps_.size() as the end of one robot action

  void plan_ensure_cover_open_();
  void plan_ensure_cover_closed_();

  void plan_flip_  (int count, char next_token);
  void plan_spin_  (int dir);
  void plan_rotate_(int dir);

  void plan_solution_();
  void plan_scan_move_(int face_idx);

  void set_believed_home_(bool home);
  void publish_status_(const std::string &s);
  void fire_ha_event_(const std::string &event, const std::string &data = "");
  void fire_done_();
  void reset_();
  void queue_boot_glide_();  // shared by setup() (clean reset) and confirm_safe_and_home()
};

}  // namespace rubiks_solver
}  // namespace esphome
