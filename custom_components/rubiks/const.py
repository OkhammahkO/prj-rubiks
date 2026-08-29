"""Constants for the Rubiks integration."""

import json
from pathlib import Path

DOMAIN = "rubiks"

# Read from manifest.json so there's a single source of truth for the version shown
# in each entity's device info page — bump manifest.json, nothing else.
INTEGRATION_VERSION = json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]

# Config entry keys
CONF_SOURCE = "source"
CONF_CAMERA_ENTITY = "camera_entity"
CONF_SAMPLE_IMAGE = "sample_image"

# Source types
SOURCE_CAMERA = "camera"
SOURCE_SAMPLE = "sample"

# Rubik's cube colors keyed by centre square color code
CUBE_COLORS = {
    "W": "white",
    "Y": "yellow",
    "R": "red",
    "O": "orange",
    "B": "blue",
    "G": "green",
}

# Scan order: Top, Back, Bottom, Front, Left, Right
# Barrel-roll rotation — tilt same direction 4 times, then two side rotations.
# Robot matches: spinCW+flip presents Red (pos 4); flip×2 presents Orange (pos 5).
# R/O at positions 4/5 were flip-flopped twice on 2026-07-26 based on verbal "hardware
# confirmed" reads that turned out to contradict each other — Red/Orange is a documented
# confusion pair on this camera (see REFERENCE_LAB comment in camera_processor.py). This
# value is instead derived mathematically from the Loading Position and Flip/Spin
# definitions in docs/orientation.md — see the derivation and sanity checks in the
# SCAN_FACES comment in esphome/components/rubiks_solver/rubiks_solver.cpp, which this
# must stay in sync with (along with docs/orientation.md).
SCAN_SEQUENCE = ["W", "B", "Y", "G", "R", "O"]

# Motion instruction for each step in the scan sequence
SCAN_MOTION = {
    "W": "Load",
    "B": "Tilt backward",
    "Y": "Tilt backward",
    "G": "Tilt backward",
    "R": "Rotate left",
    "O": "Rotate 180°",
}

# Loading position reminder shown for the first face
SCAN_LOADING_HINT = "White facing camera, Blue at top, Orange on left"

# Emoji squares for each colour — used in sensor attributes
COLOUR_EMOJI = {
    "W": "⬜",
    "Y": "🟨",
    "R": "🟥",
    "O": "🟧",
    "B": "🟦",
    "G": "🟩",
    "?": "⬛",
}

# Crop region number entity keys
CROP_LEFT = "crop_left"
CROP_TOP = "crop_top"
CROP_RIGHT = "crop_right"
CROP_BOTTOM = "crop_bottom"
CROP_ROTATION = "crop_rotation"

# LED control entity keys
LED_BRIGHTNESS = "led_brightness"
LED_STABILISE_DELAY = "led_stabilise_delay"
LED_ENTITY_ID = "led_entity_id"

# Scramble number entity key
SCRAMBLE_MOVE_COUNT = "scramble_move_count"

# Faces/modifiers for scramble generation — plain random moves (not WCA random-state).
# 26 is the researched minimum for a random-move sequence to be well-mixed (see
# docs/features.md "Scrambler"); default sits right at that threshold.
SCRAMBLE_FACES = ["U", "D", "L", "R", "F", "B"]
SCRAMBLE_MODIFIERS = ["1", "2", "3"]
SCRAMBLE_MOVE_COUNT_DEFAULT = 26
SCRAMBLE_MOVE_COUNT_MIN = 15
SCRAMBLE_MOVE_COUNT_MAX = 50

# Path for annotated output image (relative to HA www/)
ANNOTATED_IMAGE_PATH = "rubiks_last_scan.jpg"

# Device info
DEVICE_MANUFACTURER = "OkhammahkO"
DEVICE_MODEL = "Rubiks Cube Scanner"
