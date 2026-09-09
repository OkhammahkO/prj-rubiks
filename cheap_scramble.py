import random
import kociemba
from dataclasses import dataclass


# ============================================================
# CONFIGURATION
# ============================================================

NUM_RESULTS = 20
ITERATIONS = 50_000

# Maximum number of physical operations allowed.
MAX_ROTATIONS = 12
MAX_FLIPS = 6

# Minimum Kociemba solution length.
MIN_SOLUTION_LENGTH = 17

# Estimated robot costs.
#
# Change these to match your actual Cubotino timings.
ROTATE_90_COST = 1.0
ROTATE_180_COST = 1.5
FLIP_COST = 1.0

# Probability of choosing a 180 degree rotation.
P_ROTATE_180 = 0.25

# Probability of flipping after a rotation.
P_FLIP = 0.45


# ============================================================
# CUBE REPRESENTATION
# ============================================================

# Face order used by Kociemba:
#
# U R F D L B
#
# Each face contains 9 stickers.
SOLVED = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"


# ============================================================
# BASIC FACE TURN IMPLEMENTATION
# ============================================================


def rotate_face(face):
    """
    Rotate one 3x3 face clockwise.
    """
    return (
        face[6]
        + face[3]
        + face[0]
        + face[7]
        + face[4]
        + face[1]
        + face[8]
        + face[5]
        + face[2]
    )


def turn_cube(cube, move):
    """
    Apply a standard Singmaster face move.

    Supported:
        U U' U2
        R R' R2
        F F' F2
        D D' D2
        L L' L2
        B B' B2
    """

    faces = {
        "U": list(cube[0:9]),
        "R": list(cube[9:18]),
        "F": list(cube[18:27]),
        "D": list(cube[27:36]),
        "L": list(cube[36:45]),
        "B": list(cube[45:54]),
    }

    face = move[0]
    suffix = move[1:] if len(move) > 1 else ""

    turns = {
        "": 1,
        "'": 3,
        "2": 2,
    }[suffix]

    for _ in range(turns):
        faces[face] = list(rotate_face(faces[face]))

        # Adjacent strips.
        if face == "U":
            f = faces["F"][0:3]
            r = faces["R"][0:3]
            b = faces["B"][0:3]
            l = faces["L"][0:3]

            faces["F"][0:3] = l
            faces["R"][0:3] = f
            faces["B"][0:3] = r
            faces["L"][0:3] = b

        elif face == "D":
            f = faces["F"][6:9]
            r = faces["R"][6:9]
            b = faces["B"][6:9]
            l = faces["L"][6:9]

            faces["F"][6:9] = r
            faces["L"][6:9] = f
            faces["B"][6:9] = l
            faces["R"][6:9] = b

        elif face == "F":
            u = faces["U"][6:9]
            r = [faces["R"][i] for i in (0, 3, 6)]
            d = faces["D"][0:3]
            l = [faces["L"][i] for i in (2, 5, 8)]

            faces["U"][6:9] = l[::-1]
            faces["R"][0] = u[0]
            faces["R"][3] = u[1]
            faces["R"][6] = u[2]

            faces["D"][0:3] = r[::-1]

            faces["L"][2] = d[0]
            faces["L"][5] = d[1]
            faces["L"][8] = d[2]

        elif face == "B":
            u = faces["U"][0:3]
            r = [faces["R"][2], faces["R"][5], faces["R"][8]]
            d = faces["D"][6:9]
            l = [faces["L"][0], faces["L"][3], faces["L"][6]]

            faces["U"][0:3] = r
            faces["L"][0] = d[2]
            faces["L"][3] = d[1]
            faces["L"][6] = d[0]

            faces["D"][6:9] = l
            faces["R"][2] = u[2]
            faces["R"][5] = u[1]
            faces["R"][8] = u[0]

        elif face == "R":
            u = [faces["U"][2], faces["U"][5], faces["U"][8]]
            f = [faces["F"][2], faces["F"][5], faces["F"][8]]
            d = [faces["D"][2], faces["D"][5], faces["D"][8]]
            b = [faces["B"][0], faces["B"][3], faces["B"][6]]

            faces["U"][2] = b[2]
            faces["U"][5] = b[1]
            faces["U"][8] = b[0]

            faces["F"][2] = u[0]
            faces["F"][5] = u[1]
            faces["F"][8] = u[2]

            faces["D"][2] = f[0]
            faces["D"][5] = f[1]
            faces["D"][8] = f[2]

            faces["B"][0] = d[2]
            faces["B"][3] = d[1]
            faces["B"][6] = d[0]

        elif face == "L":
            u = [faces["U"][0], faces["U"][3], faces["U"][6]]
            f = [faces["F"][0], faces["F"][3], faces["F"][6]]
            d = [faces["D"][0], faces["D"][3], faces["D"][6]]
            b = [faces["B"][2], faces["B"][5], faces["B"][8]]

            faces["U"][0] = f[0]
            faces["U"][3] = f[1]
            faces["U"][6] = f[2]

            faces["F"][0] = d[0]
            faces["F"][3] = d[1]
            faces["F"][6] = d[2]

            faces["D"][0] = b[2]
            faces["D"][3] = b[1]
            faces["D"][6] = b[0]

            faces["B"][2] = u[2]
            faces["B"][5] = u[1]
            faces["B"][8] = u[0]

    result = (
        "".join(faces["U"])
        + "".join(faces["R"])
        + "".join(faces["F"])
        + "".join(faces["D"])
        + "".join(faces["L"])
        + "".join(faces["B"])
    )

    return result


