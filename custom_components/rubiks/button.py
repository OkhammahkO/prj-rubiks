"""Button entities for Rubiks Cube Scanner."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CAMERA_ENTITY,
    CONF_SAMPLE_IMAGE,
    CONF_SOURCE,
    DOMAIN,
    FACES,
    SOURCE_CAMERA,
)
from .camera_processor import (
    detect_face_colors,
    load_image_from_bytes,
    load_image_from_path,
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

        # Determine the next face to scan
        next_face = next((f for f in FACES if f not in scanned), None)
        if next_face is None:
            _LOGGER.warning("All 6 faces already scanned. Reset before scanning again.")
            return

        # Load image
        source = self._entry.data[CONF_SOURCE]
        try:
            if source == SOURCE_CAMERA:
                camera_entity_id = self._entry.data[CONF_CAMERA_ENTITY]
                image_bytes = await self._get_camera_snapshot(camera_entity_id)
                image = load_image_from_bytes(image_bytes)
            else:
                path = self._entry.data[CONF_SAMPLE_IMAGE]
                image = await self.hass.async_add_executor_job(load_image_from_path, path)
        except Exception:
            _LOGGER.exception("Failed to load image for face scan")
            return

        # Detect colors (run in executor — Pillow is not async)
        colors = await self.hass.async_add_executor_job(detect_face_colors, image)
        scanned[next_face] = colors
        _LOGGER.info("Scanned face %s: %s", next_face, colors)

        # Fire event so sensors update
        self.hass.bus.async_fire(f"{DOMAIN}_face_scanned", {"face": next_face, "colors": colors})

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
