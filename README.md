# NetWalker

NetWalker is a Home Assistant custom integration for discovering MikroTik devices over SNMP, building a topology graph from LLDP and interface data, exposing device entities, and rendering an interactive network map inside Home Assistant.

Repository URL: `https://github.com/Kitsok/netwalker`

Current version: `0.6.4`

## Table of contents

- [First-version scope](#first-version-scope)
- [UI-only configuration](#ui-only-configuration)
- [Install in Home Assistant](#install-in-home-assistant)
- [Use in Home Assistant](#use-in-home-assistant)
- [Enable SNMP on MikroTik](#enable-snmp-on-mikrotik)
- [Repository layout](#repository-layout)
- [Notes](#notes)

This repository is intentionally structured as a HACS custom integration, not a Home Assistant add-on. HACS can install integrations and frontend assets, but it does not install Supervisor add-ons.

## First-version scope

- UI-only configuration with Home Assistant config flow and options flow
- SNMPv2c polling
- Discovery targets entered in the web UI for explicit discovery runs
- Host, CIDR, and IPv4 range expansion during manual discovery
- Polling of known nodes on the normal interval without rescanning the network
- LLDP management-address expansion from discovered devices during manual discovery
- Device discovery using standard SNMP system and interface tables
- Link inference from LLDP plus optional manual UI overrides
- Home Assistant entities and devices
- Built-in Home Assistant panel for the interactive topology map
- Admin services `netwalker.refresh` for immediate polling and `netwalker.discover` for explicit discovery

## UI-only configuration

No YAML is required. All configuration is stored in Home Assistant config entries:

- title
- discovery targets
- support for single hosts, CIDR subnets, and IPv4 ranges
- manual discovery from those targets
- automatic expansion to LLDP neighbors that expose management IPs during discovery
- SNMP community
- polling interval
- retries and timeouts
- manual link overrides as JSON entered in the options flow

The first version keeps manual overrides in the web UI as JSON text. That satisfies the no-filesystem-editing requirement, but it should be replaced with a proper visual link editor in a later pass.

## Install in Home Assistant

### Option 1: HACS custom repository

1. In Home Assistant, open HACS.
2. Open the menu in the top right and choose `Custom repositories`.
3. Add repository URL `https://github.com/Kitsok/netwalker`.
4. Select category `Integration`.
5. Search for `NetWalker` in HACS and install it.
6. Restart Home Assistant.
7. Open `Settings` -> `Devices & services`.
8. Click `Add integration`.
9. Search for `NetWalker`.
10. Enter:
    - instance name
    - discovery targets, one per line or comma-separated
    - accepted formats: single host, CIDR subnet like `192.168.1.0/24`, or IPv4 range like `192.168.1.10-30`
    - SNMP community
    - SNMP port
    - polling interval
    - timeout
    - retries
11. Submit the form.

After setup, Home Assistant will create discovered devices and entities, and the `NetWalker` sidebar panel will appear automatically.
Configured discovery targets are used only when you run manual discovery.
Normal scheduled polling refreshes already known nodes and rebuilds the
topology without rescanning the full target list.

### Option 2: Manual install

1. Copy [custom_components/netwalker](/home/kitsok/home/netwalker/custom_components/netwalker) into your Home Assistant config directory under `custom_components/netwalker`.
2. Restart Home Assistant.
3. Open `Settings` -> `Devices & services`.
4. Click `Add integration`.
5. Search for `NetWalker` and complete the same setup form described above.

## Use in Home Assistant

### Devices and entities

- Each discovered MikroTik appears as a Home Assistant device.
- Entities are created for reachability, uptime, model, RouterOS version, wireless clients, and active PoE ports when available.

### Topology panel

- Open the `NetWalker` item in the Home Assistant sidebar.
- Select the NetWalker instance if you have more than one.
- Use `Poll` to trigger immediate polling of known nodes.
- Use `Discover` to scan configured discovery targets and add new nodes.
- Click a node to inspect interfaces and current traffic values.
- Use the zoom and pan buttons to navigate the map.

### Change settings later

1. Open `Settings` -> `Devices & services`.
2. Find the `NetWalker` integration card.
3. Open `Configure`.
4. Update scan targets, polling settings, or manual link overrides.

## Enable SNMP on MikroTik

The integration expects SNMP to be enabled on each MikroTik device you
want to poll. The example below uses SNMPv2c and restricts access to a
single Home Assistant IP. Adjust the IP address and community name for
your environment.

RouterOS CLI example:

```routeros
/snmp set enabled=yes contact="Home Assistant" location="Network Rack"
/snmp community set [ find default=yes ] name=netwalker addresses=192.168.1.10/32
```

Recommended follow-up checks:

- Replace `192.168.1.10/32` with the IP address of your Home Assistant instance.
- Avoid leaving the default unrestricted `public` community in place.
- Use the same community string in the NetWalker Home Assistant config flow.
- Add each MikroTik management IP, management subnet, or a small IPv4 range as a NetWalker discovery target in Home Assistant.

Reference: MikroTik RouterOS SNMP documentation
`https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP`

## Repository layout

- `custom_components/netwalker`: Home Assistant integration
- `custom_components/netwalker/panel`: static frontend for the map panel

## Notes

- The backend focuses on standards-based MIBs first. MikroTik-specific PoE and wireless metrics are left as extension points because those require proprietary OIDs that vary by platform.
- The initial panel is intentionally dependency-light and uses plain web components plus SVG.
