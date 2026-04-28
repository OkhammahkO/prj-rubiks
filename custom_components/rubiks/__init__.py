"""The Rubiks Cube Scanner integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .cal_store import CalibrationStore
from .const import DOMAIN

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.IMAGE,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.TEXT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Rubiks from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    cal_store = await CalibrationStore.create(hass, entry.entry_id)
    hass.data[DOMAIN][entry.entry_id] = {
        "scanned_faces": {},
        "face_scans": {},            # face_label -> FaceScan (colours + lab_readings)
        "face_annotated_images": {}, # face_label -> annotated JPEG bytes
        "calibration_result": None,
        "summary_image": None,
        "last_annotated_image": None,
        "image_size": None,
        "scan_warnings": [],
        "crop_entities": {},
        "led_brightness_entity": None,
        "led_stabilise_delay_entity": None,
        "led_entity_id_entity": None,
        "cal_store": cal_store,
        "kociemba_faces": None,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
