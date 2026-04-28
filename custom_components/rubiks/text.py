"""Text entities for Rubiks Cube Scanner."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from .const import DEVICE_MANUFACTURER, DEVICE_MODEL, DOMAIN, LED_ENTITY_ID

_STORAGE_VERSION = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Rubiks text entities."""
    store = Store(hass, _STORAGE_VERSION, f"{DOMAIN}_text_{entry.entry_id}")
    saved: dict[str, str] = await store.async_load() or {}

    entity = LedEntityIdText(hass, entry, saved.get(LED_ENTITY_ID, ""), store)
    hass.data[DOMAIN][entry.entry_id]["led_entity_id_entity"] = entity
    async_add_entities([entity])


class LedEntityIdText(TextEntity):
    """Entity ID of the HA light to illuminate before each scan."""

    _attr_has_entity_name = True
    entity_description = TextEntityDescription(
        key=LED_ENTITY_ID,
        translation_key=LED_ENTITY_ID,
        pattern=r"^(light\.[a-z0-9_]+)?$",
    )

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        initial: str,
        store: Store,
    ) -> None:
        """Initialise."""
        self.hass = hass
        self._entry = entry
        self._store = store
        self._attr_unique_id = f"{entry.entry_id}_{LED_ENTITY_ID}"
        self._attr_native_value = initial
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_MODEL,
            manufacturer=DEVICE_MANUFACTURER,
        )

    async def async_set_value(self, value: str) -> None:
        """Persist and update entity ID."""
        self._attr_native_value = value
        self.async_write_ha_state()
        await self._store.async_save({LED_ENTITY_ID: value})

    @property
    def configured_entity_id(self) -> str | None:
        """Return the configured entity ID, or None if blank."""
        return self._attr_native_value or None
