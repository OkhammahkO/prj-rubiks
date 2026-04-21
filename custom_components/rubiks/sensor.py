"""Sensor entities for Rubiks Cube Scanner."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CUBE_COLORS, DOMAIN

_LOGGER = logging.getLogger(__name__)

CUBE_STATE_SENSOR = SensorEntityDescription(key="cube_state", translation_key="cube_state")
CURRENT_FACE_SENSOR = SensorEntityDescription(key="current_face", translation_key="current_face")
FACES_SCANNED_SENSOR = SensorEntityDescription(key="faces_scanned", translation_key="faces_scanned")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Rubiks sensor entities."""
    async_add_entities([
        CubeStateSensor(hass, entry),
        CurrentFaceSensor(hass, entry),
        FacesScannedSensor(hass, entry),
    ])


class CubeStateSensor(SensorEntity):
    """Full cube state once all 6 faces are scanned (54-char string)."""

    entity_description = CUBE_STATE_SENSOR
    _attr_has_entity_name = True
    _attr_native_value: str | None = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_cube_state"

    async def async_added_to_hass(self) -> None:
        """Subscribe to face scan events."""
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_face_scanned", self._on_face_scanned)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_scan_reset", self._on_reset)
        )

    @callback
    def _on_face_scanned(self, event: Event) -> None:
        scanned: dict = self.hass.data[DOMAIN][self._entry.entry_id]["scanned_faces"]
        if len(scanned) == 6:
            # Build state string ordered by centre color: W Y R O B G
            self._attr_native_value = "".join(
                "".join(scanned[color]) for color in CUBE_COLORS if color in scanned
            )
        else:
            self._attr_native_value = None
        self.async_write_ha_state()

    @callback
    def _on_reset(self, event: Event) -> None:
        self._attr_native_value = None
        self.async_write_ha_state()


class CurrentFaceSensor(SensorEntity):
    """Shows how many faces have been scanned and which colors are still missing."""

    entity_description = CURRENT_FACE_SENSOR
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_current_face"
        self._attr_native_value: str = "ready"

    async def async_added_to_hass(self) -> None:
        """Subscribe to events."""
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_face_scanned", self._on_face_scanned)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_scan_reset", self._on_reset)
        )

    @callback
    def _on_face_scanned(self, event: Event) -> None:
        scanned: dict = self.hass.data[DOMAIN][self._entry.entry_id]["scanned_faces"]
        missing = [c for c in CUBE_COLORS if c not in scanned]
        self._attr_native_value = "complete" if not missing else f"missing: {', '.join(missing)}"
        self.async_write_ha_state()

    @callback
    def _on_reset(self, event: Event) -> None:
        self._attr_native_value = "ready"
        self.async_write_ha_state()


class FacesScannedSensor(SensorEntity):
    """Number of faces scanned (0-6) with per-face color data as attributes."""

    entity_description = FACES_SCANNED_SENSOR
    _attr_has_entity_name = True
    _attr_native_value: int = 0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_faces_scanned"
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Subscribe to events."""
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_face_scanned", self._on_face_scanned)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_scan_reset", self._on_reset)
        )

    @callback
    def _on_face_scanned(self, event: Event) -> None:
        scanned: dict = self.hass.data[DOMAIN][self._entry.entry_id]["scanned_faces"]
        self._attr_native_value = len(scanned)
        # Expose each face's 9 colors keyed by centre color, e.g. {"W": ["W","R","G",...]}
        self._attr_extra_state_attributes = {
            color: colors for color, colors in scanned.items()
        }
        self.async_write_ha_state()

    @callback
    def _on_reset(self, event: Event) -> None:
        self._attr_native_value = 0
        self._attr_extra_state_attributes = {}
        self.async_write_ha_state()
