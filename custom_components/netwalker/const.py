"""Constants for the NetWalker integration."""

from __future__ import annotations

DOMAIN = "netwalker"
PLATFORMS = ["sensor", "binary_sensor"]

CONF_SCAN_TARGETS = "scan_targets"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_TIMEOUT = "timeout"
CONF_RETRIES = "retries"
CONF_MANUAL_LINKS = "manual_links"
CONF_TITLE = "title"

DEFAULT_TITLE = "NetWalker"
DEFAULT_SCAN_INTERVAL = 60
DEFAULT_TIMEOUT = 3
DEFAULT_RETRIES = 1
DEFAULT_PORT = 161

PANEL_URL_PATH = "netwalker"
PANEL_MODULE_NAME = "netwalker-panel"
PANEL_STATIC_URL = f"/api/{DOMAIN}/panel"
PANEL_FILENAME = "netwalker-panel.js"

OIDS = {
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "sys_uptime": "1.3.6.1.2.1.1.3.0",
    "sys_name": "1.3.6.1.2.1.1.5.0",
    "if_name": "1.3.6.1.2.1.31.1.1.1.1",
    "if_alias": "1.3.6.1.2.1.31.1.1.1.18",
    "if_oper_status": "1.3.6.1.2.1.2.2.1.8",
    "if_high_speed": "1.3.6.1.2.1.31.1.1.1.15",
    "if_in_octets": "1.3.6.1.2.1.31.1.1.1.6",
    "if_out_octets": "1.3.6.1.2.1.31.1.1.1.10",
    "lldp_loc_port_id": "1.0.8802.1.1.2.1.3.7.1.3",
    "lldp_rem_sys_name": "1.0.8802.1.1.2.1.4.1.1.9",
    "lldp_rem_port_desc": "1.0.8802.1.1.2.1.4.1.1.8",
}
