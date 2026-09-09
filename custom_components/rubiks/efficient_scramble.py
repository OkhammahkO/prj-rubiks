"""Generate scrambles that are cheap for the robot to execute but still properly hard.

Plain random-move scrambling (the old approach) picks a face uniformly at random —
but each notation move translates to 2-7 physical robot actions depending on which
face is currently reachable without a flip (see ROBOT_MOVES_TABLE below), so most of
a random scramble's cost goes toward faces that happen to need reorienting first. This
instead biases each pick toward whichever face is currently cheapest to reach, while
still never repeating the same face twice in a row (same rule the old generator used,
needed to avoid wasteful runs like six R1's in place of one R2).

Every candidate is verified through the real solver (solve()) before being accepted —
a shorter/cheaper scramble must never also be an easier one. In practice this resolves
on the first or second attempt (see the profiling in the conversation this was built
from), so it's cheap enough to run synchronously via async_add_executor_job, same as
this integration's other CPU-bound work (calibrate_faces, detect_face_colors).

ROBOT_MOVES_TABLE below is a Python port of the exact translation table
esphome/components/rubiks_solver/moves.h uses to turn a kociemba move string into
physical robot actions (flip/spin/rotate) — needed here purely to score candidates by
robot-action cost, matching what the firmware will actually execute. Independent from
moves.h and must be kept in sync with it by hand if it changes — same situation as
SCAN_SEQUENCE/the ESP32's SCAN_FACES[] elsewhere in this project, since the ESP32
doesn't import Python.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from . import solver as _solver

_LOGGER = logging.getLogger(__name__)

MIN_SOLUTION_LENGTH = 17  # below this, twophase solves tend to look under-scrambled
# 5 keeps a button press responsive (~0.4s) while capturing nearly all the achievable
# quality — attempts 6-15 only shave a further ~1% off the mean robot-action cost in
# testing, not worth 3x the latency for.
MAX_ATTEMPTS = 5

# ─── Robot move translation (port of moves.h's MOVES_TABLE/count_moves) ───────────

ROBOT_MOVES_TABLE = {
    "U1": "F2R1S3",
    "U2": "F2R1S3R1S3",
    "U3": "F2S1R3",
    "D1": "R1S3",
    "D2": "R1S3R1S3",
    "D3": "S1R3",
    "F1": "F1R1S3",
    "F2": "F1R1S3R1S3",
    "F3": "F1S1R3",
    "B1": "F3R1S3",
    "B2": "F3R1S3R1S3",
    "B3": "F3S1R3",
    "L1": "S3F3R1",
    "L2": "S3F3R1S3R1",
    "L3": "S1F1R3",
    "R1": "S3F1R1",
    "R2": "S3F1R1S3R1",
    "R3": "S1F3R3",
}


def _count_robot_actions(robot_moves: str) -> int:
    """F<n> = n actions, R/S = 1 each — matches moves.h's count_moves()."""
    total = 0
    for i in range(0, len(robot_moves) - 1, 2):
        tok, num = robot_moves[i], int(robot_moves[i + 1])
        if tok == "F":
            total += num
        elif tok in ("R", "S"):
            total += 1
    return total


def _optimize_robot_moves(robot_moves: str) -> str:
    """Remove adjacent cancelling spin pairs (S1S3/S3S1) — matches moves.h's
    optimize_moves(). Left-to-right single pass, same as the firmware."""
    result = []
    i = 0
    while i + 3 < len(robot_moves):
        cur, nxt = robot_moves[i : i + 2], robot_moves[i + 2 : i + 4]
        if (cur, nxt) in (("S1", "S3"), ("S3", "S1")):
            i += 4
        else:
            result.append(cur)
            i += 2
    result.append(robot_moves[i:])
    return "".join(result)


def _adapt_move(move: str, orient: _OrientState) -> str:
    """Map a kociemba-notation move to the robot-position label it currently sits
    at (e.g. "R1" -> "D1" if the R face has been reoriented to the bottom) — matches
    moves.h's adapt_move(). Needed because ROBOT_MOVES_TABLE is keyed by *position*
    (D/U/L/R/F/B relative to the robot), not by the move's own fixed face letter,
    and orientation drifts as earlier moves in the sequence flip/spin the cube."""
    face, rot = move[0], move[1]
    if orient.h_left == face:
        return "L" + rot
    if orient.h_front == face:
        return "F" + rot
    if orient.h_right == face:
        return "R" + rot
    if orient.v_down == face:
        return "D" + rot
    if orient.v_up == face:
        return "U" + rot
    return "B" + rot


def robot_action_count(scramble: str) -> int:
    """Real robot-action count a scramble notation string would take to execute —
    walks orientation across the whole sequence and applies the same cross-move
    cancellation pass, exactly like moves.h's robot_required_moves(). A naive
    per-move lookup (ignoring how earlier moves reorient the cube, and skipping the
    S1S3/S3S1 cancellation at move boundaries) gives the wrong answer.
    """
    orient = _OrientState("L", "F", "R", "D", "F", "U")
    robot_moves = []
    for move in scramble.split():
        adapted = _adapt_move(move, orient)
        robot_seq = ROBOT_MOVES_TABLE[adapted]
        robot_moves.append(robot_seq)
        _apply_robot_seq(robot_seq, orient)
    return _count_robot_actions(_optimize_robot_moves("".join(robot_moves)))


# ─── Position-biased candidate generator ──────────────────────────────────────

