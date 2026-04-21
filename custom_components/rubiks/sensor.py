"""Sensor entities for Rubiks Cube Scanner."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, FACES

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
    """Sensor showing the full cube state once all 6 faces are scanned.

    Value is a 54-character string (standard kociemba notation) or None.
    """

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
        """Update cube state when a face is scanned."""
        scanned = self.hass.data[DOMAIN][self._entry.entry_id]["scanned_faces"]
        if all(f in scanned for f in FACES):
            # Build 54-char state string: U9 + R9 + F9 + D9 + L9 + B9
            self._attr_native_value = "".join(
                "".join(scanned[face]) for face in FACES
            )
        else:
            self._attr_native_value = None
        self.async_write_ha_state()

    @callback
    def _on_reset(self, event: Event) -> None:
        """Clear state on reset."""
        self._attr_native_value = None
        self.async_write_ha_state()


class CurrentFaceSensor(SensorEntity):
    """Sensor showing which face will be scanned next."""

    entity_description = CURRENT_FACE_SENSOR
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_current_face"
        self._attr_native_value = FACES[0]

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
        """Advance to next face."""
        scanned = self.hass.data[DOMAIN][self._entry.entry_id]["scanned_faces"]
        next_face = next((f for f in FACES if f not in scanned), None)
        self._attr_native_value = next_face or "complete"
        self.async_write_ha_state()

    @callback
    def _on_reset(self, event: Event) -> None:
        """Reset to first face."""
        self._attr_native_value = FACES[0]
        self.async_write_ha_state()


class FacesScannedSensor(SensorEntity):
    """Sensor showing how many faces have been scanned (0-6)."""

    entity_description = FACES_SCANNED_SENSOR
    _attr_has_entity_name = True
    _attr_native_value: int = 0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_faces_scanned"

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
        """Increment count."""
        scanned = self.hass.data[DOMAIN][self._entry.entry_id]["scanned_faces"]
        self._attr_native_value = len(scanned)
        self.async_write_ha_state()

    @callback
    def _on_reset(self, event: Event) -> None:
        """Reset count."""
        self._attr_native_value = 0
        self.async_write_ha_state()
