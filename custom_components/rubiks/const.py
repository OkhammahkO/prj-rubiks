"""Constants for the Rubiks integration."""

DOMAIN = "rubiks"

# Config entry keys
CONF_SOURCE = "source"
CONF_CAMERA_ENTITY = "camera_entity"
CONF_SAMPLE_IMAGE = "sample_image"

# Source types
SOURCE_CAMERA = "camera"
SOURCE_SAMPLE = "sample"

# Face names (standard Rubik's cube notation)
FACES = ["U", "R", "F", "D", "L", "B"]  # Up, Right, Front, Down, Left, Back
FACE_NAMES = {
    "U": "Up",
    "R": "Right",
    "F": "Front",
    "D": "Down",
    "L": "Left",
    "B": "Back",
}

# Rubik's cube colors (HSV hue ranges, saturation/value thresholds)
# Colors: White, Yellow, Red, Orange, Blue, Green
CUBE_COLORS = {
    "W": "white",
    "Y": "yellow",
    "R": "red",
    "O": "orange",
    "B": "blue",
    "G": "green",
}

# Number of squares per face
SQUARES_PER_FACE = 9
GRID_SIZE = 3

# Crop region number entity keys
CROP_LEFT = "crop_left"
CROP_TOP = "crop_top"
CROP_RIGHT = "crop_right"
CROP_BOTTOM = "crop_bottom"

# Path for annotated output image (relative to HA www/)
ANNOTATED_IMAGE_PATH = "rubiks_last_scan.jpg"
