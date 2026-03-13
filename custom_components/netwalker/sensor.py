"""Sensor platform for NetWalker."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import DOMAIN
from .entity import NetWalkerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id].coordinator
    known_entities: set[tuple[str, str]] = set()

    @callback
    def _sync_entities() -> None:
        new_entities: list[SensorEntity] = []
        for device_id in coordinator.data.devices:
            for entity_cls in (
                DeviceUptimeSensor,
                DeviceModelSensor,
                DeviceVersionSensor,
                DeviceWirelessClientsSensor,
                DevicePoePortsSensor,
            ):
                key = (device_id, entity_cls.entity_key)
                if key in known_entities:
                    continue
                known_entities.add(key)
                new_entities.append(entity_cls(coordinator, device_id))
        if new_entities:
            async_add_entities(new_entities)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class _BaseDeviceSensor(NetWalkerEntity, SensorEntity):
    """Base sensor class for a discovered device."""

    entity_key = "base"

    @property
    def unique_id(self) -> str:
        return (
            f"{self.coordinator.config_entry.entry_id}_"
            f"{self._device_id}_{self.entity_key}"
        )


class DeviceUptimeSensor(_BaseDeviceSensor):
    """Expose device uptime."""

    entity_key = "uptime"
    _attr_translation_key = "uptime"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_suggested_display_precision = 0

    @property
    def native_value(self) -> StateType:
        ticks = self.device_snapshot.uptime_ticks
        return int(ticks / 100) if ticks is not None else None


class DeviceModelSensor(_BaseDeviceSensor):
    """Expose device model."""

    entity_key = "model"
    _attr_translation_key = "model"

    @property
    def native_value(self) -> StateType:
        return self.device_snapshot.model


class DeviceVersionSensor(_BaseDeviceSensor):
    """Expose RouterOS version."""

    entity_key = "routeros_version"
    _attr_translation_key = "routeros_version"

    @property
    def native_value(self) -> StateType:
        return self.device_snapshot.routeros_version


class DeviceWirelessClientsSensor(_BaseDeviceSensor):
    """Expose wireless client count when available."""

    entity_key = "wireless_clients"
    _attr_translation_key = "wireless_clients"

    @property
    def native_value(self) -> StateType:
        return self.device_snapshot.wireless_clients


class DevicePoePortsSensor(_BaseDeviceSensor):
    """Expose active PoE ports when available."""

    entity_key = "poe_ports_active"
    _attr_translation_key = "poe_ports_active"

    @property
    def native_value(self) -> StateType:
        return self.device_snapshot.poe_ports_active
