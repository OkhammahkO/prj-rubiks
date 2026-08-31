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

User beware, most of the porting of this project and additional development and docs was vibe coded.

---

## Dashboard

![Rubiks dashboard](docs/Images/Esp_cam/Gui1.png)

---

## Setup

Don't expect magic out of the box — like the original, servo and colour calibration take some patience to dial in.


1. Install the software — HACS component + flash `esphome/rubiks-solver.yaml`.
2. Build the hardware — 3D-printed frame and servos per Andrea's Top version, ESP32-S3-CAM in place of the Pi.
3. Calibrate — servo positions/timings, then colour detection.

Assembly generally follows the original — I haven't documented my own variations here. I've been pretty sparse with details of my build and the set-up. Happy to develop detail if there's interest.

TODO:
 - Add hood 3d print
 - Review set up properly for HACs / ESPHome external componets

---

## Docs

- [Architecture / integration spec](docs/spec.md)
- [Robot hardware + ESPHome component](docs/robot.md)
- [Servo tuning reference](docs/servo-tuning.md)
- [Camera/cube orientation model](docs/orientation.md)
- [Collision prevention](docs/collision-prevention.md)
- [TM1638 display/buzzer/buttons](docs/tm1638.md)
- [Feature/entity inventory](docs/features.md)

---

## License

[MIT](LICENSE) for this project's software. The physical CUBOTino design/mechanism is Andrea Favero's — see [his Instructables page](https://www.instructables.com/CUBOTino-Autonomous-Small-3D-Printed-Rubiks-Cube-R/) for terms on the design itself.