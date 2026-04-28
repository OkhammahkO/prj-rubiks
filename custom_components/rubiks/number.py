"""Number entities for Rubiks Cube Scanner."""

from __future__ import annotations

import logging

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from .const import (
    CROP_BOTTOM,
    CROP_LEFT,
    CROP_RIGHT,
    CROP_TOP,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    LED_BRIGHTNESS,
    LED_STABILISE_DELAY,
)

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1

CROP_ENTITIES: list[tuple[NumberEntityDescription, float]] = [
    (
        NumberEntityDescription(
            key=CROP_LEFT,
            translation_key=CROP_LEFT,
            native_min_value=0,
            native_max_value=4096,
            native_step=1,
            mode=NumberMode.SLIDER,
            icon="mdi:arrow-collapse-left",
        ),
        0,
    ),
    (
        NumberEntityDescription(
            key=CROP_TOP,
            translation_key=CROP_TOP,
            native_min_value=0,
            native_max_value=4096,
            native_step=1,
            mode=NumberMode.SLIDER,
            icon="mdi:arrow-collapse-up",
        ),
        0,
    ),
    (
        NumberEntityDescription(
            key=CROP_RIGHT,
            translation_key=CROP_RIGHT,
            native_min_value=0,
            native_max_value=4096,
            native_step=1,
            mode=NumberMode.SLIDER,
            icon="mdi:arrow-collapse-right",
        ),
        0,
    ),
    (
        NumberEntityDescription(
            key=CROP_BOTTOM,
            translation_key=CROP_BOTTOM,
            native_min_value=0,
            native_max_value=4096,
            native_step=1,
            mode=NumberMode.SLIDER,
            icon="mdi:arrow-collapse-down",
        ),
        0,
    ),
]


LED_BRIGHTNESS_DESCRIPTION = NumberEntityDescription(
    key=LED_BRIGHTNESS,
    translation_key=LED_BRIGHTNESS,
    native_min_value=0,
    native_max_value=255,
    native_step=1,
    mode=NumberMode.SLIDER,
    icon="mdi:brightness-6",
)

LED_STABILISE_DELAY_DESCRIPTION = NumberEntityDescription(
    key=LED_STABILISE_DELAY,
    translation_key=LED_STABILISE_DELAY,
    native_min_value=0.0,
    native_max_value=2.0,
    native_step=0.05,
    native_unit_of_measurement="s",
    mode=NumberMode.BOX,
    icon="mdi:timer-outline",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up crop and LED number entities."""
    crop_store = Store(hass, _STORAGE_VERSION, f"{DOMAIN}_crop_{entry.entry_id}")
    crop_saved: dict[str, float] = await crop_store.async_load() or {}

    led_store = Store(hass, _STORAGE_VERSION, f"{DOMAIN}_led_{entry.entry_id}")
    led_saved: dict[str, float] = await led_store.async_load() or {}

    led_brightness = LedBrightnessEntity(
        hass, entry, led_saved.get(LED_BRIGHTNESS, 200.0), led_store
    )
    hass.data[DOMAIN][entry.entry_id]["led_brightness_entity"] = led_brightness

    delay_store = Store(hass, _STORAGE_VERSION, f"{DOMAIN}_led_delay_{entry.entry_id}")
    delay_saved: dict[str, float] = await delay_store.async_load() or {}

    led_stabilise_delay = LedStabiliseDelayEntity(
        hass, entry, delay_saved.get(LED_STABILISE_DELAY, 0.3), delay_store
    )
    hass.data[DOMAIN][entry.entry_id]["led_stabilise_delay_entity"] = led_stabilise_delay

    async_add_entities([
        CropNumberEntity(hass, entry, desc, crop_saved.get(desc.key, default), crop_store)
        for desc, default in CROP_ENTITIES
    ] + [led_brightness, led_stabilise_delay])


class CropNumberEntity(NumberEntity):
    """A number entity representing one edge of the crop region."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        description: NumberEntityDescription,
        initial: float,
        store: Store,
    ) -> None:
        """Initialise."""
        self.hass = hass
        self._entry = entry
        self._store = store
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_native_value = initial
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_MODEL,
            manufacturer=DEVICE_MANUFACTURER,
        )
        _LOGGER.info("Crop %s initialised to %s", description.key, initial)

    async def async_added_to_hass(self) -> None:
        """Register entity for crop box reads."""
        await super().async_added_to_hass()
        self.hass.data[DOMAIN][self._entry.entry_id]["crop_entities"][
            self.entity_description.key
        ] = self

    async def async_set_native_value(self, value: float) -> None:
        """Update the crop coordinate and persist immediately."""
        self._attr_native_value = value
        self.async_write_ha_state()
        await self._persist()

    async def _persist(self) -> None:
        """Write all crop values to storage."""
        entities: dict = self.hass.data[DOMAIN][self._entry.entry_id].get("crop_entities", {})
        await self._store.async_save({
            key: entity._attr_native_value for key, entity in entities.items()
        })

    def update_max(self, max_value: int) -> None:
        """Update the slider maximum to match image dimensions."""
        self._attr_native_max_value = max_value
        if self._attr_native_value > max_value:
            self._attr_native_value = float(max_value)
        self.async_write_ha_state()


class LedBrightnessEntity(NumberEntity):
    """Brightness level (0–255) to set the LED to before each scan/preview."""

    _attr_has_entity_name = True
    entity_description = LED_BRIGHTNESS_DESCRIPTION

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        initial: float,
        store: Store,
    ) -> None:
        """Initialise."""
        self.hass = hass
        self._entry = entry
        self._store = store
        self._attr_unique_id = f"{entry.entry_id}_{LED_BRIGHTNESS}"
        self._attr_native_value = initial
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_MODEL,
            manufacturer=DEVICE_MANUFACTURER,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Persist and update brightness."""
        self._attr_native_value = value
        self.async_write_ha_state()
        await self._store.async_save({LED_BRIGHTNESS: value})

    @property
    def brightness(self) -> int:
        """Return brightness as integer (0–255)."""
        return int(self._attr_native_value or 0)


class LedStabiliseDelayEntity(NumberEntity):
    """Seconds to wait after turning on the LED before capturing an image."""

    _attr_has_entity_name = True
    entity_description = LED_STABILISE_DELAY_DESCRIPTION

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        initial: float,
        store: Store,
    ) -> None:
        """Initialise."""
        self.hass = hass
        self._entry = entry
        self._store = store
        self._attr_unique_id = f"{entry.entry_id}_{LED_STABILISE_DELAY}"
        self._attr_native_value = initial
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_MODEL,
            manufacturer=DEVICE_MANUFACTURER,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Persist and update delay."""
        self._attr_native_value = value
        self.async_write_ha_state()
        await self._store.async_save({LED_STABILISE_DELAY: value})

    @property
    def delay(self) -> float:
        """Return stabilisation delay in seconds."""
        return float(self._attr_native_value or 0.0)
