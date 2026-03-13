"""Register the NetWalker Home Assistant panel."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import (
    PANEL_FILENAME,
    PANEL_MODULE_NAME,
    PANEL_STATIC_URL,
    PANEL_URL_PATH,
)

_PANEL_DIR = Path(__file__).parent / "panel"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register the panel static asset and sidebar entry."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"{PANEL_STATIC_URL}/{PANEL_FILENAME}",
                str(_PANEL_DIR / PANEL_FILENAME),
                cache_headers=False,
            )
        ]
    )
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_MODULE_NAME,
        frontend_url_path=PANEL_URL_PATH,
        module_url=f"{PANEL_STATIC_URL}/{PANEL_FILENAME}",
        sidebar_title="NetWalker",
        sidebar_icon="mdi:graph-outline",
        require_admin=False,
    )
