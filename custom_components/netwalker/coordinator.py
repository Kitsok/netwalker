"""Coordinator for NetWalker discovery and topology updates."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_COMMUNITY,
    CONF_MANUAL_LINKS,
    CONF_PORT,
    CONF_RETRIES,
    CONF_SCAN_INTERVAL,
    CONF_SCAN_TARGETS,
    CONF_TIMEOUT,
    DEFAULT_COMMUNITY,
    DOMAIN,
)
from .models import DeviceSnapshot, TopologySnapshot
from .snmp import discover_device, mark_unreachable
from .topology import build_topology

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class NetWalkerRuntime:
    """Runtime objects stored for one config entry."""

    coordinator: "NetWalkerCoordinator"


class NetWalkerCoordinator(DataUpdateCoordinator[TopologySnapshot]):
    """Coordinate SNMP polling and topology graph updates."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.config_entry = entry
        self._previous: TopologySnapshot | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=self._scan_interval),
        )

    @property
    def runtime(self) -> NetWalkerRuntime:
        return self.hass.data[DOMAIN][self.config_entry.entry_id]

    @property
    def scan_targets(self) -> list[str]:
        raw_targets = self.config_entry.options.get(
            CONF_SCAN_TARGETS, self.config_entry.data.get(CONF_SCAN_TARGETS, "")
        )
        return [item.strip() for item in raw_targets.replace("\n", ",").split(",") if item.strip()]

    @property
    def _scan_interval(self) -> int:
        return int(
            self.config_entry.options.get(
                CONF_SCAN_INTERVAL,
                self.config_entry.data.get(CONF_SCAN_INTERVAL),
            )
        )

    @property
    def _community(self) -> str:
        return str(
            self.config_entry.options.get(
                CONF_COMMUNITY,
                self.config_entry.data.get(CONF_COMMUNITY, DEFAULT_COMMUNITY),
            )
        )

    @property
    def _port(self) -> int:
        return int(
            self.config_entry.options.get(CONF_PORT, self.config_entry.data.get(CONF_PORT, 161))
        )

    @property
    def _timeout(self) -> int:
        return int(
            self.config_entry.options.get(
                CONF_TIMEOUT, self.config_entry.data.get(CONF_TIMEOUT, 3)
            )
        )

    @property
    def _retries(self) -> int:
        return int(
            self.config_entry.options.get(
                CONF_RETRIES, self.config_entry.data.get(CONF_RETRIES, 1)
            )
        )

    @property
    def _manual_links(self) -> str:
        return str(
            self.config_entry.options.get(
                CONF_MANUAL_LINKS,
                self.config_entry.data.get(CONF_MANUAL_LINKS, ""),
            )
        )

    async def _async_update_data(self) -> TopologySnapshot:
        if not self.scan_targets and self._previous is None:
            raise UpdateFailed("No scan targets configured")

        previous_by_host = {}
        if self._previous is not None:
            previous_by_host = {
                device.host: device for device in self._previous.devices.values()
            }

        async def _discover(host: str) -> DeviceSnapshot | None:
            try:
                return await discover_device(
                    host=host,
                    community=self._community,
                    port=self._port,
                    timeout=self._timeout,
                    retries=self._retries,
                )
            except Exception as err:
                _LOGGER.warning("Discovery failed for %s: %s", host, err)
                previous_device = previous_by_host.get(host)
                return mark_unreachable(previous_device) if previous_device else None

        queue = [
            host
            for host in self.scan_targets + list(previous_by_host)
            if host.strip()
        ]
        attempted: set[str] = set()
        devices_by_host: dict[str, DeviceSnapshot] = {}

        while queue and len(attempted) < 64:
            batch: list[str] = []
            while queue and len(batch) < 8:
                host = queue.pop(0)
                host_key = _host_key(host)
                if host_key in attempted:
                    continue
                attempted.add(host_key)
                batch.append(host)

            if not batch:
                continue

            results = await asyncio.gather(*(_discover(host) for host in batch))
            for discovered in results:
                if discovered is None:
                    continue

                devices_by_host[discovered.host] = discovered
                for neighbor_host in _neighbor_management_hosts(discovered):
                    neighbor_key = _host_key(neighbor_host)
                    if neighbor_key in attempted:
                        continue
                    queue.append(neighbor_host)

        devices = list(devices_by_host.values())
        if not devices:
            raise UpdateFailed("Discovery failed for all configured targets")

        snapshot = build_topology(devices, self._previous, self._manual_links)
        self._previous = snapshot
        return snapshot


def _neighbor_management_hosts(device: DeviceSnapshot) -> list[str]:
    hosts: list[str] = []
    for neighbor in device.lldp_neighbors:
        address = neighbor.remote_management_address
        if address is None:
            continue
        try:
            hosts.append(str(ipaddress.ip_address(address)))
        except ValueError:
            continue
    return hosts


def _host_key(host: str) -> str:
    return host.strip().lower()
