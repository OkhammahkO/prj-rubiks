# Rubiks Cube Scanner — Home Assistant Integration

A HACS custom integration that uses an ESP32-CAM (via ESPHome) to scan the faces of a Rubik's cube and track its state in Home Assistant.

## Status

**Phase 1 — Cube State Detection** (in progress)

See [docs/features.md](docs/features.md) for full roadmap.

## How it works

1. Mount an ESP32-CAM (ESPHome) on a fixed frame pointing at the cube
2. Position a face in front of the camera and press **Scan Face**
3. The integration captures an image, detects the colour of each of the 9 squares using HSV analysis, and labels the face by its centre square colour
4. Repeat for all 6 faces — the **Cube State** sensor populates with the full 54-character state string
5. The **Last Scan** camera entity shows an annotated image after every scan so you can verify detections visually

## Requirements

- Home Assistant OS or Supervised (for add-on support in future phases)
- ESPHome camera entity, or a sample image for testing
- HACS

## Setup

### 1. Install via HACS

Add this repository as a custom HACS repository, then install **Rubiks Cube Scanner**.

### 2. Add the integration

**Settings → Devices & Services → Add Integration → Rubiks Cube Scanner**

Choose a source:
- **Camera** — select your ESPHome camera entity
- **Sample Image** — enter a full file path (e.g. `/config/custom_components/rubiks/sample_images/face.jpg`) for testing without hardware

### 3. Set crop region (optional)

After setup, four number entities appear on the device:
- **Crop Left / Top / Right / Bottom** — pixel coordinates defining the cube face boundary in the image

Set all to `0` to use the full image (useful for initial testing). Adjust once you can see the annotated overlay.

### 4. Dashboard

Add a **Camera** card pointing at the **Last Scan** entity — it updates automatically after every scan showing the detected grid, sample points, and colour labels.

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| Scan Face | Button | Triggers a face scan |
| Reset Scan | Button | Clears all scanned face data |
| Last Scan | Camera | Annotated image from the most recent scan |
| Cube State | Sensor | 54-character state string when all 6 faces scanned |
| Current Face | Sensor | Which face colours are still missing |
| Faces Scanned | Sensor | Count (0–6) with per-face colour data as attributes |
| Crop Left/Top/Right/Bottom | Number | Define the crop region in the image |

## Development setup

```bash
# Clone alongside HA core
git clone https://github.com/OkhammahkO/rubiks /workspaces/prj-rubiks

# Symlink into HA core config
ln -s /workspaces/prj-rubiks/custom_components/rubiks \
      /workspaces/core/config/custom_components/rubiks

# Install test dependencies
uv pip install -r requirements_test.txt
```

See [docs/spec.md](docs/spec.md) for architecture details.
