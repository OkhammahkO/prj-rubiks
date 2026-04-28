# Rubiks Cube Scanner — Home Assistant Integration

A HACS custom integration that uses a fixed ESP32-CAM (via ESPHome) to scan all 6 faces of a Rubik's cube, solve it, and display the move sequence.

## How it works

1. Mount an ESP32-CAM (OV2640, via ESPHome) on a fixed frame pointing at the cube
2. Set the crop region using the slider entities so the face fills the grid
3. Present each face to the camera in sequence and press **Scan Face**
4. The integration captures an image, classifies each of the 9 squares using CIELAB colour distance, and stores the face by its centre square colour
5. After all 6 faces are scanned, per-session calibration refines the classification using actual camera readings, then validates colour counts
6. Press **Solve** — the **Solution** sensor shows the move sequence to solve the cube

The **Current Face** sensor tells you which face to present next. The annotated image entities let you verify each scan visually.

---

## Scan sequence

Present faces to the camera in this order — a simple barrel-roll rotation:

| Step | Face | Motion from previous |
|------|------|----------------------|
| 1 | **White** | — start here (White facing camera, Blue at top, Orange on left) |
| 2 | **Blue** | Tilt cube backward 90° |
| 3 | **Yellow** | Tilt backward 90° again |
| 4 | **Green** | Tilt backward 90° again |
| 5 | **Orange** | Rotate 90° left |
| 6 | **Red** | Rotate 180° |

The **Current Face** sensor tracks your position in this sequence.

---

## Hardware

- ESP32-CAM with OV2640 sensor, running ESPHome
- LED illumination strongly recommended — consistent lighting is the single biggest factor in reliable detection
- A fixed mount so the cube position is repeatable

### Recommended ESPHome camera settings

```yaml
camera:
  - platform: esp32_cam
    name: Rubiks Camera
    aec_mode: manual
    aec_value: 300
    agc_mode: manual
    agc_value: 0
    wb_mode: home
```

Set LED brightness using the **LED Brightness** slider entity, and point the LED entity ID at your ESPHome light entity using **LED Entity ID**.

---

## Setup

### 1. Install via HACS

Add this repository as a custom HACS repository, then install **Rubiks Cube Scanner**.

### 2. Add the integration

**Settings → Devices & Services → Add Integration → Rubiks Cube Scanner**

Choose a source:
- **Camera** — select your ESPHome camera entity
- **Sample Image** — enter a full file path for testing without hardware

### 3. Configure crop region

Use the **Crop Left / Top / Right / Bottom** sliders to define the face boundary in the image. Press **Preview Crop** to see the annotated overlay without recording a scan. The preview also fires automatically on startup.

### 4. Configure LED (optional)

Set **LED Entity ID** to your ESPHome light entity (e.g. `light.rubiks_led`) and **LED Brightness** to 0–255. The integration turns the LED on at that brightness before every scan and preview.

Set **LED Stabilise Delay** to the number of seconds to wait after the LED turns on before capturing — default 0.3s. Increase this if images come out dark or if your LED takes time to reach full brightness.

### 5. Scan and solve

Press **Reset Scan** to start fresh, follow the **Current Face** sensor through the 6-position sequence, then press **Solve**.

---

## Entities

### Buttons

| Entity | Description |
|--------|-------------|
| Scan Face | Capture and classify the current face |
| Preview Crop | Capture and annotate without storing a scan |
| Reset Scan | Clear all scanned face data |
| Save Calibration | Hard-commit this session's calibrated colour references to storage |
| Reset Calibration | Wipe saved references and revert to factory defaults |
| Solve | Run the solver on the current cube state |

### Sensors

| Entity | State | Key attributes |
|--------|-------|----------------|
| Current Face | Next face to scan (e.g. `Blue · Tilt backward (1 of 6 done)`) | `next_colour`, `motion`, `remaining` |
| Faces Scanned | Count 0–6 | Per-face square detail (colour + LAB values) + emoji grid per face |
| Cube State | 54-char colour string (when complete) | `faces scanned`, `cube is valid`, `corrections applied`, `uncertain stickers`, `colour references`, emoji cube net |
| Scan Warnings | Count of active warnings (0 = all clear) | `status` 🟢/🔴, `warnings` list |
| Kociemba Input | 54-char solver input string | `parity_valid`, `ready_to_solve` |
| Solution | Move sequence (e.g. `R U R' U'`) | `move_count`, `cube_string` |

### Images

| Entity | Description |
|--------|-------------|
| Last Scan | Annotated image from the most recent scan or preview |
| Face White/Yellow/Red/Orange/Blue/Green | Persists the annotated scan for each face |
| Scan Summary | 3×2 grid of all 6 face scans, generated after calibration |

### Numbers

| Entity | Range | Description |
|--------|-------|-------------|
| Crop Left / Top / Right / Bottom | 0 – image width/height | Face crop region |
| LED Brightness | 0–255 | Brightness to set LED before each scan |
| LED Stabilise Delay | 0–2 s (step 0.05) | Seconds to wait after LED turns on before capturing |

### Text

| Entity | Description |
|--------|-------------|
| LED Entity ID | HA entity ID of the light to illuminate before scanning (e.g. `light.rubiks_led`) |

---

## Colour calibration

Detection uses CIELAB colour space with weighted Euclidean distance. Classification starts from hardcoded reference centroids measured on an OV2640 camera, then improves automatically over time.

**Adaptive calibration (automatic):** After every 6-face scan where all colour counts are valid, the session's calibrated centroids are blended into saved references using an exponential moving average (20% new, 80% historical). This adapts gradually to your specific camera and lighting without being thrown off by a single bad session.

**Manual save:** Press **Save Calibration** after a clean 6-face scan to hard-commit those centroids immediately, bypassing the EMA. Use this when you've just got a perfect result and want to lock it in.

**Factory reset:** Press **Reset Calibration** to wipe saved references and revert to hardcoded defaults.

Saved references persist across HA restarts in `.storage/rubiks_cal_<entry_id>`.

---

## Troubleshooting

**Centre square unclassified (`?`)**  
Crop region too wide (background pixels included), insufficient lighting, or heavy colour cast. Check the **Last Scan** image and adjust the crop sliders.

**Scan Warnings > 0**  
Open the **Scan Warnings** sensor attributes for the plain-English list. A colour appearing more than 9 times usually means you presented the wrong face — press **Reset Scan** and start over, being careful to follow the **Current Face** sensor.

**Cube is valid: false**  
After calibration, colour counts were unequal. Check the **Faces Scanned** sensor attributes for low-confidence stickers to identify which face is the problem, then press **Reset Scan** and redo all 6 faces with better lighting or a tighter crop on the suspect face.

**Solver returns moves for an already-solved cube**  
This is handled automatically — the integration detects a solved state and returns "Already solved!" without calling the solver.

**Images too dark**  
Increase **LED Stabilise Delay** — your LED may need longer to reach full brightness before the camera captures.

---

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
