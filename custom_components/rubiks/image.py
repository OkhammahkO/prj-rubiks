"""Image entities for Rubiks Cube Scanner."""

from __future__ import annotations

import logging

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CUBE_COLORS, DEVICE_MANUFACTURER, DEVICE_MODEL, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Rubiks image entities."""
    async_add_entities([
        LastScanImage(hass, entry),
        *[FaceScanImage(hass, entry, colour) for colour in CUBE_COLORS],
        SummaryImage(hass, entry),
    ])


class RubiksImageBase(ImageEntity):
    """Shared base for all Rubiks image entities."""

    _attr_has_entity_name = True
    _attr_content_type = "image/jpeg"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass)
        self._entry = entry
        self._image_bytes: bytes | None = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_MODEL,
            manufacturer=DEVICE_MANUFACTURER,
        )

    def _refresh(self, image_bytes: bytes | None) -> None:
        """Update image bytes and notify HA."""
        self._image_bytes = image_bytes
        self._cached_image = None
        self._attr_image_last_updated = dt_util.now()
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        """Return the latest image bytes."""
        return self._image_bytes


class LastScanImage(RubiksImageBase):
    """Most recent annotated scan — updates on every scan or preview."""

    entity_description = ImageEntityDescription(key="last_scan", translation_key="last_scan")

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_scan"

    async def async_added_to_hass(self) -> None:
        """Subscribe to scan and preview events."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_face_scanned", self._on_update)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_scan_rejected", self._on_update)
        )

    @callback
    def _on_update(self, event: Event) -> None:
        self._refresh(
            self.hass.data[DOMAIN][self._entry.entry_id].get("last_annotated_image")
        )


class FaceScanImage(RubiksImageBase):
    """Persists the annotated image for one specific cube face."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, colour: str) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._colour = colour
        self._attr_unique_id = f"{entry.entry_id}_face_{colour.lower()}"
        self.entity_description = ImageEntityDescription(
            key=f"face_{colour.lower()}",
            translation_key=f"face_{colour.lower()}",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to face scanned and reset events."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_face_scanned", self._on_face_scanned)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_scan_reset", self._on_reset)
        )

    @callback
    def _on_face_scanned(self, event: Event) -> None:
        if event.data.get("face") != self._colour:
            return
        images = self.hass.data[DOMAIN][self._entry.entry_id].get("face_annotated_images", {})
        self._refresh(images.get(self._colour))

    @callback
    def _on_reset(self, event: Event) -> None:
        self._refresh(None)


class SummaryImage(RubiksImageBase):
    """3×2 grid of all 6 face scans — generated after calibration."""

    entity_description = ImageEntityDescription(key="summary", translation_key="summary")

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_summary"

    async def async_added_to_hass(self) -> None:
        """Subscribe to calibration and reset events."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_calibrated", self._on_calibrated)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_scan_reset", self._on_reset)
        )

    @callback
    def _on_calibrated(self, event: Event) -> None:
        self._refresh(
            self.hass.data[DOMAIN][self._entry.entry_id].get("summary_image")
        )

    @callback
    def _on_reset(self, event: Event) -> None:
        self._refresh(None)
