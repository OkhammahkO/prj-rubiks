"""Button entities for Rubiks Cube Scanner."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.components.camera import async_get_image
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .solver import build_kociemba_faces, diagnose_cube_string, kociemba_string, solve
from .camera_processor import (
    CropBox,
    REFERENCE_LAB,
    lab_distance,
    calibrate_faces,
    check_running_validity,
    detect_face_colors,
    generate_summary_image,
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
    SCAN_SEQUENCE,
    SOURCE_CAMERA,
)

if TYPE_CHECKING:
    from PIL.Image import Image

_LOGGER = logging.getLogger(__name__)

SCAN_BUTTON = ButtonEntityDescription(key="scan_face", translation_key="scan_face")
PREVIEW_BUTTON = ButtonEntityDescription(key="preview_crop", translation_key="preview_crop")
RESET_BUTTON = ButtonEntityDescription(key="reset_scan", translation_key="reset_scan")
SAVE_CAL_BUTTON = ButtonEntityDescription(
    key="save_calibration", translation_key="save_calibration"
)
RESET_CAL_BUTTON = ButtonEntityDescription(
    key="reset_calibration", translation_key="reset_calibration"
)
SOLVE_BUTTON = ButtonEntityDescription(key="solve", translation_key="solve")

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
    ])


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
        )

    async def async_press(self) -> None:  # type: ignore[override]
        """Override in subclasses."""

    async def _load_image(self) -> Image:
        """Load image from configured source and store its dimensions in shared data."""
        await self._illuminate()
        source = self._entry.data[CONF_SOURCE]
        if source == SOURCE_CAMERA:
            camera_entity_id = self._entry.data[CONF_CAMERA_ENTITY]
            image_bytes = await self._get_camera_snapshot(camera_entity_id)
            image = await self.hass.async_add_executor_job(
                load_image_from_bytes, image_bytes
            )
        else:
            path = self._entry.data[CONF_SAMPLE_IMAGE]
            image = await self.hass.async_add_executor_job(load_image_from_path, path)

        w, h = image.size
        self.hass.data[DOMAIN][self._entry.entry_id]["image_size"] = (w, h)
        self._update_crop_max(w, h)
        return image

    def _get_crop_box(self) -> CropBox | None:
        """Read current crop coordinates from number entities."""
        entities = self.hass.data[DOMAIN][self._entry.entry_id].get("crop_entities", {})
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

    async def _save_annotated(self, image_bytes: bytes) -> None:
        """Store annotated image in shared data and www/."""
        self.hass.data[DOMAIN][self._entry.entry_id]["last_annotated_image"] = image_bytes
        www_path = self.hass.config.path("www")
        os.makedirs(www_path, exist_ok=True)
        out_path = os.path.join(www_path, ANNOTATED_IMAGE_PATH)
        await self.hass.async_add_executor_job(_write_file, out_path, image_bytes)

    def _update_crop_max(self, width: int, height: int) -> None:
        """Set slider maximums to match actual image dimensions."""
        entities = self.hass.data[DOMAIN][self._entry.entry_id].get("crop_entities", {})
        for key in ("crop_left", "crop_right"):
            if entity := entities.get(key):
                entity.update_max(width)
        for key in ("crop_top", "crop_bottom"):
            if entity := entities.get(key):
                entity.update_max(height)

    async def _illuminate(self) -> None:
        """Turn on the configured LED at the configured brightness, then wait to stabilise."""
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        led_id_entity = data.get("led_entity_id_entity")
        led_br_entity = data.get("led_brightness_entity")
        if led_id_entity is None or led_br_entity is None:
            return
        entity_id = led_id_entity.configured_entity_id
        if not entity_id:
            return
        brightness = led_br_entity.brightness
        await self.hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": entity_id, "brightness": brightness},
            blocking=True,
        )
        delay_entity = data.get("led_stabilise_delay_entity")
        await asyncio.sleep(delay_entity.delay if delay_entity else 0.3)

    async def _get_camera_snapshot(self, entity_id: str) -> bytes:
        """Request a snapshot from a HA camera entity."""
        t0 = time.monotonic()
        camera_image = await async_get_image(self.hass, entity_id)
        _LOGGER.info(
            "Camera snapshot took %.2fs, size: %d bytes",
            time.monotonic() - t0,
            len(camera_image.content),
        )
        return camera_image.content


class ScanFaceButton(RubiksButtonBase):
    """Button to trigger scanning of the current cube face."""

    entity_description = SCAN_BUTTON

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_scan_face"

    async def async_press(self) -> None:  # type: ignore[override]
        """Scan the next face in sequence and store the result."""
        data = self.hass.data[DOMAIN][self._entry.entry_id]
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
            await self._run_calibration()

    async def _run_calibration(self) -> None:
        """Calibrate all 6 faces, build kociemba string, and fire the calibrated event."""
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        scanned = data["scanned_faces"]
        cal_store = data.get("cal_store")

        result = await self.hass.async_add_executor_job(calibrate_faces, data["face_scans"])
        data["calibration_result"] = result
        for lbl, colours in result.calibrated_faces.items():
            scanned[lbl] = colours
        data["summary_image"] = await self.hass.async_add_executor_job(
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

        kociemba_faces = build_kociemba_faces(scanned)
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

        self.hass.bus.async_fire(
            f"{DOMAIN}_calibrated",
            {
                "parity_valid": result.parity_valid,
                "corrections": len(result.pre_calibration_changes),
                "low_confidence": len(result.low_confidence),
                "anchors_saved": result.parity_valid,
                "kociemba_string": cube_str,
            },
        )


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

        crop_box = self._get_crop_box()
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        cal_store = data.get("cal_store")
        refs = cal_store.get_references() if cal_store else None
        scan = await self.hass.async_add_executor_job(
            detect_face_colors, image, crop_box, refs,
        )
        await self._save_annotated(scan.annotated_image)
        self.hass.bus.async_fire(f"{DOMAIN}_scan_rejected", {})
        _LOGGER.info("Preview updated — crop: %s", crop_box)


class ResetScanButton(RubiksButtonBase):
    """Button to clear all scanned faces and start over."""

    entity_description = RESET_BUTTON

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_reset_scan"

    async def async_press(self) -> None:  # type: ignore[override]
        """Clear all scanned face data."""
        data = self.hass.data[DOMAIN][self._entry.entry_id]
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
        data = self.hass.data[DOMAIN][self._entry.entry_id]
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
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        cal_store = data.get("cal_store")
        if cal_store is None:
            return
        await cal_store.reset()
        self.hass.bus.async_fire(f"{DOMAIN}_calibration_reset", {})


class SolveButton(RubiksButtonBase):
    """Run the kociemba solver on the current cube state and fire the result."""

    entity_description = SOLVE_BUTTON

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_solve"

    async def async_press(self) -> None:  # type: ignore[override]
        """Solve the current cube state using kociemba."""
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        kociemba_faces = data.get("kociemba_faces")
        if not kociemba_faces:
            _LOGGER.warning("Solve pressed but no kociemba face data — scan all 6 faces first.")
            return

        cube_str = kociemba_string(kociemba_faces)
        if not cube_str:
            _LOGGER.warning("Solve pressed but could not build kociemba string.")
            return

        _LOGGER.info("Solving cube: %s", cube_str)
        solution = await self.hass.async_add_executor_job(solve, cube_str)
        if solution is None:
            _LOGGER.error("Solver returned no solution for: %s", cube_str)
            return

        if solution == "":
            _LOGGER.info("Cube is already solved.")
            solution = "Already solved!"
            move_count = 0
        else:
            move_count = len(solution.split())
        _LOGGER.info("Solution (%d moves): %s", move_count, solution)
        self.hass.bus.async_fire(
            f"{DOMAIN}_solved",
            {"solution": solution, "move_count": move_count, "cube_string": cube_str},
        )


def _write_file(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)
