"""Button entities for Rubiks Cube Scanner."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.components.camera import async_get_image
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .camera_processor import (
    REFERENCE_LAB,
    CropBox,
    calibrate_faces,
    check_running_validity,
    detect_face_colors,
    generate_summary_image,
    lab_distance,
    load_image_from_bytes,
    load_image_from_path,
)
from .const import (
    ANNOTATED_IMAGE_PATH,
    CONF_CAMERA_ENTITY,
    CONF_SAMPLE_IMAGE,
    CONF_SOURCE,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    INTEGRATION_VERSION,
    SCAN_SEQUENCE,
    SCRAMBLE_FACES,
    SCRAMBLE_MODIFIERS,
    SCRAMBLE_MOVE_COUNT_DEFAULT,
    SOURCE_CAMERA,
)
from .solver import (
    ROBOT_CAMERA_TO_KOCIEMBA_REMAP,
    build_kociemba_faces,
    diagnose_cube_string,
    kociemba_string,
    solve,
)

if TYPE_CHECKING:
    from homeassistant.core import ServiceCall
    from PIL.Image import Image

_LOGGER = logging.getLogger(__name__)

SCAN_BUTTON = ButtonEntityDescription(key="scan_face", translation_key="scan_face", icon="mdi:camera-iris")
ROBOT_START_BUTTON = ButtonEntityDescription(key="robot_start_scan", translation_key="robot_start_scan", icon="mdi:cube-scan")
ROBOT_STOP_BUTTON = ButtonEntityDescription(key="robot_stop", translation_key="robot_stop", icon="mdi:stop-circle-outline")
ROBOT_ABORT_BUTTON = ButtonEntityDescription(key="robot_abort", translation_key="robot_abort", icon="mdi:alert-octagon-outline")
ROBOT_ADVANCE_BUTTON = ButtonEntityDescription(key="robot_advance_face", translation_key="robot_advance_face", icon="mdi:arrow-right-circle-outline")
PREVIEW_BUTTON = ButtonEntityDescription(key="preview_crop", translation_key="preview_crop", icon="mdi:eye-outline")
RESET_BUTTON = ButtonEntityDescription(key="reset_scan", translation_key="reset_scan", icon="mdi:restart")
SAVE_CAL_BUTTON = ButtonEntityDescription(
    key="save_calibration", translation_key="save_calibration", icon="mdi:content-save-outline"
)
RESET_CAL_BUTTON = ButtonEntityDescription(
    key="reset_calibration", translation_key="reset_calibration", icon="mdi:backup-restore"
)
SOLVE_BUTTON = ButtonEntityDescription(key="solve", translation_key="solve", icon="mdi:lightbulb-on-outline")
SCRAMBLE_BUTTON = ButtonEntityDescription(key="scramble", translation_key="scramble", icon="mdi:dice-multiple-outline")

_LAB_WARN_THRESHOLD = 20.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Rubiks button entities."""
    async_add_entities([
        ScanFaceButton(hass, entry),
        PreviewCropButton(hass, entry),
        ResetScanButton(hass, entry),
        SaveCalibrationButton(hass, entry),
        ResetCalibrationButton(hass, entry),
        SolveButton(hass, entry),
        RobotStartScanButton(hass, entry),
        RobotStopButton(hass, entry),
        RobotAbortButton(hass, entry),
        RobotAdvanceFaceButton(hass, entry),
        ScrambleButton(hass, entry),
    ])


# ── Module-level helpers (shared by button entities and service handler) ──────

def generate_scramble(move_count: int) -> str:
    """Generate a random scramble string, e.g. "U1 R2 F3 D1 ...".

    Plain random-move scrambling, not WCA's random-state method — picks a random face
    each step (never the same face twice in a row, to avoid the most obviously
    redundant/cancelling sequences) and a random modifier (1=CW, 2=180°, 3=CCW). Digit
    form matches what execute_solution()'s normalize_solution() already accepts
    directly, same notation the D1/U1/etc test buttons use.

    move_count should be at least ~26 for the sequence to be reasonably well-mixed —
    below that, research shows random-move scrambles tend to leave recognisable
    partially-solved patterns. See docs/features.md "Scrambler".
    """
    moves: list[str] = []
    last_face: str | None = None
    for _ in range(move_count):
        face = random.choice([f for f in SCRAMBLE_FACES if f != last_face])
        moves.append(face + random.choice(SCRAMBLE_MODIFIERS))
        last_face = face
    return " ".join(moves)


