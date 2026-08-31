# Rubee - a Home Assistant + ESPHome remake of [CUBOTino](https://www.instructables.com/CUBOTino-Autonomous-Small-3D-Printed-Rubiks-Cube-R/)

<img src="docs/Images/Esp_cam/Rubee.jpeg" width="400" alt="Rubee, the robot">

Scans and solves a rubiks cube.

Main differences in this build:
- A HACS component and ESPHome split the work of cube scanning and solving
- **ESP32-S3-CAM** instead of a Raspberry Pi Zero 2 W (or Zero W) + Pi Camera. Built in LED. ([board](https://github.com/nulllaborg/esp32s3-cam), [buy](https://www.aliexpress.com/item/1005012148685931.html))
- HACS does colour detection and kociemba solving.
- ESPHome does camera control and implementing the solution
- **Top-mounted camera with light-blocking hood** - consistent scans regardless of room lighting.
- **TM1638 display, buzzer, and 8 buttons** built into the robot — live status, audio feedback, and scan/solve/abort controls at the cube itself.

user beware, a lot of the porting of this project was vibe coded.

---

## Setup

Don't expect magic out of the box — like the original, servo and colour calibration take some patience to dial in.


1. Install the software — HACS component + flash `esphome/rubiks-solver.yaml`.
2. Build the hardware — 3D-printed frame and servos per Andrea's Top version, ESP32-S3-CAM in place of the Pi.
3. Calibrate — servo positions/timings, then colour detection.

Assembly generally follows the original — I haven't documented my own variations here. I've been prety sparse with details of my build. Happy to develop detail if there's interest.

---

## Dashboard

![Rubiks dashboard](docs/Images/Esp_cam/Gui1.png)

---

## Colour calibration

Detection uses CIELAB colour distance, starting from hardcoded references and adapting automatically — after every valid 6-face scan, calibrated centroids blend into saved references via EMA (20% new, 80% history). Press **Save Calibration** to hard-commit a clean scan immediately, or **Reset Calibration** to revert to factory defaults. Full rationale in [docs/spec.md](docs/spec.md).

---

## Troubleshooting


**Centre square unclassified (`?`)**
Crop region too wide, insufficient lighting, or heavy colour cast. Check **Last Scan** and adjust the crop sliders.

**Scan Warnings > 0**
Check the **Scan Warnings** attributes for the plain-English list. A colour appearing more than 9 times usually means the wrong face was presented — **Reset Scan** and redo, following **Current Face**.

**Cube is valid: false**
Colour counts were unequal after calibration. Check **Faces Scanned** attributes for low-confidence stickers, then **Reset Scan** and redo the suspect face with better lighting or a tighter crop.

**Solver returns moves for an already-solved cube**
Handled automatically — returns "Already solved!" without calling the solver.

**Images too dark**
Increase **LED Stabilise Delay** — the LED may need longer to reach full brightness before capture.

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

# Run tests
pytest custom_components/rubiks/tests/ -v
```

See [docs/spec.md](docs/spec.md) for architecture details.
