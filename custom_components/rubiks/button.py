"""Button entities for Rubiks Cube Scanner."""

from __future__ import annotations

import logging
import os

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .camera_processor import (
    CropBox,
    detect_face_colors,
    load_image_from_bytes,
    load_image_from_path,
)
from .const import (
    ANNOTATED_IMAGE_PATH,
    CONF_CAMERA_ENTITY,
    CONF_SAMPLE_IMAGE,
    CONF_SOURCE,
    DOMAIN,
    SOURCE_CAMERA,
)

_LOGGER = logging.getLogger(__name__)

SCAN_BUTTON = ButtonEntityDescription(key="scan_face", translation_key="scan_face")
RESET_BUTTON = ButtonEntityDescription(key="reset_scan", translation_key="reset_scan")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Rubiks button entities."""
    async_add_entities([
        ScanFaceButton(hass, entry),
        ResetScanButton(hass, entry),
    ])


class ScanFaceButton(ButtonEntity):
    """Button to trigger scanning of the current cube face."""

    entity_description = SCAN_BUTTON
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the button."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_scan_face"

    async def async_press(self) -> None:
        """Scan the current face and store the result."""
        data = self.hass.data[DOMAIN][self._entry.entry_id]
        scanned: dict = data["scanned_faces"]

        if len(scanned) >= 6:
            _LOGGER.warning("All 6 faces already scanned. Reset before scanning again.")
            return

        # Read crop box from number entities
        crop_box: CropBox | None = self._get_crop_box(data)

        # Load image
        source = self._entry.data[CONF_SOURCE]
        try:
            if source == SOURCE_CAMERA:
                camera_entity_id = self._entry.data[CONF_CAMERA_ENTITY]
                image_bytes = await self._get_camera_snapshot(camera_entity_id)
                image = await self.hass.async_add_executor_job(load_image_from_bytes, image_bytes)
            else:
                path = self._entry.data[CONF_SAMPLE_IMAGE]
                image = await self.hass.async_add_executor_job(load_image_from_path, path)
        except Exception:
            _LOGGER.exception("Failed to load image for face scan")
            return

        # Detect colors (Pillow is not async)
        scan = await self.hass.async_add_executor_job(detect_face_colors, image, crop_box)

        # Reject if centre square is unknown
        if scan.centre_color == "?":
            _LOGGER.warning(
                "Scan rejected — centre square unclassified. Check crop region and lighting."
            )
            await self._save_annotated(scan.annotated_image)
            self.hass.bus.async_fire(f"{DOMAIN}_scan_rejected", {"reason": "centre_unknown"})
            return

        # Warn on partial unknowns but accept the scan
        if scan.has_unknowns:
            _LOGGER.warning(
                "Face %s scanned with unknown squares: %s", scan.face_label, scan.colors
            )

        # Reject duplicate face
        if scan.face_label in scanned:
            _LOGGER.warning(
                "Face with centre color %s already scanned. Rotate to a new face.",
                scan.face_label,
            )
            return

        scanned[scan.face_label] = scan.colors
        _LOGGER.info("Scanned face %s: %s", scan.face_label, scan.colors)

        await self._save_annotated(scan.annotated_image)

        self.hass.bus.async_fire(
            f"{DOMAIN}_face_scanned",
            {"face": scan.face_label, "colors": scan.colors},
        )

    def _get_crop_box(self, data: dict) -> CropBox | None:
        """Read current crop coordinates from number entity state."""
        try:
            from homeassistant.helpers import entity_registry as er
            registry = er.async_get(self.hass)

            def _value(key: str) -> int:
                entity_id = registry.async_get_entity_id("number", DOMAIN, f"{self._entry.entry_id}_{key}")
                if not entity_id:
                    return 0
                state = self.hass.states.get(entity_id)
                return int(float(state.state)) if state else 0

            left = _value("crop_left")
            top = _value("crop_top")
            right = _value("crop_right")
            bottom = _value("crop_bottom")

            if right > left and bottom > top:
                return (left, top, right, bottom)
        except Exception:
            _LOGGER.debug("Could not read crop box from number entities, using full image")
        return None

    async def _save_annotated(self, image_bytes: bytes) -> None:
        """Store annotated image in shared data (for camera entity) and www/ (for direct URL access)."""
        self.hass.data[DOMAIN][self._entry.entry_id]["last_annotated_image"] = image_bytes
        www_path = self.hass.config.path("www")
        os.makedirs(www_path, exist_ok=True)
        out_path = os.path.join(www_path, ANNOTATED_IMAGE_PATH)
        await self.hass.async_add_executor_job(_write_file, out_path, image_bytes)

    async def _get_camera_snapshot(self, entity_id: str) -> bytes:
        """Request a snapshot from a HA camera entity."""
        from homeassistant.components.camera import async_get_image

        camera_image = await async_get_image(self.hass, entity_id)
        return camera_image.content


class ResetScanButton(ButtonEntity):
    """Button to clear all scanned faces and start over."""

    entity_description = RESET_BUTTON
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the button."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_reset_scan"

    async def async_press(self) -> None:
        """Clear all scanned face data."""
        self.hass.data[DOMAIN][self._entry.entry_id]["scanned_faces"] = {}
        self.hass.bus.async_fire(f"{DOMAIN}_scan_reset", {})
        _LOGGER.info("Cube scan reset.")


def _write_file(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)
