"""Constants for the Rubiks integration."""

DOMAIN = "rubiks"

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
# Barrel-roll rotation — tilt same direction 4 times, then two side rotations
SCAN_SEQUENCE = ["W", "B", "Y", "G", "O", "R"]

# Motion instruction for each step in the scan sequence
SCAN_MOTION = {
    "W": "Load",
    "B": "Tilt backward",
    "Y": "Tilt backward",
    "G": "Tilt backward",
    "O": "Rotate left",
    "R": "Rotate 180°",
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

# LED control entity keys
LED_BRIGHTNESS = "led_brightness"
LED_STABILISE_DELAY = "led_stabilise_delay"
LED_ENTITY_ID = "led_entity_id"

# Path for annotated output image (relative to HA www/)
ANNOTATED_IMAGE_PATH = "rubiks_last_scan.jpg"

# Device info
DEVICE_MANUFACTURER = "OkhammahkO"
DEVICE_MODEL = "Rubiks Cube Scanner"
