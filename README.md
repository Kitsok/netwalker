# NetWalker

NetWalker is a Home Assistant custom integration for discovering MikroTik devices over SNMP, building a topology graph from LLDP and interface data, exposing device entities, and rendering an interactive network map inside Home Assistant.

This repository is intentionally structured as a HACS custom integration, not a Home Assistant add-on. HACS can install integrations and frontend assets, but it does not install Supervisor add-ons.

## First-version scope

- UI-only configuration with Home Assistant config flow and options flow
- SNMPv2c polling
- Seed hosts entered in the web UI
- Device discovery using standard SNMP system and interface tables
- Link inference from LLDP plus optional manual UI overrides
- Home Assistant entities and devices
- Built-in Home Assistant panel for the interactive topology map
- Admin service `netwalker.refresh` for immediate refresh from HA UI automations or developer tools

## UI-only configuration

No YAML is required. All configuration is stored in Home Assistant config entries:

- title
- seed hosts
- SNMP community
- polling interval
- retries and timeouts
- manual link overrides as JSON entered in the options flow

The first version keeps manual overrides in the web UI as JSON text. That satisfies the no-filesystem-editing requirement, but it should be replaced with a proper visual link editor in a later pass.

## Repository layout

- `custom_components/netwalker`: Home Assistant integration
- `custom_components/netwalker/panel`: static frontend for the map panel

## Notes

- The backend focuses on standards-based MIBs first. MikroTik-specific PoE and wireless metrics are left as extension points because those require proprietary OIDs that vary by platform.
- The initial panel is intentionally dependency-light and uses plain web components plus SVG.
