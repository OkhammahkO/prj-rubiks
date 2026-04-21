"""Number entities for Rubiks Cube Scanner crop region."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CROP_BOTTOM, CROP_LEFT, CROP_RIGHT, CROP_TOP

CROP_ENTITIES: list[tuple[NumberEntityDescription, int]] = [
    (NumberEntityDescription(key=CROP_LEFT, translation_key=CROP_LEFT, native_min_value=0, native_max_value=4096, native_step=1, mode=NumberMode.BOX), 0),
    (NumberEntityDescription(key=CROP_TOP, translation_key=CROP_TOP, native_min_value=0, native_max_value=4096, native_step=1, mode=NumberMode.BOX), 0),
    (NumberEntityDescription(key=CROP_RIGHT, translation_key=CROP_RIGHT, native_min_value=0, native_max_value=4096, native_step=1, mode=NumberMode.BOX), 0),
    (NumberEntityDescription(key=CROP_BOTTOM, translation_key=CROP_BOTTOM, native_min_value=0, native_max_value=4096, native_step=1, mode=NumberMode.BOX), 0),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up crop region number entities."""
    async_add_entities([
        CropNumberEntity(hass, entry, description, default)
        for description, default in CROP_ENTITIES
    ])


class CropNumberEntity(NumberEntity):
    """A number entity representing one edge of the crop region."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        description: NumberEntityDescription,
        default: float,
    ) -> None:
        """Initialise."""
        self.hass = hass
        self._entry = entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_native_value = default

    async def async_set_native_value(self, value: float) -> None:
        """Update the crop coordinate."""
        self._attr_native_value = value
        self.async_write_ha_state()
