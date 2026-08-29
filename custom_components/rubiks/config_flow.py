"""Config flow for Rubiks Cube Scanner."""

from __future__ import annotations

import os
from typing import Any

import voluptuous as vol
from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_CAMERA_ENTITY,
    CONF_SAMPLE_IMAGE,
    CONF_SOURCE,
    DOMAIN,
    LED_ENTITY_ID,
    SOURCE_CAMERA,
    SOURCE_SAMPLE,
)


class RubiksConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rubiks Cube Scanner."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the config flow."""
        self._source: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — choose image source."""
        if user_input is not None:
            self._source = user_input[CONF_SOURCE]
            if self._source == SOURCE_CAMERA:
                return await self.async_step_camera()
            return await self.async_step_sample()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCE): SelectSelector(
                        SelectSelectorConfig(
                            options=[SOURCE_CAMERA, SOURCE_SAMPLE],
                            mode=SelectSelectorMode.LIST,
                            translation_key="source",
                        )
                    )
                }
            ),
        )

    async def async_step_camera(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle camera entity selection."""
        if user_input is not None:
            camera_entity = user_input[CONF_CAMERA_ENTITY]
            led_entity = await self._discover_led(camera_entity)
            return self.async_create_entry(
                title="Rubiks Cube Scanner (Camera)",
                data={
                    CONF_SOURCE: SOURCE_CAMERA,
                    CONF_CAMERA_ENTITY: camera_entity,
                    LED_ENTITY_ID: led_entity,
                },
            )

        return self.async_show_form(
            step_id="camera",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CAMERA_ENTITY): EntitySelector(
                        EntitySelectorConfig(domain=CAMERA_DOMAIN)
                    )
                }
            ),
        )

    async def _discover_led(self, camera_entity_id: str) -> str | None:
        """Find the single light entity on the same device as the camera, if any."""
        ent_reg = er.async_get(self.hass)
        cam_entry = ent_reg.async_get(camera_entity_id)
        if cam_entry is None or cam_entry.device_id is None:
            return None
        lights = [
            e.entity_id
            for e in ent_reg.entities.get_entries_for_device_id(cam_entry.device_id)
            if e.domain == "light"
        ]
        return lights[0] if len(lights) == 1 else None

    async def async_step_sample(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle sample image path entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            path = user_input[CONF_SAMPLE_IMAGE]
            exists = await self.hass.async_add_executor_job(os.path.isfile, path)
            if not exists:
                errors[CONF_SAMPLE_IMAGE] = "invalid_image"
            else:
                return self.async_create_entry(
                    title="Rubiks Cube Scanner (Sample Image)",
                    data={
                        CONF_SOURCE: SOURCE_SAMPLE,
                        CONF_SAMPLE_IMAGE: path,
                    },
                )

        return self.async_show_form(
            step_id="sample",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SAMPLE_IMAGE): TextSelector()
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return RubiksOptionsFlow()


class RubiksOptionsFlow(OptionsFlow):
    """Options flow handler for Rubiks Cube Scanner."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        source = self.config_entry.data.get(CONF_SOURCE, SOURCE_CAMERA)

        if user_input is not None:
            if source != SOURCE_CAMERA:
                path = user_input[CONF_SAMPLE_IMAGE]
                exists = await self.hass.async_add_executor_job(os.path.isfile, path)
                if not exists:
                    errors[CONF_SAMPLE_IMAGE] = "invalid_image"
            if not errors:
                return self.async_create_entry(data=user_input)

        if source == SOURCE_CAMERA:
            current_cam = self.config_entry.options.get(
                CONF_CAMERA_ENTITY,
                self.config_entry.data.get(CONF_CAMERA_ENTITY),
            )
            current_led = self.config_entry.options.get(
                LED_ENTITY_ID,
                self.config_entry.data.get(LED_ENTITY_ID),
            )
            schema = vol.Schema(
                {
                    vol.Required(CONF_CAMERA_ENTITY, default=current_cam): EntitySelector(
                        EntitySelectorConfig(domain=CAMERA_DOMAIN)
                    ),
                    vol.Optional(LED_ENTITY_ID, default=current_led or ""): EntitySelector(
                        EntitySelectorConfig(domain="light")
                    ),
                }
            )
        else:
            current = self.config_entry.options.get(
                CONF_SAMPLE_IMAGE,
                self.config_entry.data.get(CONF_SAMPLE_IMAGE),
            )
            schema = vol.Schema(
                {
                    vol.Required(CONF_SAMPLE_IMAGE, default=current): TextSelector()
                }
            )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
