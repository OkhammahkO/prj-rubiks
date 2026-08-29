"""Tests for button.py — scramble generation."""

from __future__ import annotations

from custom_components.rubiks.button import generate_scramble
from custom_components.rubiks.const import SCRAMBLE_FACES, SCRAMBLE_MODIFIERS


class TestGenerateScramble:
    """Test the plain random-move scramble generator."""

    def test_move_count(self) -> None:
        """Returns exactly move_count moves."""
        scramble = generate_scramble(26)
        assert len(scramble.split()) == 26

    def test_zero_moves(self) -> None:
        """Zero moves returns an empty string."""
        assert generate_scramble(0) == ""

    def test_move_format(self) -> None:
        """Every move is a valid face + modifier pair."""
        scramble = generate_scramble(40)
        for move in scramble.split():
            assert len(move) == 2
            assert move[0] in SCRAMBLE_FACES
            assert move[1] in SCRAMBLE_MODIFIERS

    def test_no_consecutive_same_face(self) -> None:
        """Never repeats the same face twice in a row."""
        scramble = generate_scramble(100)
        faces = [move[0] for move in scramble.split()]
        for a, b in zip(faces, faces[1:], strict=False):
            assert a != b

    def test_randomness(self) -> None:
        """Two generated scrambles of reasonable length are (almost certainly) different."""
        assert generate_scramble(30) != generate_scramble(30)
