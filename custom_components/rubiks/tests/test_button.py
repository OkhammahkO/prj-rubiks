"""Tests for button.py — scramble generation."""

from __future__ import annotations

from custom_components.rubiks.efficient_scramble import (
    MIN_SOLUTION_LENGTH,
    _notation_to_facelet_cube,
    generate_efficient_scramble,
    robot_action_count,
)
from custom_components.rubiks.solver import solve

_FACES = {"U", "D", "L", "R", "F", "B"}
_MODIFIERS = {"1", "2", "3"}


class TestGenerateEfficientScramble:
    """Real, end-to-end tests — correctness here depends on the actual twophase
    solver's difficulty verification, so these aren't mocked out."""

    def test_move_count(self) -> None:
        """Returns exactly move_count moves."""
        scramble = generate_efficient_scramble(16)
        assert len(scramble.split()) == 16

    def test_move_format(self) -> None:
        """Every move is a valid face + modifier pair."""
        scramble = generate_efficient_scramble(16)
        for move in scramble.split():
            assert len(move) == 2
            assert move[0] in _FACES
            assert move[1] in _MODIFIERS

    def test_no_consecutive_same_face(self) -> None:
        """Never repeats the same face twice in a row — avoids wasteful runs like
        six R1's in place of one R2."""
        scramble = generate_efficient_scramble(16)
        faces = [move[0] for move in scramble.split()]
        for a, b in zip(faces, faces[1:], strict=False):
            assert a != b

    def test_is_properly_hard(self) -> None:
        """The resulting cube state genuinely needs MIN_SOLUTION_LENGTH+ moves to
        re-solve — not just nominally scrambled."""
        scramble = generate_efficient_scramble(16)
        cube = _notation_to_facelet_cube(scramble)
        solution = solve(cube)
        assert solution is not None
        assert len(solution.split()) >= MIN_SOLUTION_LENGTH

    def test_randomness(self) -> None:
        """Two generated scrambles are (almost certainly) different."""
        assert generate_efficient_scramble(16) != generate_efficient_scramble(16)


class TestRobotActionCount:
    """The moves.h-port cost model used to bias/score candidates."""

    def test_matches_moves_h_test_vectors(self) -> None:
        """Cross-checked against moves.h's own header comment test vectors."""
        assert robot_action_count("R1") == 3
        assert robot_action_count("U1") == 4
        assert robot_action_count("U2 D2 R2 L2 F2 B2") == 36
