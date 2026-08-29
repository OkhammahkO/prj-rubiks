#pragma once

// Port of CUBOTino_Files/ESP32_files/Cubotino_moves.py (Andrea Favero, April 2022).
// Translates a kociemba solution string into a robot move string.
//
// Robot move tokens:
//   F<n>  flip cube n times (front face → bottom), cover OPEN
//   S1    spin full cube 90° CW,                   cover OPEN
//   S3    spin full cube 90° CCW,                  cover OPEN
//   R1    rotate bottom layer 90° CW,              cover CLOSED
//   R3    rotate bottom layer 90° CCW,             cover CLOSED
//
// Starting orientation: White UP, Green FRONT  (matches solver.py: W=U Y=D G=F B=B O=L R=R).
//
// Test vectors (verified against Python source):
//   "R1"               → "S3F1R1"              total  3
//   "U1"               → "F2R1S3"              total  4
//   "U2 D2 R2 L2 F2 B2"  → (36 actions)
//   "U2 L1 R1 D2 B2 ..." → (94 actions)

#include <string>
#include <cstddef>

namespace esphome {
namespace rubiks_solver {
namespace moves {

// ─── Orientation state ────────────────────────────────────────────────────────

// Tracks which cube face is currently at each physical robot position.
// h_* = horizontal ring (left / front / right).
// v_* = vertical slice  (down / front / up).
// Invariant: h_front == v_front at all times.
struct OrientState {
  std::string h_left, h_front, h_right;
  std::string v_down, v_front, v_up;
};

// Canonical start position: White UP, Green FRONT.
inline OrientState starting_orientation() {
  return {"L", "F", "R",   "D", "F", "U"};
}

// ─── Lookup table: kociemba move → robot token string ─────────────────────────

struct MoveEntry {
  char key[3];
  char value[13];
};

//                 kociemba   robot tokens
static const MoveEntry MOVES_TABLE[] = {
    { "U1",   "F2R1S3"     },   { "U2",   "F2R1S3R1S3" },   { "U3",   "F2S1R3"     },
    { "D1",   "R1S3"       },   { "D2",   "R1S3R1S3"   },   { "D3",   "S1R3"       },
    { "F1",   "F1R1S3"     },   { "F2",   "F1R1S3R1S3" },   { "F3",   "F1S1R3"     },
    { "B1",   "F3R1S3"     },   { "B2",   "F3R1S3R1S3" },   { "B3",   "F3S1R3"     },
    { "L1",   "S3F3R1"     },   { "L2",   "S3F3R1S3R1" },   { "L3",   "S1F1R3"     },
    { "R1",   "S3F1R1"     },   { "R2",   "S3F1R1S3R1" },   { "R3",   "S1F3R3"     },
};

static const char *lookup_move(const std::string &key) {
  for (const auto &entry : MOVES_TABLE)
    if (key == entry.key) return entry.value;
  return nullptr;
}

// ─── Orientation effects ──────────────────────────────────────────────────────

static std::string opp_face(const std::string &f) {
  if (f == "F") return "B";   if (f == "B") return "F";
  if (f == "U") return "D";   if (f == "D") return "U";
  if (f == "R") return "L";   if (f == "L") return "R";
  return "?";
}

// Flip: front face → bottom.   D←F, F←U, U←opp(D)
static void flip_effect(OrientState &o) {
  o.v_down  = o.v_front;
  o.v_front = o.v_up;
  o.v_up    = opp_face(o.v_down);
  o.h_front = o.v_front;         // keep h_front / v_front in sync
}

// Spin CW  (viewed from above): R←F, F←L, L←opp(R)
static void spinCW_effect(OrientState &o) {
  o.h_right = o.h_front;
  o.h_front = o.h_left;
  o.h_left  = opp_face(o.h_right);
  o.v_front = o.h_front;
}

// Spin CCW (viewed from above): L←F, F←R, R←opp(L)
static void spinCCW_effect(OrientState &o) {
  o.h_left  = o.h_front;
  o.h_front = o.h_right;
  o.h_right = opp_face(o.h_left);
  o.v_front = o.h_front;
}

// Update orientation for one robot token string (e.g. "F2R1S3").
// R tokens do not affect cube orientation (bottom layer only).
inline void cube_orient_update(const std::string &movement, OrientState &orient) {
  for (size_t i = 0; i + 1 < movement.size(); i++) {
    if (movement[i] == 'F') {
      int n = movement[i + 1] - '0';
      for (int j = 0; j < n; j++) flip_effect(orient);

    } else if (movement[i] == 'S') {
      int n = movement[i + 1] - '0';
      if (n == 3) { spinCCW_effect(orient); }
      else        { for (int j = 0; j < n; j++) spinCW_effect(orient); }
    }
  }
}

// ─── Move adaptation ──────────────────────────────────────────────────────────

// Map a kociemba face label to the physical position where that face currently
// sits on the robot, then return that position + the original rotation suffix.
// e.g. if the R face has been spun to the L slot: "R1" → "L1".
inline std::string adapt_move(const std::string &move, const OrientState &orient) {
  const std::string face(1, move[0]);
  const char        rot = move[1];

  if (orient.h_left  == face) return std::string("L") + rot;
  if (orient.h_front == face) return std::string("F") + rot;
  if (orient.h_right == face) return std::string("R") + rot;
  if (orient.v_down  == face) return std::string("D") + rot;
  if (orient.v_up    == face) return std::string("U") + rot;
  return                             std::string("B") + rot;   // v_front==h_front already checked; must be back
}

// ─── Post-processing ──────────────────────────────────────────────────────────

// Remove adjacent cancelling spin pairs (S1S3, S3S1) in one left-to-right pass.
inline std::string optimize_moves(const std::string &moves) {
  std::string result;
  result.reserve(moves.size());
  size_t i = 0;
  while (i + 3 < moves.size()) {
    std::string cur  = moves.substr(i, 2);
    std::string next = moves.substr(i + 2, 2);
    if ((cur == "S1" && next == "S3") || (cur == "S3" && next == "S1")) {
      i += 4;                   // skip both — they cancel each other
    } else {
      result += cur;
      i += 2;
    }
  }
  while (i < moves.size()) result += moves[i++];   // append any trailing token
  return result;
}

// Count total physical robot actions:  F<n> = n,  R or S = 1 each.
inline int count_moves(const std::string &moves) {
  int total = 0;
  for (size_t i = 0; i + 1 < moves.size(); i += 2) {
    char tok = moves[i];
    int  num = moves[i + 1] - '0';
    if      (tok == 'F')               total += num;
    else if (tok == 'R' || tok == 'S') total += 1;
  }
  return total;
}

// ─── Main pipeline ────────────────────────────────────────────────────────────

// Normalize a kociemba/test-button solution string to "face+digit" pairs.
// Handles bare face letters ("D"→"D1"), prime notation ("D'"→"D3"),
// and already-digit-suffixed forms ("D1","D2","D3"). Strips spaces.
inline std::string normalize_solution(const std::string &solution) {
  std::string out;
  out.reserve(solution.size() * 2);
  for (size_t i = 0; i < solution.size(); ) {
    char c = solution[i];
    if (c == ' ') { i++; continue; }
    out += c;   // face letter (U/D/R/L/F/B)
    i++;
    if (i < solution.size() && solution[i] == '\'') {
      out += '3'; i++;
    } else if (i < solution.size() && solution[i] >= '1' && solution[i] <= '3') {
      out += solution[i]; i++;
    } else {
      out += '1';   // bare face letter = single CW quarter turn
    }
  }
  return out;
}

// Translate a kociemba solution string ("U2 R F' ...") into an optimised
// robot move string ("F2R1S3R1S3...").  Returns "" on empty or malformed input.
// Accepts both bare kociemba notation ("D", "D'") and digit-suffixed ("D1", "D3").
inline std::string robot_required_moves(const std::string &solution) {
  std::string normalized = normalize_solution(solution);

  if (normalized.empty() || normalized.size() % 2 != 0) return "";

  OrientState orient = starting_orientation();
  std::string moves;

  for (size_t i = 0; i + 1 < normalized.size(); i += 2) {
    std::string block   = normalized.substr(i, 2);
    std::string adapted = adapt_move(block, orient);

    const char *robot_seq = lookup_move(adapted);
    if (robot_seq == nullptr) return "";      // invalid adapted move — shouldn't happen

    moves += robot_seq;
    cube_orient_update(robot_seq, orient);
  }

  return optimize_moves(moves);
}

}  // namespace moves
}  // namespace rubiks_solver
}  // namespace esphome