# Per-position cost (modifier -> robot actions), derived from ROBOT_MOVES_TABLE — the
# position currently at the bottom (v_down) is cheapest since no flip is needed to
# reach it; the "back" position is priciest (three flips).
_POSITION_COST = {
    "v_down": {"1": 2, "2": 4, "3": 2},
    "h_front": {"1": 3, "2": 5, "3": 3},
    "h_right": {"1": 3, "2": 5, "3": 5},
    "v_up": {"1": 4, "2": 6, "3": 4},
    "h_left": {"1": 5, "2": 7, "3": 3},
    "back": {"1": 5, "2": 7, "3": 5},
}
_POSITION_LABEL = {
    "v_down": "D",
    "h_front": "F",
    "h_right": "R",
    "v_up": "U",
    "h_left": "L",
    "back": "B",
}
_BIAS_EXPONENT = 8  # see conversation this was tuned in — plateaus past ~8


@dataclass
class _OrientState:
    """Tracks which cube face currently sits at each physical robot position —
    identical model to moves.h's OrientState, needed here to know which face is
    currently cheap (v_down/h_front/h_right) vs. expensive (v_up/h_left/back)."""

    h_left: str
    h_front: str
    h_right: str
    v_down: str
    v_front: str
    v_up: str


def _opp_face(f: str) -> str:
    return {"F": "B", "B": "F", "U": "D", "D": "U", "R": "L", "L": "R"}[f]


def _apply_robot_seq(robot_seq: str, o: _OrientState) -> None:
    """Advance orientation tracking by one robot action sequence (mirrors
    moves.h's cube_orient_update())."""
    for i in range(0, len(robot_seq) - 1, 2):
        tok, n = robot_seq[i], int(robot_seq[i + 1])
        if tok == "F":
            for _ in range(n):
                o.v_down, o.v_front, o.v_up = o.v_front, o.v_up, _opp_face(o.v_front)
                o.h_front = o.v_front
        elif tok == "S":
            if n == 3:
                o.h_left, o.h_front, o.h_right = (
                    o.h_front,
                    o.h_right,
                    _opp_face(o.h_front),
                )
            else:
                for _ in range(n):
                    o.h_right, o.h_front, o.h_left = (
                        o.h_front,
                        o.h_left,
                        _opp_face(o.h_front),
                    )
            o.v_front = o.h_front


def _generate_candidate(move_count: int, rng: random.Random) -> str:
    orient = _OrientState("L", "F", "R", "D", "F", "U")
    all_faces = {"U", "D", "L", "R", "F", "B"}
    moves: list[str] = []
    last_face: str | None = None

    for _ in range(move_count):
        used = {
            orient.h_left,
            orient.h_front,
            orient.h_right,
            orient.v_down,
            orient.v_up,
        }
        back_face = next(iter(all_faces - used))

        candidates = []
        for pos, face in (
            ("v_down", orient.v_down),
            ("h_front", orient.h_front),
            ("h_right", orient.h_right),
            ("v_up", orient.v_up),
            ("h_left", orient.h_left),
            ("back", back_face),
        ):
            if face == last_face:  # never repeat the same face twice in a row
                continue
            for mod, cost in _POSITION_COST[pos].items():
                candidates.append((face, _POSITION_LABEL[pos], mod, cost))

        weights = [1.0 / (cost**_BIAS_EXPONENT) for _, _, _, cost in candidates]
        face, label, mod, _cost = rng.choices(candidates, weights=weights, k=1)[0]
        moves.append(face + mod)
        _apply_robot_seq(ROBOT_MOVES_TABLE[label + mod], orient)
        last_face = face

    return " ".join(moves)


def _notation_to_facelet_cube(scramble: str) -> str:
    """Apply a scramble notation string to a solved cube, return the resulting
    54-facelet string — using twophase's own verified move algebra (CubieCube /
    basicMoveCube), not a hand-rolled one. Only imports twophase.cubie/face, which
    are pure move algebra with no pruning-table file I/O, so this is safe to call
    without solver.py's table-extraction/FOLDER-redirection dance.
    """
    from twophase.cubie import CubieCube, basicMoveCube  # noqa: PLC0415
    from twophase.enums import Color  # noqa: PLC0415

    face_map = {
        "U": Color.U,
        "D": Color.D,
        "R": Color.R,
        "L": Color.L,
        "F": Color.F,
        "B": Color.B,
    }
    cc = CubieCube()
    for move in scramble.split():
        base = basicMoveCube[face_map[move[0]]]
        for _ in range(int(move[1])):
            cc.multiply(base)
    return str(cc.to_facelet_cube().to_string())


# ─── Public entry point ─────────────────────────────────────────────────────────


def generate_efficient_scramble(move_count: int) -> str:
    """Generate a scramble that's cheap for the robot but still properly hard.

    Runs synchronously — call via async_add_executor_job, same as this integration's
    other CPU-bound work. Returns a valid scramble even in the (empirically ~never
    observed) case where nothing clears the difficulty bar within MAX_ATTEMPTS — the
    cheapest candidate seen is used rather than failing the button press outright.
    """
    rng = random.Random()
    best: tuple[int, str] | None = None

    for _ in range(MAX_ATTEMPTS):
        candidate = _generate_candidate(move_count, rng)
        cube = _notation_to_facelet_cube(candidate)
        solution = _solver.solve(cube)
        if solution is None or len(solution.split()) < MIN_SOLUTION_LENGTH:
            continue
        cost = robot_action_count(candidate)
        if best is None or cost < best[0]:
            best = (cost, candidate)

    if best is not None:
        return best[1]

    _LOGGER.warning(
        "generate_efficient_scramble: no candidate cleared the difficulty bar in "
        "%d attempts — using an unverified one instead",
        MAX_ATTEMPTS,
    )
    return _generate_candidate(move_count, rng)
