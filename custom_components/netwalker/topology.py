"""Topology graph builder."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime

from .models import DeviceSnapshot, LinkSnapshot, TopologySnapshot


def build_topology(
    devices: Iterable[DeviceSnapshot],
    previous: TopologySnapshot | None,
    manual_links_json: str | None,
) -> TopologySnapshot:
    """Build a normalized topology snapshot."""
    now = datetime.now(UTC)
    interval_seconds = _elapsed_seconds(previous, now)
    device_map = {device.device_id: device for device in devices}
    name_map = {device.display_name.lower(): device for device in devices}
    host_map = {device.host.lower(): device for device in devices}
    previous_devices = previous.devices if previous else {}
    links_by_key: dict[tuple[str, str, str, str], LinkSnapshot] = {}

    for device in device_map.values():
        _populate_rates(device, previous_devices.get(device.device_id), interval_seconds)
        for neighbor in device.lldp_neighbors:
            remote = _resolve_remote_device(neighbor, host_map, name_map)
            if remote is None:
                continue
            if remote.device_id == device.device_id:
                continue
            reciprocal = _find_reciprocal_neighbor(device, neighbor, remote)
            if reciprocal is None:
                continue
            if device.device_id > remote.device_id:
                continue
            target_interface = neighbor.remote_interface or reciprocal.local_interface
            key = _link_key(
                device.device_id,
                neighbor.local_interface,
                remote.device_id,
                target_interface or "",
            )
            source_iface = _find_interface(device, neighbor.local_interface)
            target_iface = _find_interface(remote, target_interface)
            links_by_key[key] = LinkSnapshot(
                source_device_id=device.device_id,
                source_device_name=device.display_name,
                source_interface=neighbor.local_interface,
                target_device_id=remote.device_id,
                target_device_name=remote.display_name,
                target_interface=target_interface,
                state=_derive_link_state(source_iface, target_iface),
                forward_bps=source_iface.tx_bps if source_iface else None,
                reverse_bps=target_iface.tx_bps if target_iface else None,
            )

    for manual_link in _load_manual_links(manual_links_json):
        source = name_map.get(manual_link["source"].lower())
        target = name_map.get(manual_link["target"].lower())
        if not source or not target:
            continue
        key = _link_key(
            source.device_id,
            manual_link["source_interface"],
            target.device_id,
            manual_link.get("target_interface") or "",
        )
        source_iface = _find_interface(source, manual_link["source_interface"])
        target_iface = _find_interface(target, manual_link.get("target_interface"))
        links_by_key[key] = LinkSnapshot(
            source_device_id=source.device_id,
            source_device_name=source.display_name,
            source_interface=manual_link["source_interface"],
            target_device_id=target.device_id,
            target_device_name=target.display_name,
            target_interface=manual_link.get("target_interface"),
            state=_derive_link_state(source_iface, target_iface),
            forward_bps=source_iface.tx_bps if source_iface else None,
            reverse_bps=target_iface.tx_bps if target_iface else None,
        )

    return TopologySnapshot(
        devices=device_map,
        links=sorted(
            links_by_key.values(),
            key=lambda link: (
                link.source_device_name.lower(),
                link.source_interface.lower(),
                link.target_device_name.lower(),
            ),
        ),
        updated_at=now.isoformat(),
    )


def _populate_rates(
    current: DeviceSnapshot,
    previous: DeviceSnapshot | None,
    interval_seconds: float,
) -> None:
    if previous is None or interval_seconds <= 0:
        return

    for index, iface in current.interfaces.items():
        old_iface = previous.interfaces.get(index)
        if old_iface is None:
            continue
        iface.rx_bps = _rate_per_second(
            old_iface.in_octets, iface.in_octets, interval_seconds
        )
        iface.tx_bps = _rate_per_second(
            old_iface.out_octets, iface.out_octets, interval_seconds
        )


def _rate_per_second(
    previous_value: int | None, current_value: int | None, interval_seconds: float
) -> float | None:
    if (
        previous_value is None
        or current_value is None
        or current_value < previous_value
        or interval_seconds <= 0
    ):
        return None
    delta_bytes = current_value - previous_value
    return float(delta_bytes * 8 / interval_seconds)


def _find_interface(device: DeviceSnapshot, name: str | None):
    if name is None:
        return None
    for interface in device.interfaces.values():
        if interface.name == name:
            return interface
    return None


def _resolve_remote_device(neighbor, host_map, name_map):
    if neighbor.remote_management_address:
        remote = host_map.get(neighbor.remote_management_address.lower())
        if remote is not None:
            return remote
    return name_map.get(neighbor.remote_system_name.lower())


def _find_reciprocal_neighbor(source, neighbor, remote):
    candidates = []
    for remote_neighbor in remote.lldp_neighbors:
        if not _neighbor_points_to_device(remote_neighbor, source):
            continue
        score = _interface_match_score(neighbor, remote_neighbor)
        candidates.append((score, remote_neighbor))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best_neighbor = candidates[0]
    if best_score > 0:
        return best_neighbor

    source_candidates = [
        source_neighbor
        for source_neighbor in source.lldp_neighbors
        if _resolve_neighbor_key(source_neighbor) == _resolve_neighbor_key(neighbor)
    ]
    if len(source_candidates) == 1 and len(candidates) == 1:
        return best_neighbor

    return None


def _neighbor_points_to_device(neighbor, device) -> bool:
    if neighbor.remote_management_address:
        if neighbor.remote_management_address.lower() == device.host.lower():
            return True
    return neighbor.remote_system_name.lower() == device.display_name.lower()


def _interface_match_score(left_neighbor, right_neighbor) -> int:
    score = 0

    left_remote = _normalize_interface_name(left_neighbor.remote_interface)
    left_local = _normalize_interface_name(left_neighbor.local_interface)
    right_remote = _normalize_interface_name(right_neighbor.remote_interface)
    right_local = _normalize_interface_name(right_neighbor.local_interface)

    if left_remote and right_local:
        if left_remote == right_local:
            score += 2
        elif left_remote in right_local or right_local in left_remote:
            score += 1

    if right_remote and left_local:
        if right_remote == left_local:
            score += 2
        elif right_remote in left_local or left_local in right_remote:
            score += 1

    return score


def _normalize_interface_name(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _resolve_neighbor_key(neighbor) -> tuple[str, str]:
    return (
        (neighbor.remote_management_address or "").lower(),
        neighbor.remote_system_name.lower(),
    )


def _derive_link_state(source_iface, target_iface) -> str:
    states = {
        state
        for state in (
            source_iface.oper_status if source_iface else None,
            target_iface.oper_status if target_iface else None,
        )
        if state
    }
    if not states:
        return "unknown"
    if states == {"up"}:
        return "up"
    if "down" in states or "lower_layer_down" in states:
        return "down"
    return sorted(states)[0]


def _link_key(
    source_device_id: str,
    source_interface: str,
    target_device_id: str,
    target_interface: str,
) -> tuple[str, str, str, str]:
    left = (source_device_id, source_interface)
    right = (target_device_id, target_interface)
    if left <= right:
        return (left[0], left[1], right[0], right[1])
    return (right[0], right[1], left[0], left[1])


def _load_manual_links(raw_json: str | None) -> list[dict[str, str]]:
    if not raw_json:
        return []
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _elapsed_seconds(previous: TopologySnapshot | None, now: datetime) -> float:
    if previous is None or previous.updated_at is None:
        return 0
    try:
        previous_time = datetime.fromisoformat(previous.updated_at)
    except ValueError:
        return 0
    return max((now - previous_time).total_seconds(), 0)