async def _async_illuminate(hass: HomeAssistant, data: dict) -> None:
    """Turn on configured LED at configured brightness and wait for stabilisation.

    Skips both the service call and the stabilisation delay if the light is already
    on — avoids re-paying the delay for every face in a scan when it was already
    turned on (and given time to stabilise) for the previous one.
    """
    entity_id = data.get("led_entity_id")
    led_br_entity = data.get("led_brightness_entity")
    if not entity_id or led_br_entity is None:
        return
    state = hass.states.get(entity_id)
    if state is not None and state.state == "on":
        return
    brightness = led_br_entity.brightness
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": entity_id, "brightness": brightness},
        blocking=True,
    )
    delay_entity = data.get("led_stabilise_delay_entity")
    await asyncio.sleep(delay_entity.delay if delay_entity else 0.3)


def _get_rotation(data: dict) -> float:
    """Read current grid rotation angle (degrees) from the crop_rotation number entity."""
    entity = data.get("crop_entities", {}).get("crop_rotation")
    return float(entity.native_value or 0.0) if entity is not None else 0.0


def _get_crop_box(data: dict) -> CropBox | None:
    """Read current crop coordinates from number entities."""
    entities = data.get("crop_entities", {})
    try:
        left = int(entities["crop_left"].native_value)
        top = int(entities["crop_top"].native_value)
        right = int(entities["crop_right"].native_value)
        bottom = int(entities["crop_bottom"].native_value)
    except (KeyError, TypeError):
        return None
    if right > left and bottom > top:
        return (left, top, right, bottom)
    return None


def _update_crop_max(data: dict, width: int, height: int) -> None:
    """Set crop slider maximums to match actual image dimensions."""
    entities = data.get("crop_entities", {})
    for key in ("crop_left", "crop_right"):
        if entity := entities.get(key):
            entity.update_max(width)
    for key in ("crop_top", "crop_bottom"):
        if entity := entities.get(key):
            entity.update_max(height)


async def _async_save_annotated(hass: HomeAssistant, data: dict, image_bytes: bytes) -> None:
    """Store annotated image in shared data and www/."""
    data["last_annotated_image"] = image_bytes
    www_path = hass.config.path("www")
    os.makedirs(www_path, exist_ok=True)
    out_path = os.path.join(www_path, ANNOTATED_IMAGE_PATH)
    await hass.async_add_executor_job(_write_file, out_path, image_bytes)


async def _async_get_camera_snapshot(hass: HomeAssistant, entity_id: str) -> bytes:
    """Request a snapshot from a HA camera entity."""
    t0 = time.monotonic()
    camera_image = await async_get_image(hass, entity_id)
    _LOGGER.info(
        "Camera snapshot took %.2fs, size: %d bytes",
        time.monotonic() - t0,
        len(camera_image.content),
    )
    return camera_image.content


async def _async_load_image(
    hass: HomeAssistant, entry: ConfigEntry, data: dict
) -> Image:
    """Illuminate and load image from the configured source."""
    await _async_illuminate(hass, data)
    source = entry.data[CONF_SOURCE]
    if source == SOURCE_CAMERA:
        camera_entity_id = (
            entry.options.get(CONF_CAMERA_ENTITY)
            or entry.data[CONF_CAMERA_ENTITY]
        )
        # Discard first snapshot — camera idles at 0.1 fps so the buffer may
        # hold a stale frame from before the LED came on or the cube settled.
        await _async_get_camera_snapshot(hass, camera_entity_id)
        await asyncio.sleep(0.4)
        image_bytes = await _async_get_camera_snapshot(hass, camera_entity_id)
        image = await hass.async_add_executor_job(load_image_from_bytes, image_bytes)
    else:
        path = (
            entry.options.get(CONF_SAMPLE_IMAGE)
            or entry.data[CONF_SAMPLE_IMAGE]
        )
        image = await hass.async_add_executor_job(load_image_from_path, path)
    w, h = image.size
    data["image_size"] = (w, h)
    _update_crop_max(data, w, h)
    return image


