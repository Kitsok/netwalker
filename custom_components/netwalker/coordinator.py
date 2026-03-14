"""Coordinator for NetWalker discovery and topology updates."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass
from datetime import timedelta
import re
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store
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
        self._known_hosts: list[str] = []
        self._store: Store[dict[str, list[str]]] = Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}"
        )
        self._discovery_lock = asyncio.Lock()
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=self._scan_interval),
        )

    async def async_initialize(self) -> None:
        """Load persisted discovery state."""
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            hosts = stored.get("known_hosts", [])
            if isinstance(hosts, list):
                self._known_hosts = _deduplicate_hosts(
                    [str(host) for host in hosts if str(host).strip()]
                )

        if self._known_hosts:
            return

        self._known_hosts = self._seed_known_hosts_from_device_registry()
        if self._known_hosts:
            await self._store.async_save({"known_hosts": self._known_hosts})

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
        poll_hosts = self._poll_hosts()
        if not poll_hosts:
            empty = self._previous or TopologySnapshot()
            self._previous = empty
            return empty

        devices = await self._poll_host_batch(poll_hosts)
        if not devices:
            if self._previous is not None:
                return self._previous
            raise UpdateFailed("Polling failed for all known targets")

        self._remember_known_hosts(devices)
        snapshot = build_topology(devices, self._previous, self._manual_links)
        self._previous = snapshot
        return snapshot

    async def async_discover(self) -> TopologySnapshot:
        """Run an explicit discovery pass from configured targets."""
        async with self._discovery_lock:
            targets = _configured_discovery_targets(self.scan_targets) + [
                DiscoveryTarget(host=host, strict=True) for host in self._known_hosts
            ]
            targets = _deduplicate_targets(targets)
            devices = await self._discover_targets(targets)
            if not devices:
                if self._previous is not None:
                    return self._previous
                raise UpdateFailed("Discovery failed for all configured targets")

            self._remember_known_hosts(devices)
            snapshot = build_topology(devices, self._previous, self._manual_links)
            self._previous = snapshot
            self.async_set_updated_data(snapshot)
            return snapshot

    def _poll_hosts(self) -> list[str]:
        hosts = self._known_hosts + _configured_literal_hosts(self.scan_targets)
        if self._previous is not None:
            hosts.extend(device.host for device in self._previous.devices.values())
        return _deduplicate_hosts(hosts)

    async def _poll_host_batch(self, hosts: list[str]) -> list[DeviceSnapshot]:
        previous_by_host = self._previous_by_host()

        async def _poll(host: str) -> DeviceSnapshot | None:
            try:
                return await discover_device(
                    host=host,
                    community=self._community,
                    port=self._port,
                    timeout=self._timeout,
                    retries=self._retries,
                )
            except Exception as err:
                _LOGGER.debug("Polling failed for %s: %s", host, err)
                previous_device = previous_by_host.get(host)
                return mark_unreachable(previous_device) if previous_device else None

        devices: dict[str, DeviceSnapshot] = {}
        queue = list(hosts)
        while queue:
            batch: list[str] = []
            while queue and len(batch) < 8:
                batch.append(queue.pop(0))
            results = await asyncio.gather(*(_poll(host) for host in batch))
            for discovered in results:
                if discovered is not None:
                    devices[discovered.host] = discovered

        return list(devices.values())

    async def _discover_targets(
        self, initial_targets: list[DiscoveryTarget]
    ) -> list[DeviceSnapshot]:
        previous_by_host = self._previous_by_host()

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

        queue = list(initial_targets)
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
        return devices

    def _previous_by_host(self) -> dict[str, DeviceSnapshot]:
        if self._previous is None:
            return {}
        return {device.host: device for device in self._previous.devices.values()}

    def _remember_known_hosts(self, devices: list[DeviceSnapshot]) -> None:
        hosts = self._known_hosts + [device.host for device in devices if device.reachable]
        hosts += _configured_literal_hosts(self.scan_targets)
        deduplicated = _deduplicate_hosts(hosts)
        if deduplicated == self._known_hosts:
            return
        self._known_hosts = deduplicated
        self.hass.async_create_task(
            self._store.async_save({"known_hosts": self._known_hosts})
        )

    def _seed_known_hosts_from_device_registry(self) -> list[str]:
        registry = dr.async_get(self.hass)
        hosts: list[str] = []
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            if not device.configuration_url:
                continue
            parsed = urlparse(device.configuration_url)
            if parsed.hostname:
                hosts.append(parsed.hostname)
        return _deduplicate_hosts(hosts)


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


def _configured_literal_hosts(raw_targets: list[str]) -> list[str]:
    hosts: list[str] = []
    for raw_target in raw_targets:
        target = raw_target.strip()
        if not target:
            continue
        if _expand_cidr_target(target) is not None:
            continue
        if _expand_ip_range_target(target) is not None:
            continue
        hosts.append(target)
    return _deduplicate_hosts(hosts)


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


def _deduplicate_hosts(hosts: list[str]) -> list[str]:
    deduplicated: list[str] = []
    seen: set[str] = set()
    for host in hosts:
        key = _host_key(host)
        if not key or key in seen:
            continue
        seen.add(key)
        deduplicated.append(host)
    return deduplicated
