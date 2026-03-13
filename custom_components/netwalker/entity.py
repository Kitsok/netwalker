"""Shared entity helpers for NetWalker."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import NetWalkerCoordinator


class NetWalkerEntity(CoordinatorEntity[NetWalkerCoordinator]):
    """Base entity bound to a discovered device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NetWalkerCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id

    @property
    def device_snapshot(self):
        return self.coordinator.data.devices[self._device_id]

    @property
    def device_info(self) -> dict:
        device = self.device_snapshot
        return {
            "identifiers": {(self.coordinator.config_entry.domain, self._device_id)},
            "name": device.display_name,
            "manufacturer": "MikroTik",
            "model": device.model,
            "sw_version": device.routeros_version,
            "configuration_url": f"http://{device.host}",
        }

    @property
    def extra_state_attributes(self) -> dict:
        device = self.device_snapshot
        return {
            "host": device.host,
            "sys_descr": device.sys_descr,
            "interfaces": sorted(
                (
                    {
                        "index": interface.index,
                        "name": interface.name,
                        "alias": interface.alias,
                        "oper_status": interface.oper_status,
                        "speed_mbps": interface.speed_mbps,
                        "rx_bps": interface.rx_bps,
                        "tx_bps": interface.tx_bps,
                    }
                    for interface in device.interfaces.values()
                ),
                key=lambda item: item["name"],
            ),
        }
