"""NetWalker Home Assistant integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, service

from .const import DOMAIN, PLATFORMS
from .coordinator import NetWalkerCoordinator, NetWalkerRuntime
from .http_api import NetWalkerEntriesView, NetWalkerTopologyView
from .panel import async_register_panel

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration domain."""
    async def _async_handle_refresh_service(call: ServiceCall) -> None:
        """Refresh one or all configured topology coordinators."""
        entry_id = call.data.get("entry_id")
        runtimes = hass.data.get(DOMAIN, {})
        if entry_id:
            runtime = runtimes.get(entry_id)
            if runtime is None:
                _LOGGER.warning("Refresh requested for unknown entry_id %s", entry_id)
                return
            await runtime.coordinator.async_request_refresh()
            return

        for runtime in runtimes.values():
            await runtime.coordinator.async_request_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.http.register_view(NetWalkerTopologyView(hass))
    hass.http.register_view(NetWalkerEntriesView(hass))
    await async_register_panel(hass)
    service.async_register_admin_service(
        hass,
        DOMAIN,
        "refresh",
        _async_handle_refresh_service,
        schema=vol.Schema({vol.Optional("entry_id"): cv.string}),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up NetWalker from a config entry."""
    coordinator = NetWalkerCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = NetWalkerRuntime(coordinator=coordinator)

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry after option changes."""
    await hass.config_entries.async_reload(entry.entry_id)
