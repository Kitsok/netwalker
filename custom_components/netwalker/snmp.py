"""SNMP helpers for NetWalker."""

from __future__ import annotations

import asyncio
import ipaddress
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
    lldp_rem_addr_task = asyncio.create_task(client.walk(OIDS["lldp_rem_man_addr"]))
    wl_rtab_count_task = asyncio.create_task(
        _safe_get_optional(client, OIDS["mtxr_wl_rtab_entry_count"])
    )
    wl_cmr_count_task = asyncio.create_task(
        _safe_get_optional(client, OIDS["mtxr_wl_cmr_tab_entry_count"])
    )
    wl_ap_clients_task = asyncio.create_task(
        _safe_walk_optional(client, OIDS["mtxr_wl_ap_client_count"])
    )
    wl_cm_reg_clients_task = asyncio.create_task(
        _safe_walk_optional(client, OIDS["mtxr_wl_cm_reg_client_count"])
    )
    poe_status_task = asyncio.create_task(
        _safe_walk_optional(client, OIDS["mtxr_poe_status"])
    )
    poe_power_task = asyncio.create_task(
        _safe_walk_optional(client, OIDS["mtxr_poe_power"])
    )

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
            lldp_remote_addrs,
            wl_rtab_count,
            wl_cmr_count,
            wl_ap_clients,
            wl_cm_reg_clients,
            poe_statuses,
            poe_powers,
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
            lldp_rem_addr_task,
            wl_rtab_count_task,
            wl_cmr_count_task,
            wl_ap_clients_task,
            wl_cm_reg_clients_task,
            poe_status_task,
            poe_power_task,
        )
    except Exception as err:
        _LOGGER.debug("Discovery failed for %s: %s", host, err)
        raise

    device_id = _slugify(sys_name or host)
    model, routeros_version = _parse_sys_descr(sys_descr)
    interfaces = _build_interfaces(
        if_names,
        if_aliases,
        if_states,
        if_speeds,
        if_ins,
        if_outs,
        poe_statuses,
        poe_powers,
    )
    neighbors = _build_neighbors(
        lldp_local_ports=lldp_local_ports,
        lldp_remote_names=lldp_remote_names,
        lldp_remote_ports=lldp_remote_ports,
        lldp_remote_addrs=lldp_remote_addrs,
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
        wireless_clients=_derive_wireless_clients(
            wl_rtab_count, wl_cmr_count, wl_ap_clients, wl_cm_reg_clients
        ),
        poe_ports_active=_count_active_poe_ports(poe_statuses),
    )


def mark_unreachable(device: DeviceSnapshot) -> DeviceSnapshot:
    """Preserve the last known device state while marking it unreachable."""
    return replace(device, reachable=False)


async def _safe_get_optional(client: SnmpClient, oid: str) -> str | None:
    try:
        return await client.get(oid)
    except Exception:
        return None


async def _safe_walk_optional(client: SnmpClient, oid: str) -> dict[str, str]:
    try:
        return await client.walk(oid)
    except Exception:
        return {}


def _build_interfaces(
    if_names: dict[str, str],
    if_aliases: dict[str, str],
    if_states: dict[str, str],
    if_speeds: dict[str, str],
    if_ins: dict[str, str],
    if_outs: dict[str, str],
    poe_statuses: dict[str, str],
    poe_powers: dict[str, str],
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
            poe_status=_decode_poe_status(
                poe_statuses.get(f"{OIDS['mtxr_poe_status']}.{index}")
            ),
            poe_power_watts=_decode_poe_power_watts(
                poe_powers.get(f"{OIDS['mtxr_poe_power']}.{index}")
            ),
        )
    return interfaces