async def _async_run_calibration(
    hass: HomeAssistant,
    entry: ConfigEntry,
    data: dict,
    remap: dict[str, list[int]] | None = None,
) -> None:
    """Calibrate all 6 scanned faces, build kociemba string, fire calibrated event.

    Pass ``remap=ROBOT_CAMERA_TO_KOCIEMBA_REMAP`` for robot top-down scans;
    defaults to Phase 1/2 CAMERA_TO_KOCIEMBA_REMAP.
    """
    scanned = data["scanned_faces"]
    cal_store = data.get("cal_store")

    result = await hass.async_add_executor_job(calibrate_faces, data["face_scans"])
    data["calibration_result"] = result
    for lbl, colours in result.calibrated_faces.items():
        scanned[lbl] = colours
    data["summary_image"] = await hass.async_add_executor_job(
        generate_summary_image, data["face_annotated_images"]
    )
    if result.parity_valid and cal_store:
        await cal_store.ema_update(result.anchors)

    centre_warnings = [
        f"{face} face centre is '{scanned[face][4]}' after calibration "
        f"(expected {face}) — Red/Orange confusion?"
        for face in scanned
        if scanned[face][4] != face
    ]
    for w in centre_warnings:
        _LOGGER.warning("Centre mismatch: %s", w)
    data["scan_warnings"] = list(data.get("scan_warnings") or []) + centre_warnings

    kociemba_faces = build_kociemba_faces(scanned, remap=remap)
    data["kociemba_faces"] = kociemba_faces
    cube_str = kociemba_string(kociemba_faces) if kociemba_faces else None

    if cube_str:
        cube_issues = diagnose_cube_string(cube_str)
        if cube_issues:
            _LOGGER.warning(
                "Cube state has %d structural issue%s after calibration:\n  %s",
                len(cube_issues),
                "s" if len(cube_issues) != 1 else "",
                "\n  ".join(cube_issues),
            )
            data["scan_warnings"] = list(data.get("scan_warnings") or []) + [
                f"Cube structural issue: {issue}" for issue in cube_issues
            ]

    hass.bus.async_fire(
        f"{DOMAIN}_calibrated",
        {
            "parity_valid": result.parity_valid,
            "corrections": len(result.pre_calibration_changes),
            "low_confidence": len(result.low_confidence),
            "anchors_saved": result.parity_valid,
            "kociemba_string": cube_str,
        },
    )


async def async_handle_robot_scan_face(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    """Handle the rubiks.robot_scan_face service call.

    Expects {face: "W"} from the esphome.rubiks_face_ready event payload.
    Runs illuminate → capture → detect → store pipeline, then fires
    rubiks_face_scanned. After all 6 faces, runs calibration with
    ROBOT_CAMERA_TO_KOCIEMBA_REMAP (top-down camera orientation).
    """
    face = call.data["face"]

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        _LOGGER.error("robot_scan_face: no rubiks integration configured")
        return
    entry = entries[0]
    data = hass.data[DOMAIN].get(entry.entry_id)
    if data is None:
        _LOGGER.error("robot_scan_face: integration not loaded")
        return

    scanned: dict = data["scanned_faces"]
    if face in scanned:
        _LOGGER.warning("robot_scan_face: face %s already scanned — call reset first", face)
        return

    try:
        image = await _async_load_image(hass, entry, data)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("robot_scan_face: failed to load image for face %s", face)
        return

    cal_store = data.get("cal_store")
    refs = cal_store.get_references() if cal_store else None
    scan = await hass.async_add_executor_job(
        detect_face_colors, image, _get_crop_box(data), refs, face, _get_rotation(data),
    )

    if len(scan.lab_readings) >= 5:
        centre_lab = scan.lab_readings[4]
        expected_ref = (refs or REFERENCE_LAB)[face]
        dist = lab_distance(centre_lab, expected_ref)
        if dist > _LAB_WARN_THRESHOLD:
            _LOGGER.warning(
                "robot_scan_face: face %s centre LAB(%.1f,%.1f,%.1f) is %.1f units "
                "from expected reference — verify robot arm position.",
                face, *centre_lab, dist,
            )

    if scan.has_unknowns:
        _LOGGER.warning(
            "robot_scan_face: face %s has unknown squares: %s", face, scan.colors
        )

    scanned[face] = scan.colors
    data["face_scans"][face] = scan
    data["face_annotated_images"][face] = scan.annotated_image
    _LOGGER.info("robot_scan_face: stored face %s: %s", face, scan.colors)

    warnings = check_running_validity(scanned)
    data["scan_warnings"] = warnings
    for w in warnings:
        _LOGGER.warning("robot_scan_face: %s", w)

    await _async_save_annotated(hass, data, scan.annotated_image)
    hass.bus.async_fire(
        f"{DOMAIN}_face_scanned",
        {"face": face, "colors": scan.colors, "warnings": warnings},
    )

    if len(scanned) == 6:
        await _async_run_calibration(
            hass, entry, data, remap=ROBOT_CAMERA_TO_KOCIEMBA_REMAP
        )


# ── Base entity class ─────────────────────────────────────────────────────────

class RubiksButtonBase(ButtonEntity):
    """Base class with shared image loading and annotated image saving."""

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        self.hass = hass
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_MODEL,
            manufacturer=DEVICE_MANUFACTURER,
            sw_version=INTEGRATION_VERSION,
        )

    async def async_press(self) -> None:  # type: ignore[override]
        """Override in subclasses."""

    def _data(self) -> dict:
        return self.hass.data[DOMAIN][self._entry.entry_id]

    async def _illuminate(self) -> None:
        await _async_illuminate(self.hass, self._data())

    def _get_crop_box(self) -> CropBox | None:
        return _get_crop_box(self._data())

    async def _save_annotated(self, image_bytes: bytes) -> None:
        await _async_save_annotated(self.hass, self._data(), image_bytes)

    def _update_crop_max(self, width: int, height: int) -> None:
        _update_crop_max(self._data(), width, height)

    async def _load_image(self) -> Image:
        return await _async_load_image(self.hass, self._entry, self._data())

    async def _get_camera_snapshot(self, entity_id: str) -> bytes:
        return await _async_get_camera_snapshot(self.hass, entity_id)


