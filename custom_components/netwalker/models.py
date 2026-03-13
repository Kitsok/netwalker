"""Typed models used by NetWalker."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class InterfaceSnapshot:
    """Interface data gathered from SNMP."""

    index: str
    name: str
    alias: str | None = None
    oper_status: str | None = None
    speed_mbps: int | None = None
    in_octets: int | None = None
    out_octets: int | None = None
    rx_bps: float | None = None
    tx_bps: float | None = None
    poe_status: str | None = None
    poe_power_watts: float | None = None


@dataclass(slots=True)
class LldpNeighbor:
    """LLDP neighbor observed on a local interface."""

    local_port_num: str
    local_interface: str
    remote_system_name: str
    remote_interface: str | None = None
    remote_management_address: str | None = None


@dataclass(slots=True)
class DeviceSnapshot:
    """Device model for one discovery pass."""

    host: str
    device_id: str
    sys_name: str
    sys_descr: str
    uptime_ticks: int | None
    model: str | None
    routeros_version: str | None
    reachable: bool
    interfaces: dict[str, InterfaceSnapshot] = field(default_factory=dict)
    lldp_neighbors: list[LldpNeighbor] = field(default_factory=list)
    wireless_clients: int | None = None
    poe_ports_active: int | None = None

    @property
    def display_name(self) -> str:
        return self.sys_name or self.host


@dataclass(slots=True)
class LinkSnapshot:
    """A normalized link between two discovered devices."""

    source_device_id: str
    source_device_name: str
    source_interface: str
    target_device_id: str
    target_device_name: str
    target_interface: str | None
    state: str
    forward_bps: float | None = None
    reverse_bps: float | None = None


@dataclass(slots=True)
class TopologySnapshot:
    """Complete topology payload exposed to Home Assistant and the panel."""

    devices: dict[str, DeviceSnapshot] = field(default_factory=dict)
    links: list[LinkSnapshot] = field(default_factory=list)
    updated_at: str | None = None

    def as_dict(self) -> dict:
        """Convert the snapshot into a JSON-serializable payload."""
        return {
            "updated_at": self.updated_at,
            "devices": [
                {
                    "id": device.device_id,
                    "host": device.host,
                    "name": device.display_name,
                    "sys_descr": device.sys_descr,
                    "model": device.model,
                    "routeros_version": device.routeros_version,
                    "uptime_ticks": device.uptime_ticks,
                    "reachable": device.reachable,
                    "wireless_clients": device.wireless_clients,
                    "poe_ports_active": device.poe_ports_active,
                    "interfaces": [
                        {
                            "index": iface.index,
                            "name": iface.name,
                            "alias": iface.alias,
                            "oper_status": iface.oper_status,
                            "speed_mbps": iface.speed_mbps,
                            "rx_bps": iface.rx_bps,
                            "tx_bps": iface.tx_bps,
                            "poe_status": iface.poe_status,
                            "poe_power_watts": iface.poe_power_watts,
                        }
                        for iface in sorted(
                            device.interfaces.values(), key=lambda item: item.name
                        )
                    ],
                }
                for device in sorted(
                    self.devices.values(), key=lambda item: item.display_name.lower()
                )
            ],
            "links": [
                {
                    "source_device_id": link.source_device_id,
                    "source_device_name": link.source_device_name,
                    "source_interface": link.source_interface,
                    "target_device_id": link.target_device_id,
                    "target_device_name": link.target_device_name,
                    "target_interface": link.target_interface,
                    "state": link.state,
                    "forward_bps": link.forward_bps,
                    "reverse_bps": link.reverse_bps,
                }
                for link in self.links
            ],
        }