def _build_neighbors(
    lldp_local_ports: dict[str, str],
    lldp_remote_names: dict[str, str],
    lldp_remote_ports: dict[str, str],
    lldp_remote_addrs: dict[str, str],
) -> list[LldpNeighbor]:
    local_port_names = {
        _oid_suffix(OIDS["lldp_loc_port_id"], oid): value
        for oid, value in lldp_local_ports.items()
    }

    remote_port_descs = {
        _remote_table_key_from_oid(OIDS["lldp_rem_port_desc"], oid): value
        for oid, value in lldp_remote_ports.items()
    }
    remote_management_addrs = {
        key: decoded
        for oid, value in lldp_remote_addrs.items()
        for key, decoded in [
            _decode_lldp_management_address(oid, value)
        ]
        if decoded is not None
    }

    neighbors: list[LldpNeighbor] = []
    for oid, remote_system_name in lldp_remote_names.items():
        remote_key = _remote_table_key_from_oid(OIDS["lldp_rem_sys_name"], oid)
        local_port_num = remote_key[1]
        neighbors.append(
            LldpNeighbor(
                local_port_num=local_port_num,
                local_interface=local_port_names.get(local_port_num, local_port_num),
                remote_system_name=remote_system_name,
                remote_interface=remote_port_descs.get(remote_key),
                remote_management_address=remote_management_addrs.get(remote_key),
            )
        )
    return neighbors


def _remote_table_key_from_oid(base_oid: str, oid: str) -> tuple[str, str, str]:
    suffix = _oid_suffix(base_oid, oid)
    parts = suffix.split(".")
    if len(parts) < 3:
        padded = parts + ["0"] * (3 - len(parts))
        return (padded[0], padded[1], padded[2])
    return (parts[0], parts[1], parts[2])


def _decode_lldp_management_address(
    oid: str, raw_value: str
) -> tuple[tuple[str, str, str], str | None]:
    parts = _oid_suffix(OIDS["lldp_rem_man_addr"], oid).split(".")
    if len(parts) < 5:
        return (_remote_table_key_from_oid(OIDS["lldp_rem_man_addr"], oid), None)

    remote_key = (parts[0], parts[1], parts[2])
    subtype = _safe_int(parts[3])
    address_length = _safe_int(parts[4])
    address_parts = parts[5 : 5 + address_length] if address_length else []

    if subtype == 1 and len(address_parts) == 4:
        return (remote_key, ".".join(address_parts))

    if subtype == 2 and len(address_parts) == 16:
        try:
            ipv6_bytes = bytes(int(part) for part in address_parts)
            return (remote_key, str(ipaddress.IPv6Address(ipv6_bytes)))
        except ValueError:
            return (remote_key, None)

    # Fall back to PySNMP's rendered value for address types we do not decode explicitly.
    if raw_value and raw_value != "0x":
        return (remote_key, raw_value)

    return (remote_key, None)


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


def _derive_wireless_clients(
    wl_rtab_count: str | None,
    wl_cmr_count: str | None,
    wl_ap_clients: dict[str, str],
    wl_cm_reg_clients: dict[str, str],
) -> int | None:
    candidates = [
        _safe_int(wl_rtab_count),
        _safe_int(wl_cmr_count),
        _sum_int_values(wl_ap_clients),
        _sum_int_values(wl_cm_reg_clients),
    ]
    present = [value for value in candidates if value is not None]
    return max(present) if present else None


def _count_active_poe_ports(poe_statuses: dict[str, str]) -> int | None:
    if not poe_statuses:
        return None
    return sum(1 for value in poe_statuses.values() if _safe_int(value) == 3)


def _sum_int_values(values: dict[str, str]) -> int | None:
    if not values:
        return None
    parsed = [_safe_int(value) for value in values.values()]
    present = [value for value in parsed if value is not None]
    return sum(present) if present else None


def _decode_poe_status(value: str | None) -> str | None:
    mapping = {
        "1": "disabled",
        "2": "waiting_for_load",
        "3": "powered_on",
        "4": "overload",
        "5": "short_circuit",
        "6": "voltage_too_low",
        "7": "current_too_low",
        "8": "power_reset",
        "9": "voltage_too_high",
        "10": "controller_error",
        "11": "controller_upgrade",
        "12": "poe_in_detected",
        "13": "no_valid_psu",
        "14": "controller_init",
        "15": "low_voltage_too_low",
    }
    return mapping.get(value, value)


def _decode_poe_power_watts(value: str | None) -> float | None:
    raw = _safe_int(value)
    if raw is None:
        return None
    return raw / 10


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