# ── Button entities ───────────────────────────────────────────────────────────

class ScanFaceButton(RubiksButtonBase):
    """Button to trigger scanning of the current cube face."""

    entity_description = SCAN_BUTTON

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_scan_face"

    async def async_press(self) -> None:  # type: ignore[override]
        """Scan the next face in sequence and store the result."""
        data = self._data()
        scanned: dict = data["scanned_faces"]

        if len(scanned) >= 6:
            _LOGGER.warning("All 6 faces already scanned. Reset before scanning again.")
            return

        face_label = SCAN_SEQUENCE[len(scanned)]

        try:
            image = await self._load_image()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to load image for face scan")
            return

        cal_store = data.get("cal_store")
        refs = cal_store.get_references() if cal_store else None
        scan = await self.hass.async_add_executor_job(
            detect_face_colors, image, self._get_crop_box(), refs, face_label,
            _get_rotation(data),
        )

        if len(scan.lab_readings) >= 5:
            centre_lab = scan.lab_readings[4]
            expected_ref = (refs or REFERENCE_LAB)[face_label]
            dist = lab_distance(centre_lab, expected_ref)
            if dist > _LAB_WARN_THRESHOLD:
                _LOGGER.warning(
                    "Face %s: centre LAB(%.1f, %.1f, %.1f) is %.1f units from expected "
                    "reference — verify cube orientation.",
                    face_label, *centre_lab, dist,
                )

        if scan.has_unknowns:
            _LOGGER.warning(
                "Face %s scanned with unknown squares: %s", face_label, scan.colors
            )

        scanned[face_label] = scan.colors
        data["face_scans"][face_label] = scan
        data["face_annotated_images"][face_label] = scan.annotated_image
        _LOGGER.info("Scanned face %s: %s", face_label, scan.colors)

        warnings = check_running_validity(scanned)
        data["scan_warnings"] = warnings
        for w in warnings:
            _LOGGER.warning("Scan validity: %s", w)

        await self._save_annotated(scan.annotated_image)
        self.hass.bus.async_fire(
            f"{DOMAIN}_face_scanned",
            {"face": face_label, "colors": scan.colors, "warnings": warnings},
        )

        if len(scanned) == 6:
            await _async_run_calibration(self.hass, self._entry, data)


