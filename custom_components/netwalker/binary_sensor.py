"""Binary sensor platform for NetWalker."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import NetWalkerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id].coordinator
    known_entities: set[str] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[BinarySensorEntity] = []
        for device_id in coordinator.data.devices:
            if device_id in known_entities:
                continue
            known_entities.add(device_id)
            new_entities.append(DeviceReachabilityBinarySensor(coordinator, device_id))
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class DeviceReachabilityBinarySensor(NetWalkerEntity, BinarySensorEntity):
    """Expose device reachability."""

    _attr_translation_key = "reachable"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.config_entry.entry_id}_{self._device_id}_reachable"

    @property
    def is_on(self) -> bool | None:
        return self.device_snapshot.reachable
