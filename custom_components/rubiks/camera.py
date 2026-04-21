"""Camera entity for Rubiks Cube Scanner — serves the last annotated scan image."""

from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

SCAN_CAMERA = CameraEntityDescription(key="last_scan", translation_key="last_scan")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Rubiks camera entity."""
    async_add_entities([LastScanCamera(hass, entry)])


class LastScanCamera(Camera):
    """Camera entity that serves the most recent annotated scan image."""

    entity_description = SCAN_CAMERA
    _attr_has_entity_name = True
    _attr_is_streaming = False
    _attr_frame_interval = 0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__()
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_last_scan"
        self._image: bytes | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to scan events so the image updates automatically."""
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_face_scanned", self._on_scan)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_scan_rejected", self._on_scan)
        )

    @callback
    def _on_scan(self, event: Event) -> None:
        """Pull the latest annotated image from shared data and refresh."""
        self._image = self.hass.data[DOMAIN][self._entry.entry_id].get("last_annotated_image")
        self.async_write_ha_state()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the latest annotated image bytes."""
        return self._image