# ============================================================
# CUBOTINO ORIENTATION
# ============================================================

# Orientation is represented by:
#
#     top, bottom, front, back, left, right
#
# These are the physical cube faces currently occupying those
# positions.
#
# Initially:
#
#     U D F B L R
#
# A forward 90 degree flip:
#
#     top    <- back
#     front  <- top
#     bottom <- front
#     back   <- bottom
#
# This assumes the Cubotino flip direction is the conventional
# forward roll. If your physical flip direction is opposite,
# change flip_orientation() accordingly.


@dataclass
class Orientation:
    top: str = "U"
    bottom: str = "D"
    front: str = "F"
    back: str = "B"
    left: str = "L"
    right: str = "R"


def flip_orientation(o):
    """
    90 degree forward cube flip.
    """

    return Orientation(
        top=o.back,
        bottom=o.front,
        front=o.top,
        back=o.bottom,
        left=o.left,
        right=o.right,
    )


def inverse_flip_orientation(o):
    """
    90 degree backward cube flip.
    """

    return Orientation(
        top=o.front,
        bottom=o.back,
        front=o.bottom,
        back=o.top,
        left=o.left,
        right=o.right,
    )


# ============================================================
# CONVERT CUBOTINO ROTATION TO A STANDARD FACE MOVE
# ============================================================


def cubotino_rotation(orientation, direction):
    """
    Convert a physical bottom rotation into a standard cube move.

    direction:
        +1 = clockwise as viewed from the bottom
        -1 = counter-clockwise as viewed from the bottom
         2 = 180 degrees

    IMPORTANT:
    The sign convention here may need to be reversed depending
    on how your Cubotino code defines the bottom rotation.
    """

    face = orientation.bottom

    # A clockwise rotation when looking at the bottom face is
    # equivalent to a counter-clockwise standard face turn when
    # looking directly at that face.
    if direction == 1:
        suffix = "'"
    elif direction == -1:
        suffix = ""
    elif direction == 2:
        suffix = "2"
    else:
        raise ValueError(direction)

    return face + suffix


# ============================================================
# GENERATE ONE CUBOTINO SCRAMBLE
# ============================================================


