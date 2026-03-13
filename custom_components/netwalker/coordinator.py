"""Coordinator for NetWalker discovery and topology updates."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass
from datetime import timedelta
import re

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
    MAX_DISCOVERY_HOSTS,
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


@dataclass(slots=True)
class DiscoveryTarget:
    """One pending discovery target."""

    host: str
    strict: bool = True


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

        async def _discover(target: DiscoveryTarget) -> DeviceSnapshot | None:
            try:
                return await discover_device(
                    host=target.host,
                    community=self._community,
                    port=self._port,
                    timeout=self._timeout,
                    retries=self._retries,
                )
            except Exception as err:
                if target.strict:
                    _LOGGER.warning("Discovery failed for %s: %s", target.host, err)
                else:
                    _LOGGER.debug("Discovery probe failed for %s: %s", target.host, err)
                previous_device = previous_by_host.get(target.host)
                return mark_unreachable(previous_device) if previous_device else None

        queue = _configured_discovery_targets(self.scan_targets) + [
            DiscoveryTarget(host=host, strict=True) for host in previous_by_host if host.strip()
        ]
        attempted: set[str] = set()
        devices_by_host: dict[str, DeviceSnapshot] = {}

        while queue and len(attempted) < MAX_DISCOVERY_HOSTS:
            batch: list[DiscoveryTarget] = []
            while queue and len(batch) < 8:
                target = queue.pop(0)
                host_key = _host_key(target.host)
                if host_key in attempted:
                    continue
                attempted.add(host_key)
                batch.append(target)

            if not batch:
                continue

            results = await asyncio.gather(*(_discover(target) for target in batch))
            for discovered in results:
                if discovered is None:
                    continue

                devices_by_host[discovered.host] = discovered
                for neighbor_host in _neighbor_management_hosts(discovered):
                    neighbor_key = _host_key(neighbor_host)
                    if neighbor_key in attempted:
                        continue
                    queue.append(DiscoveryTarget(host=neighbor_host, strict=True))

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


def _configured_discovery_targets(raw_targets: list[str]) -> list[DiscoveryTarget]:
    expanded: list[DiscoveryTarget] = []
    for raw_target in raw_targets:
        expanded.extend(_expand_discovery_target(raw_target))
    return _deduplicate_targets(expanded)


def _expand_discovery_target(raw_target: str) -> list[DiscoveryTarget]:
    target = raw_target.strip()
    if not target:
        return []

    cidr_hosts = _expand_cidr_target(target)
    if cidr_hosts is not None:
        return [DiscoveryTarget(host=host, strict=False) for host in cidr_hosts]

    range_hosts = _expand_ip_range_target(target)
    if range_hosts is not None:
        return [DiscoveryTarget(host=host, strict=False) for host in range_hosts]

    return [DiscoveryTarget(host=target, strict=True)]


def _expand_cidr_target(target: str) -> list[str] | None:
    if "/" not in target:
        return None
    try:
        network = ipaddress.ip_network(target, strict=False)
    except ValueError:
        return None

    hosts = [str(address) for address in network.hosts()]
    if not hosts:
        hosts = [str(network.network_address)]
    return _limit_expanded_hosts(target, hosts)


def _expand_ip_range_target(target: str) -> list[str] | None:
    if "-" not in target:
        return None

    full_match = re.fullmatch(
        r"\s*(\d+\.\d+\.\d+\.\d+)\s*-\s*(\d+\.\d+\.\d+\.\d+)\s*", target
    )
    if full_match:
        try:
            start = ipaddress.ip_address(full_match.group(1))
            end = ipaddress.ip_address(full_match.group(2))
        except ValueError:
            return []
        if start.version != end.version or int(end) < int(start):
            return []
        hosts = [str(ipaddress.ip_address(value)) for value in range(int(start), int(end) + 1)]
        return _limit_expanded_hosts(target, hosts)

    short_match = re.fullmatch(
        r"\s*(\d+\.\d+\.\d+)\.(\d+)\s*-\s*(\d+)\s*", target
    )
    if not short_match:
        return None

    base = short_match.group(1)
    start_octet = int(short_match.group(2))
    end_octet = int(short_match.group(3))
    if (
        start_octet < 0
        or end_octet < 0
        or start_octet > 255
        or end_octet > 255
        or end_octet < start_octet
    ):
        return []
    hosts = [f"{base}.{value}" for value in range(start_octet, end_octet + 1)]
    return _limit_expanded_hosts(target, hosts)


def _limit_expanded_hosts(target: str, hosts: list[str]) -> list[str]:
    if len(hosts) <= MAX_DISCOVERY_HOSTS:
        return hosts

    _LOGGER.warning(
        "Discovery target %s expands to %s hosts; limiting to the first %s",
        target,
        len(hosts),
        MAX_DISCOVERY_HOSTS,
    )
    return hosts[:MAX_DISCOVERY_HOSTS]


def _deduplicate_targets(targets: list[DiscoveryTarget]) -> list[DiscoveryTarget]:
    deduplicated: list[DiscoveryTarget] = []
    seen: dict[str, int] = {}
    for target in targets:
        key = _host_key(target.host)
        previous_index = seen.get(key)
        if previous_index is None:
            seen[key] = len(deduplicated)
            deduplicated.append(target)
            continue
        if target.strict and not deduplicated[previous_index].strict:
            deduplicated[previous_index] = target
    return deduplicated
