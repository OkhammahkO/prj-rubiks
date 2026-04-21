"""Config flow for Rubiks Cube Scanner."""

from __future__ import annotations

import os
from typing import Any

import voluptuous as vol

from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
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
        errors: dict[str, str] = {}

        if user_input is not None:
            return self.async_create_entry(
                title="Rubiks Cube Scanner (Camera)",
                data={
                    CONF_SOURCE: SOURCE_CAMERA,
                    CONF_CAMERA_ENTITY: user_input[CONF_CAMERA_ENTITY],
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
            errors=errors,
        )

    async def async_step_sample(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle sample image path entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            path = user_input[CONF_SAMPLE_IMAGE]
            if not os.path.isfile(path):
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
