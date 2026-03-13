"""HTTP API for the NetWalker panel."""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN


class NetWalkerTopologyView(HomeAssistantView):
    """Expose the current topology to the panel frontend."""

    url = "/api/netwalker/topology/{entry_id}"
    name = "api:netwalker:topology"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        runtime = self.hass.data[DOMAIN].get(entry_id)
        if runtime is None:
            return self.json_message("Unknown config entry", status_code=404)
        return self.json(runtime.coordinator.data.as_dict())


class NetWalkerEntriesView(HomeAssistantView):
    """Expose configured NetWalker entries to the panel frontend."""

    url = "/api/netwalker/entries"
    name = "api:netwalker:entries"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        entries = []
        for entry_id, runtime in self.hass.data.get(DOMAIN, {}).items():
            entries.append(
                {
                    "entry_id": entry_id,
                    "title": runtime.coordinator.config_entry.title,
                }
            )
        entries.sort(key=lambda item: item["title"].lower())
        return self.json({"entries": entries})
