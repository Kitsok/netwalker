"""SNMP helpers for NetWalker."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field, replace

from .const import OIDS
from .models import DeviceSnapshot, InterfaceSnapshot, LldpNeighbor

_LOGGER = logging.getLogger(__name__)

try:
    from pysnmp.hlapi.v3arch.asyncio import (
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        get_cmd,
        walk_cmd,
    )
except ImportError:  # pragma: no cover - runtime dependency
    CommunityData = ContextData = ObjectIdentity = ObjectType = None
    SnmpEngine = UdpTransportTarget = get_cmd = walk_cmd = None


class NetWalkerSnmpError(RuntimeError):
    """Raised when an SNMP request fails."""


@dataclass(slots=True)
class SnmpClient:
    """Minimal SNMPv2c client wrapper."""

    host: str
    community: str
    port: int
    timeout: int
    retries: int
    _engine: object | None = field(default=None, init=False, repr=False)
    _engine_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def get(self, oid: str) -> str:
        """Get a scalar OID value."""
        self._require_runtime()
        engine = await self._get_engine()
        target = await UdpTransportTarget.create(
            (self.host, self.port), timeout=self.timeout, retries=self.retries
        )
        error_indication, error_status, error_index, var_binds = await get_cmd(
            engine,
            CommunityData(self.community, mpModel=1),
            target,
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lookupMib=False,
        )
        if error_indication or error_status:
            raise NetWalkerSnmpError(
                f"SNMP get failed for {self.host} {oid}: "
                f"{error_indication or error_status.prettyPrint()}"
            )
        return var_binds[0][1].prettyPrint()

    async def walk(self, oid: str) -> dict[str, str]:
        """Walk a subtree and return value mapping keyed by full OID."""
        self._require_runtime()
        engine = await self._get_engine()
        target = await UdpTransportTarget.create(
            (self.host, self.port), timeout=self.timeout, retries=self.retries
        )
        result: dict[str, str] = {}
        async for error_indication, error_status, error_index, var_binds in walk_cmd(
            engine,
            CommunityData(self.community, mpModel=1),
            target,
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
            lookupMib=False,
        ):
            if error_indication or error_status:
                raise NetWalkerSnmpError(
                    f"SNMP walk failed for {self.host} {oid}: "
                    f"{error_indication or error_status.prettyPrint()}"
                )
            for name, value in var_binds:
                result[str(name)] = value.prettyPrint()
        return result

    @staticmethod
    def _require_runtime() -> None:
        if get_cmd is None:
            raise NetWalkerSnmpError(
                "pysnmp is not available; install integration requirements first"
            )

    async def _get_engine(self):
        """Create the PySNMP engine off the event loop and reuse it."""
        if self._engine is not None:
            return self._engine

        async with self._engine_lock:
            if self._engine is None:
                self._engine = await asyncio.to_thread(SnmpEngine)

        return self._engine


async def discover_device(
    host: str,
    community: str,
    port: int,
    timeout: int,
    retries: int,
) -> DeviceSnapshot:
    """Discover one device via SNMP."""
    client = SnmpClient(
        host=host,
        community=community,
        port=port,
        timeout=timeout,
        retries=retries,
    )

    sys_name_task = asyncio.create_task(client.get(OIDS["sys_name"]))
    sys_descr_task = asyncio.create_task(client.get(OIDS["sys_descr"]))
    sys_uptime_task = asyncio.create_task(client.get(OIDS["sys_uptime"]))
    if_name_task = asyncio.create_task(client.walk(OIDS["if_name"]))
    if_alias_task = asyncio.create_task(client.walk(OIDS["if_alias"]))
    if_state_task = asyncio.create_task(client.walk(OIDS["if_oper_status"]))
    if_speed_task = asyncio.create_task(client.walk(OIDS["if_high_speed"]))
    if_in_task = asyncio.create_task(client.walk(OIDS["if_in_octets"]))
    if_out_task = asyncio.create_task(client.walk(OIDS["if_out_octets"]))
    lldp_loc_task = asyncio.create_task(client.walk(OIDS["lldp_loc_port_id"]))
    lldp_rem_name_task = asyncio.create_task(client.walk(OIDS["lldp_rem_sys_name"]))
    lldp_rem_port_task = asyncio.create_task(client.walk(OIDS["lldp_rem_port_desc"]))

    try:
        (
            sys_name,
            sys_descr,
            sys_uptime,
            if_names,
            if_aliases,
            if_states,
            if_speeds,
            if_ins,
            if_outs,
            lldp_local_ports,
            lldp_remote_names,
            lldp_remote_ports,
        ) = await asyncio.gather(
            sys_name_task,
            sys_descr_task,
            sys_uptime_task,
            if_name_task,
            if_alias_task,
            if_state_task,
            if_speed_task,
            if_in_task,
            if_out_task,
            lldp_loc_task,
            lldp_rem_name_task,
            lldp_rem_port_task,
        )
    except Exception as err:
        _LOGGER.debug("Discovery failed for %s: %s", host, err)
        raise

    device_id = _slugify(sys_name or host)
    model, routeros_version = _parse_sys_descr(sys_descr)
    interfaces = _build_interfaces(
        if_names, if_aliases, if_states, if_speeds, if_ins, if_outs
    )
    neighbors = _build_neighbors(
        lldp_local_ports=lldp_local_ports,
        lldp_remote_names=lldp_remote_names,
        lldp_remote_ports=lldp_remote_ports,
    )

    return DeviceSnapshot(
        host=host,
        device_id=device_id,
        sys_name=sys_name,
        sys_descr=sys_descr,
        uptime_ticks=int(sys_uptime) if sys_uptime.isdigit() else None,
        model=model,
        routeros_version=routeros_version,
        reachable=True,
        interfaces=interfaces,
        lldp_neighbors=neighbors,
    )


def mark_unreachable(device: DeviceSnapshot) -> DeviceSnapshot:
    """Preserve the last known device state while marking it unreachable."""
    return replace(device, reachable=False)


def _build_interfaces(
    if_names: dict[str, str],
    if_aliases: dict[str, str],
    if_states: dict[str, str],
    if_speeds: dict[str, str],
    if_ins: dict[str, str],
    if_outs: dict[str, str],
) -> dict[str, InterfaceSnapshot]:
    interfaces: dict[str, InterfaceSnapshot] = {}
    for oid, name in if_names.items():
        index = _oid_suffix(OIDS["if_name"], oid)
        interfaces[index] = InterfaceSnapshot(
            index=index,
            name=name,
            alias=if_aliases.get(f"{OIDS['if_alias']}.{index}"),
            oper_status=_decode_if_oper_status(
                if_states.get(f"{OIDS['if_oper_status']}.{index}")
            ),
            speed_mbps=_safe_int(if_speeds.get(f"{OIDS['if_high_speed']}.{index}")),
            in_octets=_safe_int(if_ins.get(f"{OIDS['if_in_octets']}.{index}")),
            out_octets=_safe_int(if_outs.get(f"{OIDS['if_out_octets']}.{index}")),
        )
    return interfaces


def _build_neighbors(
    lldp_local_ports: dict[str, str],
    lldp_remote_names: dict[str, str],
    lldp_remote_ports: dict[str, str],
) -> list[LldpNeighbor]:
    local_port_names = {
        _oid_suffix(OIDS["lldp_loc_port_id"], oid): value
        for oid, value in lldp_local_ports.items()
    }

    remote_port_descs = {
        _remote_key_from_oid(oid): value for oid, value in lldp_remote_ports.items()
    }

    neighbors: list[LldpNeighbor] = []
    for oid, remote_system_name in lldp_remote_names.items():
        remote_key = _remote_key_from_oid(oid)
        local_port_num = remote_key[0]
        neighbors.append(
            LldpNeighbor(
                local_port_num=local_port_num,
                local_interface=local_port_names.get(local_port_num, local_port_num),
                remote_system_name=remote_system_name,
                remote_interface=remote_port_descs.get(remote_key),
            )
        )
    return neighbors


def _remote_key_from_oid(oid: str) -> tuple[str, str]:
    parts = oid.split(".")
    if len(parts) < 2:
        return (oid, "0")
    return (parts[-2], parts[-1])


def _oid_suffix(base_oid: str, full_oid: str) -> str:
    prefix = f"{base_oid}."
    return full_oid[len(prefix) :] if full_oid.startswith(prefix) else full_oid


def _decode_if_oper_status(raw_value: str | None) -> str | None:
    mapping = {
        "1": "up",
        "2": "down",
        "3": "testing",
        "4": "unknown",
        "5": "dormant",
        "6": "not_present",
        "7": "lower_layer_down",
    }
    return mapping.get(raw_value, raw_value)


def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_sys_descr(sys_descr: str) -> tuple[str | None, str | None]:
    model: str | None = None
    version: str | None = None

    model_before_version = re.search(
        r"RouterOS\s+([A-Za-z0-9.+_-]+)\s+([0-9]+(?:\.[0-9A-Za-z_-]+)+)",
        sys_descr,
    )
    if model_before_version:
        model = model_before_version.group(1)
        version = model_before_version.group(2)

    if version is None:
        version_match = re.search(r"\b([0-9]+(?:\.[0-9A-Za-z_-]+)+)\b", sys_descr)
        version = version_match.group(1) if version_match else None

    if model is None:
        version_before_model = re.search(
            r"RouterOS\s+[0-9]+(?:\.[0-9A-Za-z_-]+)+\s+\(([^)]+)\)",
            sys_descr,
        )
        if version_before_model:
            model = version_before_model.group(1)

    if model is None:
        generic_routeros = re.search(r"RouterOS\s+([A-Za-z0-9.+_-]+)", sys_descr)
        if generic_routeros:
            candidate = generic_routeros.group(1)
            if not re.match(r"^[0-9]", candidate):
                model = candidate

    return (model, version)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
