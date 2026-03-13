"""Config flow for NetWalker."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_COMMUNITY,
    CONF_MANUAL_LINKS,
    CONF_PORT,
    CONF_RETRIES,
    CONF_SCAN_INTERVAL,
    CONF_SCAN_TARGETS,
    CONF_TIMEOUT,
    CONF_TITLE,
    DEFAULT_COMMUNITY,
    DEFAULT_PORT,
    DEFAULT_RETRIES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DEFAULT_TITLE,
    DOMAIN,
)


def _base_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_TITLE, default=defaults.get(CONF_TITLE, DEFAULT_TITLE)
            ): selector.TextSelector(),
            vol.Required(
                CONF_SCAN_TARGETS, default=defaults.get(CONF_SCAN_TARGETS, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
            vol.Required(
                CONF_COMMUNITY,
                default=defaults.get(CONF_COMMUNITY, DEFAULT_COMMUNITY),
            ): selector.TextSelector(),
            vol.Required(
                CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=65535, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10, max=3600, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_TIMEOUT, default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=30, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_RETRIES, default=defaults.get(CONF_RETRIES, DEFAULT_RETRIES)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=5, mode=selector.NumberSelectorMode.BOX
                )
            ),
        }
    )


def _options_schema(defaults: dict[str, Any]) -> vol.Schema:
    base = dict(_base_schema(defaults).schema)
    base[
        vol.Optional(
            CONF_MANUAL_LINKS, default=defaults.get(CONF_MANUAL_LINKS, "")
        )
    ] = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
    return vol.Schema(base)


def _normalize_targets(raw_targets: str) -> list[str]:
    return [
        item.strip() for item in raw_targets.replace("\n", ",").split(",") if item.strip()
    ]


class NetWalkerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NetWalker."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            if not _normalize_targets(user_input[CONF_SCAN_TARGETS]):
                errors[CONF_SCAN_TARGETS] = "no_targets"
            if not errors:
                await self.async_set_unique_id(user_input[CONF_TITLE].strip().lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_TITLE],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_base_schema(user_input or {}),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return NetWalkerOptionsFlow(config_entry)


class NetWalkerOptionsFlow(config_entries.OptionsFlow):
    """Handle integration options."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        defaults = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            if not _normalize_targets(user_input[CONF_SCAN_TARGETS]):
                errors[CONF_SCAN_TARGETS] = "no_targets"
            if not errors:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=user_input[CONF_TITLE],
                )
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(user_input or defaults),
            errors=errors,
        )
