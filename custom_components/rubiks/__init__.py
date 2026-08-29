"""The Rubiks Cube Scanner integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .button import async_handle_robot_scan_face, async_handle_solve
from .cal_store import CalibrationStore
from .const import DOMAIN, LED_ENTITY_ID, SCAN_SEQUENCE

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.IMAGE,
    Platform.NUMBER,
    Platform.SENSOR,
]

_ROBOT_SCAN_FACE_SCHEMA = vol.Schema({
    vol.Required("face"): vol.In(SCAN_SEQUENCE),
})


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
        "led_entity_id": entry.options.get(LED_ENTITY_ID) or entry.data.get(LED_ENTITY_ID),
        "led_brightness_entity": None,
        "led_stabilise_delay_entity": None,
        "scramble_move_count_entity": None,
        "cal_store": cal_store,
        "kociemba_faces": None,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    if not hass.services.has_service(DOMAIN, "robot_scan_face"):
        async def _robot_scan_face(call: ServiceCall) -> None:
            await async_handle_robot_scan_face(hass, call)

        hass.services.async_register(
            DOMAIN, "robot_scan_face", _robot_scan_face, schema=_ROBOT_SCAN_FACE_SCHEMA
        )

    if not hass.services.has_service(DOMAIN, "solve"):
        async def _solve(call: ServiceCall) -> dict:
            entries = hass.config_entries.async_entries(DOMAIN)
            if not entries:
                return {"solution": "", "move_count": 0, "error": "Integration not configured"}
            data = hass.data[DOMAIN].get(entries[0].entry_id, {})
            result = await async_handle_solve(hass, data)
            if result is None:
                return {"solution": "", "move_count": 0, "error": "Solve failed — check logs"}
            return result

        hass.services.async_register(
            DOMAIN, "solve", _solve, supports_response=SupportsResponse.OPTIONAL
        )

    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.config_entries.async_entries(DOMAIN):
            hass.services.async_remove(DOMAIN, "robot_scan_face")
            hass.services.async_remove(DOMAIN, "solve")
    return unload_ok
