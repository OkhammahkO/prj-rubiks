# Rubiks Cube Scanner — Technical Specification

## System Overview

```
ESP32-CAM (ESPHome) ──► HA Integration ──► Kociemba Solver ──► ESP32 Robot (ESPHome)
     camera entity          cube state          move sequence        motor control
```

The integration sits in the middle — it owns image capture, colour detection, and cube state. The solver and robot are Phase 2/3 concerns.

---

## Architecture Decisions

### Custom integration, not an add-on
Image processing for a single manually-triggered snapshot is lightweight enough to run in the HA event loop (offloaded to executor via `async_add_executor_job`). An add-on would add deployment complexity and require HA OS, for no meaningful benefit at this scale.

### Colour detection: HSV sampling, not Color Thief
Color Thief extracts dominant palette colours — it is designed for web images, not precision colour mapping. HSV (Hue-Saturation-Value) colour space is standard for Rubik's cube scanners because hue is largely independent of lighting intensity, making it more robust to real-world conditions than raw RGB distance.

### Face identification: centre square colour
On a standard Rubik's cube, the centre square of each face is fixed and always represents that face's colour. Using it as the face identifier means:
- Faces can be scanned in any order
- No UI prompt needed to tell the user which face to present next
- Duplicate face detection is automatic
- A bad centre scan (returns `?`) is a reliable early-rejection signal

### Crop region: number entities (runtime sliders)
Crop coordinates are exposed as four `number` entities on the device rather than being set in the config flow. This lets the user tune the crop region live using dashboard sliders and see the annotated overlay update immediately — a much tighter feedback loop than editing config and reloading.

### Visual validation: built-in camera entity
Rather than requiring a `local_file` camera entry in `configuration.yaml`, the integration registers its own `Camera` entity that serves annotated image bytes directly from memory. The annotated image is also written to `www/rubiks_last_scan.jpg` as a fallback for direct URL access.

---

## Data Model

### Cube state string
The full cube state is a 54-character string, 9 characters per face, ordered by centre colour: `W Y R O B G`.

Each character is one of: `W` (white) `Y` (yellow) `R` (red) `O` (orange) `B` (blue) `G` (green) `?` (unclassified).

Example: `WWWWWWWWWYYYYYYYYYRRRRRRRRROOOOOOOOOBBBBBBBBBGGGGGGGGG` (solved cube)

This format is compatible with the `kociemba` Python solver (Phase 2), using colour codes instead of face-position codes.

### Scanned faces store
Stored in `hass.data[DOMAIN][entry_id]["scanned_faces"]` as:
```python
{
  "W": ["W", "R", "G", "W", "W", "B", "Y", "W", "O"],  # 9 colours, keyed by centre colour
  "B": [...],
  ...
}
```

---

## Colour Detection Pipeline

```
Image bytes / file path
    │
    ▼
PIL Image (load_image_from_bytes / load_image_from_path)
    │
    ▼
Crop to face region  (optional, defined by number entities)
    │
    ▼
Divide into 3×3 grid
    │
    ▼
For each cell:
  - Find centre pixel (cx, cy)
  - Average a small sample area (noise reduction)
  - Convert RGB → HSV
  - Match against CUBE_COLOR_MAP thresholds
  - Return colour code or "?"
    │
    ▼
FaceScan(face_label, colors, annotated_image)
    │
    ├─► face_label = colors[4]  (centre square)
    ├─► Reject if face_label == "?"
    ├─► Warn if any color == "?"
    └─► Fire {DOMAIN}_face_scanned event
```

### HSV thresholds

| Code | Colour | Hue range | Sat min | Val min |
|------|--------|-----------|---------|---------|
| W | White | any | < 0.25 | > 0.70 |
| R | Red | 340–360° | 0.4 | 0.3 |
| R | Red | 0–15° | 0.4 | 0.3 |
| O | Orange | 15–40° | 0.4 | 0.3 |
| Y | Yellow | 40–75° | 0.4 | 0.3 |
| G | Green | 75–165° | 0.4 | 0.3 |
| B | Blue | 165–260° | 0.4 | 0.3 |

These are initial values and will need calibration against real hardware.

---

## Annotated Image Overlay

Drawn onto the source image (full frame) using Pillow `ImageDraw`:

| Element | Description |
|---------|-------------|
| Yellow rectangle | Face crop boundary |
| Yellow lines | 3×3 grid dividers |
| Coloured circle | Sample point location for each cell |
| Coloured text | Detected colour code next to each sample point |

Output saved to:
- `hass.data` (in memory, served by `LastScanCamera` entity)
- `config/www/rubiks_last_scan.jpg` (static file, accessible at `/local/rubiks_last_scan.jpg`)

---

## File Structure

```
custom_components/rubiks/
├── __init__.py           — integration setup, hass.data initialisation
├── manifest.json         — domain, requirements (Pillow)
├── const.py              — DOMAIN, colour codes, crop keys, face list
├── config_flow.py        — source selection (camera entity or sample image path)
├── camera_processor.py   — HSV colour detection, annotated image generation
├── button.py             — Scan Face, Reset Scan
├── camera.py             — Last Scan camera entity (serves annotated image)
├── number.py             — Crop Left/Top/Right/Bottom
├── sensor.py             — Cube State, Current Face, Faces Scanned
├── strings.json          — UI strings
├── translations/
│   └── en.json
├── tests/
│   └── __init__.py
└── sample_images/        — test images (tracked in git)
```