def generate_candidate():
    cube = SOLVED
    orientation = Orientation()

    operations = []
    standard_moves = []

    rotations = 0
    flips = 0

    last_rotation_face = None

    while rotations < MAX_ROTATIONS:
        # Pick rotation type.
        if random.random() < P_ROTATE_180:
            direction = 2
            cost = ROTATE_180_COST
        else:
            direction = random.choice([-1, 1])
            cost = ROTATE_90_COST

        face = orientation.bottom

        # Avoid immediately cancelling the previous turn.
        if face == last_rotation_face and direction != 2:
            if standard_moves:
                continue

        move = cubotino_rotation(orientation, direction)

        cube = turn_cube(cube, move)

        operations.append(("ROTATE", direction))

        standard_moves.append(move)

        rotations += 1
        last_rotation_face = face

        # Decide whether to flip.
        if flips < MAX_FLIPS and random.random() < P_FLIP:
            orientation = flip_orientation(orientation)

            operations.append(("FLIP", 90))
            flips += 1

    return cube, operations, standard_moves


# ============================================================
# COST
# ============================================================


def calculate_cost(operations):
    cost = 0

    for operation, value in operations:
        if operation == "FLIP":
            cost += FLIP_COST

        elif operation == "ROTATE":
            if value == 2:
                cost += ROTATE_180_COST
            else:
                cost += ROTATE_90_COST

    return cost


# ============================================================
# FORMAT
# ============================================================


def format_operations(operations):
    result = []

    for operation, value in operations:
        if operation == "FLIP":
            result.append("FLIP")

        elif operation == "ROTATE":
            if value == 1:
                result.append("ROT+")
            elif value == -1:
                result.append("ROT-")
            elif value == 2:
                result.append("ROT2")

    return " ".join(result)


def count_operations(operations):
    rotations = sum(1 for x, _ in operations if x == "ROTATE")
    flips = sum(1 for x, _ in operations if x == "FLIP")

    return rotations, flips


# ============================================================
# MAIN SEARCH
# ============================================================


def main():

    results = []

    seen_states = set()

    print("Generating Cubotino scrambles...")
    print()

    for i in range(ITERATIONS):
        cube, operations, standard_moves = generate_candidate()

        # Don't evaluate duplicate states.
        if cube in seen_states:
            continue

        seen_states.add(cube)

        try:
            solution = kociemba.solve(cube)
        except Exception:
            # Should not happen if the cube implementation is valid.
            continue

        solution_moves = solution.split()
        solution_length = len(solution_moves)

        if solution_length < MIN_SOLUTION_LENGTH:
            continue

        rotations, flips = count_operations(operations)

        cost = calculate_cost(operations)

        results.append(
            {
                "cost": cost,
                "rotations": rotations,
                "flips": flips,
                "solution_length": solution_length,
                "operations": operations,
                "standard_moves": standard_moves,
                "solution": solution,
                "cube": cube,
            }
        )

        # Keep only the best candidates.
        results.sort(
            key=lambda x: (
                x["cost"],
                -x["solution_length"],
            )
        )

        results = results[:NUM_RESULTS]

        if (i + 1) % 1000 == 0:
            best = results[0] if results else None

            if best:
                print(
                    f"{i + 1:>7} candidates | "
                    f"best cost={best['cost']:.1f} | "
                    f"solution={best['solution_length']} moves"
                )

    print()
    print("=" * 80)
    print("BEST CUBOTINO SCRAMBLES")
    print("=" * 80)

    for n, result in enumerate(results, 1):
        print()
        print(f"#{n}")
        print(f"Cost:       {result['cost']:.1f}")
        print(f"Rotations:  {result['rotations']}")
        print(f"Flips:      {result['flips']}")
        print(f"Difficulty: {result['solution_length']} Kociemba moves")

        print(f"Cubotino:   {format_operations(result['operations'])}")

        print(f"Cube moves: {' '.join(result['standard_moves'])}")

        print(f"Solve:      {result['solution']}")

        print(f"State:      {result['cube']}")


if __name__ == "__main__":
    main()
