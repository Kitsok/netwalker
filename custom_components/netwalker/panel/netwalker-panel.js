class NetWalkerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._entries = [];
    this._selectedEntryId = null;
    this._selectedDeviceId = null;
    this._data = null;
    this._entriesLoaded = false;
    this._lastLoaded = 0;
    this._pollHandle = null;
    this._zoom = 1;
    this._panX = 0;
    this._panY = 0;
    this._scrollState = {};
    this._interfaceSort = "traffic";
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._entriesLoaded) {
      this._loadEntries();
    } else if (Date.now() - this._lastLoaded > 5000) {
      this._loadTopology();
    } else if (!this.shadowRoot.innerHTML) {
      this._render();
    }
  }

  connectedCallback() {
    this._pollHandle = window.setInterval(() => this._loadTopology(), 15000);
  }

  disconnectedCallback() {
    if (this._pollHandle) {
      window.clearInterval(this._pollHandle);
      this._pollHandle = null;
    }
  }

  async _loadEntries() {
    if (!this._hass) {
      return;
    }
    try {
      const payload = await this._hass.callApi("GET", "netwalker/entries");
      this._entries = payload.entries || [];
      if (!this._selectedEntryId || !this._entries.some((entry) => entry.entry_id === this._selectedEntryId)) {
        this._selectedEntryId = this._entries[0]?.entry_id || null;
      }
      this._entriesLoaded = true;
      await this._loadTopology();
      return;
    } catch (err) {
      this._data = { error: err?.message || "Failed to load NetWalker entries" };
      this._entriesLoaded = true;
      this._render();
    }
  }

  async _loadTopology() {
    if (!this._hass || !this._selectedEntryId) {
      this._render();
      return;
    }
    this._lastLoaded = Date.now();
    try {
      this._data = await this._hass.callApi(
        "GET",
        `netwalker/topology/${this._selectedEntryId}`
      );
      if (!this._selectedDeviceId && this._data.devices?.length) {
        this._selectedDeviceId = this._data.devices[0].id;
      }
      if (
        this._selectedDeviceId &&
        !this._data.devices?.some((device) => device.id === this._selectedDeviceId)
      ) {
        this._selectedDeviceId = this._data.devices?.[0]?.id || null;
      }
    } catch (err) {
      this._data = { error: err?.message || "Failed to load topology" };
    }
    this._render();
  }

  _render() {
    this._captureScrollState();
    const entries = this._entries;
    const data = this._data;
    const devices = data?.devices || [];
    const links = data?.links || [];
    const width = 1280;
    const height = 860;
    const viewWidth = width / this._zoom;
    const viewHeight = height / this._zoom;
    const viewX = (width - viewWidth) / 2 - this._panX;
    const viewY = (height - viewHeight) / 2 - this._panY;

    const positionedDevices = this._layoutDevices(devices, width, height);
    const positions = new Map(positionedDevices.map((device) => [device.id, device]));
    const selectedDevice =
      positionedDevices.find((device) => device.id === this._selectedDeviceId) || null;

    const linkSvg = links
      .map((link) => this._renderLink(link, positions))
      .join("");

    const nodeSvg = positionedDevices
      .map((device) => {
        const selectedClass =
          device.id === this._selectedDeviceId ? "node-shell selected" : "node-shell";
        const statusClass = device.reachable ? "node up" : "node down";
        const model = device.model || this._fallbackModel(device.sys_descr) || "Unknown model";
        const version = device.routeros_version || this._fallbackVersion(device.sys_descr) || "n/a";
        return `
          <g class="${selectedClass}" data-device-id="${this._escape(device.id)}" tabindex="0">
            <circle cx="${device.x}" cy="${device.y}" r="80" class="${statusClass}"></circle>
            <text x="${device.x}" y="${device.y - 24}" text-anchor="middle" class="node-title">${this._escape(device.name)}</text>
            <text x="${device.x}" y="${device.y - 2}" text-anchor="middle" class="node-line">${this._escape(model)}</text>
            <text x="${device.x}" y="${device.y + 20}" text-anchor="middle" class="node-line">RouterOS ${this._escape(version)}</text>
            <text x="${device.x}" y="${device.y + 42}" text-anchor="middle" class="node-line">${this._escape(this._formatNodeTraffic(device.interfaces || [], "rx"))}</text>
            <text x="${device.x}" y="${device.y + 58}" text-anchor="middle" class="node-line">${this._escape(this._formatNodeTraffic(device.interfaces || [], "tx"))}</text>
          </g>
        `;
      })
      .join("");

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          min-height: 100vh;
          background:
            radial-gradient(circle at top, rgba(48, 97, 176, 0.26), transparent 44%),
            linear-gradient(180deg, #0d1724 0%, #172130 100%);
          color: #eef3fb;
          font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
        }
        .page {
          padding: 22px;
        }
        .toolbar {
          display: grid;
          grid-template-columns: minmax(220px, 320px) 1fr auto;
          gap: 14px;
          align-items: center;
          margin-bottom: 16px;
        }
        .title-block {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .title {
          font-size: 30px;
          font-weight: 600;
          letter-spacing: 0.03em;
        }
        .subtitle {
          color: #a7b6cb;
          font-size: 13px;
        }
        .select,
        .button {
          border-radius: 12px;
          border: 1px solid rgba(255, 255, 255, 0.1);
          background: rgba(8, 12, 20, 0.56);
          color: #eef3fb;
          padding: 10px 12px;
          font: inherit;
        }
        .button-row {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          justify-content: flex-end;
        }
        .button {
          cursor: pointer;
        }
        .content {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 340px;
          gap: 16px;
        }
        .map-shell,
        .detail-shell,
        .empty-shell,
        .error-shell {
          border-radius: 22px;
          border: 1px solid rgba(255, 255, 255, 0.08);
          background: rgba(8, 12, 20, 0.48);
          box-shadow: 0 22px 48px rgba(0, 0, 0, 0.22);
        }
        .map-shell {
          overflow: auto;
          padding: 18px;
        }
        .detail-shell {
          padding: 18px;
          overflow: auto;
        }
        .error-shell,
        .empty-shell {
          padding: 18px;
        }
        svg {
          width: 100%;
          min-width: 980px;
          height: auto;
        }
        .node {
          fill: rgba(20, 32, 49, 0.94);
          stroke-width: 4;
          transition: filter 140ms ease, stroke-width 140ms ease;
        }
        .node.up {
          stroke: #67c67c;
        }
        .node.down {
          stroke: #7c828d;
        }
        .node-shell {
          cursor: pointer;
        }
        .node-shell:hover .node,
        .node-shell.selected .node {
          filter: drop-shadow(0 0 14px rgba(81, 149, 232, 0.34));
          stroke-width: 6;
        }
        .node-title {
          fill: #ffffff;
          font-size: 17px;
          font-weight: 600;
        }
        .node-line {
          fill: #bbcade;
          font-size: 12px;
        }
        .link-label {
          fill: #dce7f8;
          font-size: 12px;
        }
        .traffic-label {
          fill: #8fb1d8;
          font-size: 11px;
        }
        .panel-title {
          font-size: 18px;
          font-weight: 600;
          margin-bottom: 12px;
        }
        .section-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 12px;
        }
        .section-header .panel-title {
          margin-bottom: 0;
        }
        .sort-select {
          min-width: 150px;
        }
        .meta-grid {
          display: grid;
          grid-template-columns: 112px 1fr;
          gap: 8px 12px;
          font-size: 13px;
          margin-bottom: 18px;
        }
        .meta-key {
          color: #95a6bf;
        }
        .interface-list {
          display: grid;
          gap: 10px;
          max-height: 60vh;
          overflow: auto;
        }
        .interface-card {
          display: grid;
          gap: 8px;
          border-radius: 14px;
          background: rgba(255, 255, 255, 0.04);
          border: 1px solid rgba(255, 255, 255, 0.06);
          padding: 10px 12px;
        }
        .interface-name {
          font-size: 14px;
          font-weight: 600;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .interface-speed {
          color: #aab9ce;
          font-size: 12px;
          line-height: 1.3;
        }
        .interface-icons {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        .metric-pill {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.06);
          color: #dbe6f5;
          padding: 2px 8px;
          font-size: 11px;
          letter-spacing: 0.02em;
          white-space: nowrap;
        }
        .metric-pill.oper-up {
          background: rgba(103, 198, 124, 0.14);
          color: #9fe2ad;
        }
        .metric-pill.oper-down {
          background: rgba(124, 130, 141, 0.18);
          color: #cad1d9;
        }
        .metric-pill.oper-other {
          background: rgba(90, 134, 190, 0.16);
          color: #b9d4ff;
        }
        .metric-pill.rx {
          color: #8fd8ff;
        }
        .metric-pill.tx {
          color: #ffd59a;
        }
        .metric-pill.poe {
          border-radius: 999px;
          background: rgba(231, 170, 85, 0.16);
          color: #ffd089;
        }
        .metric-pill.poe.inactive {
          background: rgba(124, 130, 141, 0.18);
          color: #cad1d9;
        }
        @media (max-width: 1100px) {
          .toolbar,
          .content {
            grid-template-columns: 1fr;
          }
          .button-row {
            justify-content: flex-start;
          }
        }
      </style>
      <div class="page">
        <div class="toolbar">
          <div class="title-block">
            <div class="title">NetWalker</div>
            <div class="subtitle">${this._escape(this._formatTimestamp(data?.updated_at))}</div>
          </div>
          <select class="select" id="entry-select">
            ${
              entries.length
                ? entries
                    .map(
                      (entry) => `
                        <option value="${this._escape(entry.entry_id)}" ${
                          entry.entry_id === this._selectedEntryId ? "selected" : ""
                        }>
                          ${this._escape(entry.title)}
                        </option>
                      `
                    )
                    .join("")
                : `<option value="">No NetWalker instances configured</option>`
            }
          </select>
          <div class="button-row">
            <button class="button" id="refresh-button">Refresh</button>
            <button class="button" id="zoom-in">Zoom +</button>
            <button class="button" id="zoom-out">Zoom -</button>
            <button class="button" id="pan-left">Left</button>
            <button class="button" id="pan-right">Right</button>
            <button class="button" id="pan-up">Up</button>
            <button class="button" id="pan-down">Down</button>
            <button class="button" id="reset-view">Reset</button>
          </div>
        </div>
        ${
          data?.error
            ? `<div class="error-shell">${this._escape(data.error)}</div>`
            : !entries.length
              ? `<div class="empty-shell">Create a NetWalker config entry in Home Assistant to start discovery.</div>`
              : `<div class="content">
                  <div class="map-shell">
                    <svg viewBox="${viewX} ${viewY} ${viewWidth} ${viewHeight}" role="img" aria-label="Network topology map">
                      <defs>
                        <marker id="arrow-forward" markerWidth="10" markerHeight="10" refX="7" refY="5" orient="auto" markerUnits="strokeWidth">
                          <path d="M 0 0 L 10 5 L 0 10 z" fill="#3fd0d9"></path>
                        </marker>
                        <marker id="arrow-reverse" markerWidth="10" markerHeight="10" refX="7" refY="5" orient="auto" markerUnits="strokeWidth">
                          <path d="M 0 0 L 10 5 L 0 10 z" fill="#e7aa55"></path>
                        </marker>
                        <marker id="arrow-down" markerWidth="10" markerHeight="10" refX="7" refY="5" orient="auto" markerUnits="strokeWidth">
                          <path d="M 0 0 L 10 5 L 0 10 z" fill="#7c828d"></path>
                        </marker>
                      </defs>
                      ${linkSvg}
                      ${nodeSvg}
                    </svg>
                  </div>
                  <div class="detail-shell">
                    ${this._renderSelectedDevice(selectedDevice)}
                  </div>
                </div>`
        }
      </div>
    `;

    this._bindEvents();
    requestAnimationFrame(() => this._restoreScrollState());
  }

  _bindEvents() {
    const entrySelect = this.shadowRoot.getElementById("entry-select");
    if (entrySelect) {
      entrySelect.onchange = async (event) => {
        this._selectedEntryId = event.target.value || null;
        this._selectedDeviceId = null;
        await this._loadTopology();
      };
    }

    const refreshButton = this.shadowRoot.getElementById("refresh-button");
    if (refreshButton) {
      refreshButton.onclick = async () => {
        if (this._hass && this._selectedEntryId) {
          await this._hass.callService("netwalker", "refresh", {
            entry_id: this._selectedEntryId,
          });
        }
        await this._loadTopology();
      };
    }

    const interfaceSort = this.shadowRoot.getElementById("interface-sort");
    if (interfaceSort) {
      interfaceSort.onchange = (event) => {
        this._interfaceSort = event.target.value || "traffic";
        this._render();
      };
    }

    for (const [buttonId, action] of [
      ["zoom-in", () => { this._zoom = Math.min(this._zoom * 1.2, 3); }],
      ["zoom-out", () => { this._zoom = Math.max(this._zoom / 1.2, 0.7); }],
      ["pan-left", () => { this._panX -= 70 / this._zoom; }],
      ["pan-right", () => { this._panX += 70 / this._zoom; }],
      ["pan-up", () => { this._panY -= 55 / this._zoom; }],
      ["pan-down", () => { this._panY += 55 / this._zoom; }],
      ["reset-view", () => {
        this._zoom = 1;
        this._panX = 0;
        this._panY = 0;
      }],
    ]) {
      const button = this.shadowRoot.getElementById(buttonId);
      if (button) {
        button.onclick = () => {
          action();
          this._render();
        };
      }
    }

    this.shadowRoot.querySelectorAll("[data-device-id]").forEach((element) => {
      const handler = () => {
        this._selectedDeviceId = element.getAttribute("data-device-id");
        this._render();
      };
      element.onclick = handler;
      element.onkeydown = (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          handler();
        }
      };
    });
  }

  _layoutDevices(devices, width, height) {
    if (!devices.length) {
      return [];
    }
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.min(width, height) * 0.34;
    return devices.map((device, index) => {
      const angle = (Math.PI * 2 * index) / devices.length - Math.PI / 2;
      return {
        ...device,
        x: centerX + Math.cos(angle) * radius,
        y: centerY + Math.sin(angle) * radius,
      };
    });
  }

  _renderLink(link, positions) {
    const source = positions.get(link.source_device_id);
    const target = positions.get(link.target_device_id);
    if (!source || !target) {
      return "";
    }

    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const length = Math.hypot(dx, dy) || 1;
    const offsetX = (-dy / length) * 6;
    const offsetY = (dx / length) * 6;
    const stateUp = link.state === "up";
    const forwardColor = stateUp ? "#3fd0d9" : "#7c828d";
    const reverseColor = stateUp ? "#e7aa55" : "#7c828d";
    const markerForward = stateUp ? "url(#arrow-forward)" : "url(#arrow-down)";
    const markerReverse = stateUp ? "url(#arrow-reverse)" : "url(#arrow-down)";
    const labelX = (source.x + target.x) / 2;
    const labelY = (source.y + target.y) / 2;
    return `
      <g class="link-group">
        <line
          x1="${source.x + offsetX}"
          y1="${source.y + offsetY}"
          x2="${target.x + offsetX}"
          y2="${target.y + offsetY}"
          stroke="${forwardColor}"
          stroke-width="3"
          stroke-linecap="round"
          marker-end="${markerForward}"
        ></line>
        <line
          x1="${target.x - offsetX}"
          y1="${target.y - offsetY}"
          x2="${source.x - offsetX}"
          y2="${source.y - offsetY}"
          stroke="${reverseColor}"
          stroke-width="3"
          stroke-linecap="round"
          marker-end="${markerReverse}"
        ></line>
        <text x="${labelX}" y="${labelY - 10}" text-anchor="middle" class="link-label">${this._escape(link.source_interface)} -> ${this._escape(link.target_interface || "?")}</text>
        <text x="${labelX}" y="${labelY + 8}" text-anchor="middle" class="traffic-label">${this._escape(this._formatBits(link.forward_bps))} / ${this._escape(this._formatBits(link.reverse_bps))}</text>
      </g>
    `;
  }

  _renderSelectedDevice(device) {
    if (!device) {
      return `
        <div class="panel-title">Device details</div>
        <div class="subtitle">Select a node to inspect its interfaces and metadata.</div>
      `;
    }

    const interfaces = this._sortInterfaces(device.interfaces || [])
      .map(
        (iface) => {
          return `
          <div class="interface-card">
            <div class="interface-name" title="${this._escape(iface.name)}">${this._escape(iface.name)}</div>
            <div class="interface-speed">
              ${this._escape(this._formatSpeed(iface.speed_mbps))}
            </div>
            <div class="interface-icons">
              ${this._renderOperPill(iface)}
              <span class="metric-pill rx">&darr; ${this._escape(this._formatBits(iface.rx_bps))}</span>
              <span class="metric-pill tx">&uarr; ${this._escape(this._formatBits(iface.tx_bps))}</span>
              ${this._renderPoeBadge(iface)}
            </div>
          </div>
        `
        }
      )
      .join("");

    const model = device.model || this._fallbackModel(device.sys_descr);
    const version = device.routeros_version || this._fallbackVersion(device.sys_descr);
    const metaRows = [
      ["Host", device.host],
      ["Model", model || "-"],
      ["RouterOS", version || "-"],
      ["Reachable", device.reachable ? "Yes" : "No"],
      ["Uptime", this._formatUptimeTicks(device.uptime_ticks)],
      ["Wireless", device.wireless_clients ?? "-"],
      ["PoE active", this._formatPoeSummary(device)],
      ["System", device.sys_descr || "-"],
    ];

    return `
      <div class="panel-title">${this._escape(device.name)}</div>
      <div class="meta-grid">
        ${metaRows
          .map(
            ([key, value]) =>
              `<div class="meta-key">${this._escape(key)}</div><div>${this._escape(value)}</div>`
          )
          .join("")}
      </div>
      <div class="section-header">
        <div class="panel-title">Interfaces</div>
        <select class="select sort-select" id="interface-sort">
          <option value="traffic" ${this._interfaceSort === "traffic" ? "selected" : ""}>Traffic</option>
          <option value="poe" ${this._interfaceSort === "poe" ? "selected" : ""}>PoE</option>
          <option value="speed" ${this._interfaceSort === "speed" ? "selected" : ""}>Speed</option>
          <option value="name" ${this._interfaceSort === "name" ? "selected" : ""}>Name</option>
        </select>
      </div>
      <div class="interface-list">${interfaces || `<div class="subtitle">No interfaces discovered.</div>`}</div>
    `;
  }

  _sortInterfaces(interfaces) {
    return interfaces
      .slice()
      .sort((left, right) => {
        const byTraffic = this._compareTraffic(right, left);
        const byPoe = this._comparePoe(right, left);
        const bySpeed = this._compareSpeed(right, left);

        if (this._interfaceSort === "poe") {
          return byPoe || byTraffic || bySpeed || left.name.localeCompare(right.name);
        }
        if (this._interfaceSort === "speed") {
          return bySpeed || byTraffic || byPoe || left.name.localeCompare(right.name);
        }
        if (this._interfaceSort === "name") {
          return left.name.localeCompare(right.name);
        }
        return byTraffic || byPoe || bySpeed || left.name.localeCompare(right.name);
      });
  }

  _compareTraffic(left, right) {
    return this._trafficScore(left) - this._trafficScore(right);
  }

  _comparePoe(left, right) {
    return this._poeScore(left) - this._poeScore(right);
  }

  _compareSpeed(left, right) {
    return (left.speed_mbps || 0) - (right.speed_mbps || 0);
  }

  _trafficScore(iface) {
    return (iface.rx_bps || 0) + (iface.tx_bps || 0);
  }

  _poeScore(iface) {
    const active = iface.poe_status === "powered_on" ? 1 : 0;
    return active * 1000000000 + (iface.poe_power_watts || 0);
  }

  _summarizeTraffic(interfaces) {
    const totals = interfaces.reduce(
      (acc, iface) => {
        acc.rx += iface.rx_bps || 0;
        acc.tx += iface.tx_bps || 0;
        return acc;
      },
      { rx: 0, tx: 0 }
    );
    return `RX ${this._formatBits(totals.rx)}  TX ${this._formatBits(totals.tx)}`;
  }

  _formatNodeTraffic(interfaces, direction) {
    const totals = interfaces.reduce(
      (acc, iface) => {
        acc.rx += iface.rx_bps || 0;
        acc.tx += iface.tx_bps || 0;
        return acc;
      },
      { rx: 0, tx: 0 }
    );
    if (direction === "tx") {
      return `↑ ${this._formatBits(totals.tx)}`;
    }
    return `↓ ${this._formatBits(totals.rx)}`;
  }

  _formatPoeSummary(device) {
    const portsActive = device.poe_ports_active;
    if (portsActive == null) {
      return "-";
    }

    const totalWatts = (device.interfaces || []).reduce((sum, iface) => {
      return sum + (Number(iface.poe_power_watts) || 0);
    }, 0);

    if (totalWatts <= 0) {
      return String(portsActive);
    }

    return `${portsActive} (${totalWatts.toFixed(1)} W)`;
  }

  _formatBits(value) {
    if (!value) {
      return "0 bps";
    }
    const units = ["bps", "Kbps", "Mbps", "Gbps", "Tbps"];
    let current = Number(value);
    let unitIndex = 0;
    while (current >= 1000 && unitIndex < units.length - 1) {
      current /= 1000;
      unitIndex += 1;
    }
    return `${current.toFixed(current >= 100 ? 0 : 1)} ${units[unitIndex]}`;
  }

  _formatSpeed(value) {
    if (!value) {
      return "-";
    }
    return `${value} Mbps`;
  }

  _renderOperPill(iface) {
    const status = iface.oper_status || "unknown";
    const statusClass =
      status === "up" ? "oper-up" : status === "down" ? "oper-down" : "oper-other";
    const icon = status === "up" ? "●" : status === "down" ? "○" : "◌";
    return `<span class="metric-pill ${statusClass}">${icon} ${this._escape(status.replaceAll("_", " "))}</span>`;
  }

  _renderPoeBadge(iface) {
    if (!iface.poe_status) {
      return "";
    }
    if (iface.poe_status === "powered_on") {
      const watts = iface.poe_power_watts != null ? `${iface.poe_power_watts.toFixed(1)} W` : "on";
      return `<span class="metric-pill poe">&#9889; ${this._escape(watts)}</span>`;
    }
    const label = iface.poe_status
      .replaceAll("_", " ")
      .replace(/\b\w/g, (char) => char.toUpperCase());
    return `<span class="metric-pill poe inactive">&#9889; ${this._escape(label)}</span>`;
  }

  _formatUptimeTicks(value) {
    if (!value) {
      return "-";
    }
    const seconds = Math.floor(value / 100);
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${days}d ${hours}h ${minutes}m`;
  }

  _formatTimestamp(value) {
    if (!value) {
      return "Waiting for topology data";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return parsed.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
    });
  }

  _fallbackModel(sysDescr) {
    if (!sysDescr) {
      return null;
    }
    const modelBeforeVersion = sysDescr.match(
      /RouterOS\s+([A-Za-z0-9.+_-]+)\s+[0-9]+(?:\.[0-9A-Za-z_-]+)+/
    );
    if (modelBeforeVersion) {
      return modelBeforeVersion[1];
    }
    const versionBeforeModel = sysDescr.match(
      /RouterOS\s+[0-9]+(?:\.[0-9A-Za-z_-]+)+\s+\(([^)]+)\)/
    );
    return versionBeforeModel ? versionBeforeModel[1] : null;
  }

  _fallbackVersion(sysDescr) {
    if (!sysDescr) {
      return null;
    }
    const match = sysDescr.match(/\b([0-9]+(?:\.[0-9A-Za-z_-]+)+)\b/);
    return match ? match[1] : null;
  }

  _captureScrollState() {
    this._scrollState = {
      hostScrollY: window.scrollY,
      mapScrollTop: this.shadowRoot.querySelector(".map-shell")?.scrollTop || 0,
      mapScrollLeft: this.shadowRoot.querySelector(".map-shell")?.scrollLeft || 0,
      detailScrollTop: this.shadowRoot.querySelector(".detail-shell")?.scrollTop || 0,
      interfaceScrollTop:
        this.shadowRoot.querySelector(".interface-list")?.scrollTop || 0,
    };
  }

  _restoreScrollState() {
    const mapShell = this.shadowRoot.querySelector(".map-shell");
    const detailShell = this.shadowRoot.querySelector(".detail-shell");
    const interfaceList = this.shadowRoot.querySelector(".interface-list");
    if (mapShell) {
      mapShell.scrollTop = this._scrollState.mapScrollTop || 0;
      mapShell.scrollLeft = this._scrollState.mapScrollLeft || 0;
    }
    if (detailShell) {
      detailShell.scrollTop = this._scrollState.detailScrollTop || 0;
    }
    if (interfaceList) {
      interfaceList.scrollTop = this._scrollState.interfaceScrollTop || 0;
    }
    window.scrollTo(0, this._scrollState.hostScrollY || 0);
  }

  _escape(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }
}

customElements.define("netwalker-panel", NetWalkerPanel);