class PreviewCropButton(RubiksButtonBase):
    """Button to preview crop region and grid overlay without storing a scan result."""

    entity_description = PREVIEW_BUTTON

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_preview_crop"

    async def async_added_to_hass(self) -> None:
        """Trigger a preview once HA has fully started."""
        await super().async_added_to_hass()

        async def _do_preview(_event: Event | None = None) -> None:
            await asyncio.sleep(5)
            await self.async_press()

        if self.hass.is_running:
            self.hass.async_create_task(_do_preview())
        else:
            self.async_on_remove(
                self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _do_preview)
            )

    async def async_press(self) -> None:  # type: ignore[override]
        """Capture image, annotate with current crop + grid, update Last Scan image."""
        try:
            image = await self._load_image()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to load image for preview")
            return

        data = self._data()
        cal_store = data.get("cal_store")
        refs = cal_store.get_references() if cal_store else None
        scan = await self.hass.async_add_executor_job(
            detect_face_colors, image, self._get_crop_box(), refs, None,
            _get_rotation(self._data()),
        )
        await self._save_annotated(scan.annotated_image)
        self.hass.bus.async_fire(f"{DOMAIN}_scan_rejected", {})
        _LOGGER.info("Preview updated — crop: %s", self._get_crop_box())


class ResetScanButton(RubiksButtonBase):
    """Button to clear all scanned faces and start over."""

    entity_description = RESET_BUTTON

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_reset_scan"

    async def async_press(self) -> None:  # type: ignore[override]
        """Clear all scanned face data."""
        data = self._data()
        data["scanned_faces"] = {}
        data["face_scans"] = {}
        data["face_annotated_images"] = {}
        data["calibration_result"] = None
        data["summary_image"] = None
        data["scan_warnings"] = []
        data["kociemba_faces"] = None
        self.hass.bus.async_fire(f"{DOMAIN}_scan_reset", {})
        _LOGGER.info("Cube scan reset.")


class SaveCalibrationButton(RubiksButtonBase):
    """Hard-commit the current session's calibrated anchors, overriding EMA history."""

    entity_description = SAVE_CAL_BUTTON
    _attr_available = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_save_calibration"

    async def async_added_to_hass(self) -> None:
        """Subscribe to calibration events to control availability."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_calibrated", self._on_calibrated)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_scan_reset", self._on_reset)
        )

    @callback
    def _on_calibrated(self, _event: Event) -> None:
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _on_reset(self, _event: Event) -> None:
        self._attr_available = False
        self.async_write_ha_state()

    async def async_press(self) -> None:  # type: ignore[override]
        """Commit calibrated anchors from the current session to persistent storage."""
        data = self._data()
        result = data.get("calibration_result")
        cal_store = data.get("cal_store")
        if result is None:
            _LOGGER.warning("Save Calibration pressed but no calibration result available.")
            return
        if cal_store is None:
            return
        await cal_store.hard_commit(result.anchors)
        self.hass.bus.async_fire(f"{DOMAIN}_calibration_saved", {"anchors": result.anchors})
        _LOGGER.info("Calibration manually saved.")


class ResetCalibrationButton(RubiksButtonBase):
    """Clear saved LAB anchors and revert to factory defaults."""

    entity_description = RESET_CAL_BUTTON

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_reset_calibration"

    async def async_press(self) -> None:  # type: ignore[override]
        """Wipe saved LAB anchors — next scans use hardcoded REFERENCE_LAB."""
        data = self._data()
        cal_store = data.get("cal_store")
        if cal_store is None:
            return
        await cal_store.reset()
        self.hass.bus.async_fire(f"{DOMAIN}_calibration_reset", {})


async def async_handle_solve(
    hass: HomeAssistant, data: dict
) -> dict | None:
    """Run kociemba solver on scanned cube state.

    Returns {"solution": str, "move_count": int, "cube_string": str} or None on failure.
    Fires the rubiks_solved HA event on success.
    """
    kociemba_faces = data.get("kociemba_faces")
    if not kociemba_faces:
        _LOGGER.warning("Solve called but no kociemba face data — scan all 6 faces first.")
        return None

    cube_str = kociemba_string(kociemba_faces)
    if not cube_str:
        _LOGGER.warning("Solve called but could not build kociemba string.")
        return None

    _LOGGER.info("Solving cube: %s", cube_str)
    solution = await hass.async_add_executor_job(solve, cube_str)
    if solution is None:
        _LOGGER.error("Solver returned no solution for: %s", cube_str)
        return None

    if solution == "":
        _LOGGER.info("Cube is already solved.")
        solution = "Already solved!"
        move_count = 0
    else:
        move_count = len(solution.split())

    _LOGGER.info("Solution (%d moves): %s", move_count, solution)
    hass.bus.async_fire(
        f"{DOMAIN}_solved",
        {"solution": solution, "move_count": move_count, "cube_string": cube_str},
    )
    return {"solution": solution, "move_count": move_count, "cube_string": cube_str}


class SolveButton(RubiksButtonBase):
    """Run the kociemba solver on the current cube state and fire the result."""

    entity_description = SOLVE_BUTTON

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_solve"

    async def async_press(self) -> None:  # type: ignore[override]
        """Solve the current cube state using kociemba."""
        await async_handle_solve(self.hass, self._data())


def _write_file(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


# ── Robot control buttons ─────────────────────────────────────────────────────
# These fire HA events consumed by ha_automations/rubiks_robot.yaml, which
# translates them to ESPHome service calls. This keeps ESPHome service names
# (device-specific) out of the Python component.

class RobotStartScanButton(RubiksButtonBase):
    """Reset HA scan state and signal the robot to start a scan sequence."""

    entity_description = ROBOT_START_BUTTON

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_robot_start_scan"

    async def async_press(self) -> None:  # type: ignore[override]
        data = self._data()
        data["scanned_faces"] = {}
        data["face_scans"] = {}
        data["face_annotated_images"] = {}
        data["calibration_result"] = None
        data["summary_image"] = None
        data["scan_warnings"] = []
        data["kociemba_faces"] = None
        self.hass.bus.async_fire(f"{DOMAIN}_scan_reset", {})
        self.hass.bus.async_fire(f"{DOMAIN}_robot_start_requested", {})
        _LOGGER.info("Robot start scan requested.")


class RobotStopButton(RubiksButtonBase):
    """Signal the robot to stop its current operation."""

    entity_description = ROBOT_STOP_BUTTON

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_robot_stop"

    async def async_press(self) -> None:  # type: ignore[override]
        self.hass.bus.async_fire(f"{DOMAIN}_robot_stop_requested", {})
        _LOGGER.info("Robot stop requested.")


class RobotAbortButton(RubiksButtonBase):
    """Stop the robot AND reset HA scan state atomically."""

    entity_description = ROBOT_ABORT_BUTTON

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_robot_abort"

    async def async_press(self) -> None:  # type: ignore[override]
        data = self._data()
        data["scanned_faces"] = {}
        data["face_scans"] = {}
        data["face_annotated_images"] = {}
        data["calibration_result"] = None
        data["summary_image"] = None
        data["scan_warnings"] = []
        data["kociemba_faces"] = None
        self.hass.bus.async_fire(f"{DOMAIN}_scan_reset", {})
        self.hass.bus.async_fire(f"{DOMAIN}_robot_stop_requested", {})
        _LOGGER.info("Robot abort + HA scan reset.")


class RobotAdvanceFaceButton(RubiksButtonBase):
    """Manually advance the robot to the next scan face (debug/step-through)."""

    entity_description = ROBOT_ADVANCE_BUTTON

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_robot_advance_face"

    async def async_press(self) -> None:  # type: ignore[override]
        self.hass.bus.async_fire(f"{DOMAIN}_robot_advance_face_requested", {})
        _LOGGER.info("Robot advance face requested.")


class ScrambleButton(RubiksButtonBase):
    """Generate a random scramble and send it to the robot to execute.

    Reuses execute_solution() entirely — no firmware changes. Every existing guard
    (state_ == IDLE, needs_confirm_before_move_, believed_home_) applies automatically,
    same as a real solve, since it's the identical ESPHome action underneath.
    """

    entity_description = SCRAMBLE_BUTTON

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_scramble"

    async def async_press(self) -> None:  # type: ignore[override]
        count_entity = self._data().get("scramble_move_count_entity")
        move_count = count_entity.move_count if count_entity else SCRAMBLE_MOVE_COUNT_DEFAULT
        scramble = generate_scramble(move_count)
        self.hass.bus.async_fire(f"{DOMAIN}_scramble_requested", {"solution": scramble})
        _LOGGER.info("Scramble requested: %s (%d moves)", scramble, move_count)
