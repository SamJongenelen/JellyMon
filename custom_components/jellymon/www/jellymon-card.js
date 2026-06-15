// ─── Shared helpers ──────────────────────────────────────────────────────────

const ACTIVE_SENSOR = "sensor.jellyfin_active_sessions";

function getActive(hass) {
  return hass.states[ACTIVE_SENSOR];
}

function getUserSensors(hass) {
  const active = getActive(hass);
  const ids = active?.attributes?.user_entities || [];
  const fallback = ids.length === 0
    ? Object.keys(hass.states).filter(id => id.startsWith("sensor.jellymon_") && id !== ACTIVE_SENSOR)
    : ids;
  return fallback
    .map(id => hass.states[id])
    .filter(Boolean)
    .sort((a, b) => {
      // Active sessions always first
      const aActive = ["Playing", "Paused"].includes(a.attributes.status) ? 1 : 0;
      const bActive = ["Playing", "Paused"].includes(b.attributes.status) ? 1 : 0;
      if (aActive !== bActive) return bActive - aActive;
      // Then sort by weekly playtime descending
      return (b.attributes.weekly_playtime_seconds || 0) - (a.attributes.weekly_playtime_seconds || 0);
    });
}

function statusColor(s) {
  return { Playing: "#4caf50", Paused: "#ff9800", Connected: "#2196f3", Idle: "#2196f3", Offline: "#9e9e9e", "Not connected": "#9e9e9e" }[s] || "#9e9e9e";
}

function statusIcon(s) {
  return { Playing: "▶", Paused: "⏸", Connected: "⏺", Idle: "⏺", Offline: "○", "Not connected": "○" }[s] || "○";
}

function fmtTime(seconds) {
  if (!seconds || seconds <= 0) return "0m";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function fmtLastSeen(iso) {
  if (!iso) return "unknown";
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function userName(state) {
  return state.attributes.username
    || state.attributes.friendly_name?.replace(/^JellyMon\s+/i, "")
    || state.entity_id;
}

function barColor(pct) {
  const r = Math.round(100 + (170 - 100) * pct);
  const g = Math.round(92 * pct);
  const b = Math.round(200 - 5 * pct);
  return `rgb(${r},${g},${b})`;
}

// ─── Dialog ──────────────────────────────────────────────────────────────────

function injectDialogStyles() {
  if (document.getElementById("jellymon-styles")) return;
  const s = document.createElement("style");
  s.id = "jellymon-styles";
  s.textContent = `
    .jm-overlay {
      position: fixed; inset: 0; z-index: 9999;
      background: rgba(0,0,0,0.65);
      display: flex; align-items: center; justify-content: center;
      padding: 16px;
    }
    .jm-dialog {
      background: #1c1c1e; border-radius: 16px;
      width: 100%; max-width: 500px; max-height: 88vh;
      display: flex; flex-direction: column;
      box-shadow: 0 8px 40px rgba(0,0,0,0.7);
      overflow: hidden; color: #fff;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .jm-header {
      display: flex; align-items: center; gap: 10px;
      padding: 14px 18px 0; flex-shrink: 0;
    }
    .jm-title { font-size: 17px; font-weight: 700; flex: 1; }
    .jm-subtitle { font-size: 12px; color: #888; }
    .jm-close {
      background: none; border: none; color: #888;
      font-size: 18px; cursor: pointer; padding: 4px 8px; border-radius: 8px;
    }
    .jm-close:hover { background: #2c2c2e; color: #fff; }

    .jm-body { overflow-y: auto; padding: 14px 16px; flex: 1; }
    .jm-footer {
      padding: 8px 16px; font-size: 11px; color: #666;
      border-top: 1px solid #2c2c2e; flex-shrink: 0;
    }
    /* Now playing tab */
    .jm-card {
      background: #2c2c2e; border-radius: 12px;
      padding: 12px 14px; margin-bottom: 10px;
    }
    .jm-card:last-child { margin-bottom: 0; }
    .jm-card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
    .jm-card-icon { font-size: 15px; }
    .jm-card-name { font-weight: 600; font-size: 15px; flex: 1; }
    .jm-card-status { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.6px; }
    .jm-card-title { font-size: 13px; color: #ccc; margin-bottom: 6px; line-height: 1.4; }
    .jm-chips { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 4px; }
    .jm-chip {
      background: #3a3a3c; border-radius: 6px;
      padding: 2px 8px; font-size: 11px; color: #ccc; white-space: nowrap;
    }
    .jm-card-footer {
      display: flex; justify-content: space-between;
      margin-top: 6px; font-size: 11px; color: #555;
    }
  `;
  document.head.appendChild(s);
}

function openDialog(getHass) {
  // Remove any existing dialog
  document.querySelector(".jm-overlay")?.remove();

  // Always read fresh hass state — never use a stale snapshot
  const hass = getHass();
  const active = getActive(hass);
  const count = parseInt(active?.state) || 0;
  const hasReporting = active?.attributes?.has_playback_reporting || false;

  injectDialogStyles();

  const overlay = document.createElement("div");
  overlay.className = "jm-overlay";

  function renderNowPlaying() {
    const sensors = getUserSensors(hass);
    if (sensors.length === 0) return `<div class="jm-empty">No user sensors found.</div>`;
    return sensors.map(s => {
      const a = s.attributes;
      const status = a.status || "Offline";
      const color = statusColor(status);
      const icon = statusIcon(status);
      const name = userName(s);
      const isActive = status === "Playing" || status === "Paused";
      const isIdle = status === "Connected" || status === "Idle";
      return `
        <div class="jm-card">
          <div class="jm-card-header">
            <span class="jm-card-icon" style="color:${color}">${icon}</span>
            <span class="jm-card-name">${name}</span>
            <span class="jm-card-status" style="color:${color}">${status}</span>
          </div>
          ${isActive ? `
            <div class="jm-card-title">${s.state}</div>
            <div class="jm-chips">
              ${a.video ? `<span class="jm-chip">🎬 ${a.video}</span>` : ""}
              ${a.audio ? `<span class="jm-chip">🔊 ${a.audio}</span>` : ""}
            </div>
            <div class="jm-chips">
              ${a.method ? `<span class="jm-chip">📡 ${a.method}</span>` : ""}
              ${a.mbps != null ? `<span class="jm-chip">${a.mbps} Mbps</span>` : ""}
              ${a.device ? `<span class="jm-chip">📱 ${a.device}</span>` : ""}
            </div>
            ${a.subtitles && a.subtitles !== "none" ? `<div class="jm-chips"><span class="jm-chip">💬 ${a.subtitles}</span></div>` : ""}
          ` : isIdle ? `
            <div class="jm-chips">
              ${a.device ? `<span class="jm-chip">📱 ${a.device}</span>` : ""}
              ${a.client ? `<span class="jm-chip">${a.client}</span>` : ""}
            </div>
          ` : ""}
          <div class="jm-card-footer">
            <span>${a.last_connected ? `Last seen: ${fmtLastSeen(a.last_connected)}` : ""}</span>
            <span>${a.weekly_playtime ? `This week: ${a.weekly_playtime}` : ""}</span>
          </div>
        </div>
      `;
    }).join("");
  }


  function buildDialog() {
    // Re-read hass state on every render so dialog always shows current data
    const hass = getHass();
    overlay.innerHTML = `
      <div class="jm-dialog">
        <div class="jm-header">
          <span class="jm-title">🪼 JellyMon</span>
          <span class="jm-subtitle">${count} active stream${count !== 1 ? "s" : ""}</span>
          <button class="jm-close">✕</button>
        </div>
        <div class="jm-body">
          ${renderNowPlaying()}
        </div>
        ${!hasReporting ? `<div class="jm-footer">💡 Install Jellyfin Playback Reporting for weekly playtime stats.</div>` : ""}
      </div>
    `;

    // Close listeners are set once after first buildDialog call


  }

  // Force immediate data refresh when dialog opens
  if (getHass()?.callService) {
    getHass().callService("homeassistant", "update_entity", {
      entity_id: "sensor.jellyfin_active_sessions",
    }).then(() => { if (document.body.contains(overlay)) buildDialog(); });
  }

  buildDialog();
  document.body.appendChild(overlay);

  // Auto-refresh every 10 seconds while dialog is open
  const refreshInterval = setInterval(() => {
    if (document.body.contains(overlay)) {
      buildDialog();
    } else {
      clearInterval(refreshInterval);
    }
  }, 10000);

  // Clear interval when dialog is closed
  const origClose = () => { clearInterval(refreshInterval); overlay.remove(); };
  overlay.querySelector(".jm-close").addEventListener("click", origClose);
  overlay.addEventListener("click", e => { if (e.target === overlay) origClose(); });
}

// ─── Card ─────────────────────────────────────────────────────────────────────

class JellyMonCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  setConfig(config) { this._config = config; }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    const active = getActive(this._hass);
    const count = parseInt(active?.state) || 0;
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: inline-block; }
        .badge {
          display: inline-flex; align-items: center; gap: 6px;
          background: var(--ha-card-background, #1c1c1e);
          border: 1px solid var(--divider-color, #333);
          border-radius: 20px; padding: 4px 12px 4px 8px;
          cursor: pointer; user-select: none; transition: background 0.15s;
          font-family: var(--paper-font-body1_-_font-family, sans-serif);
        }
        .badge:hover { background: var(--secondary-background-color, #2a2a2e); }
        .icon { font-size: 18px; }
        .count { font-weight: 700; font-size: 15px; color: ${count > 0 ? "#AA5CC3" : "var(--secondary-text-color,#888)"}; }
        .label { font-size: 12px; color: var(--secondary-text-color, #888); }
      </style>
      <div class="badge" id="b">
        <span class="icon">🪼</span>
        <span class="count">${count}</span>
        <span class="label">${count === 1 ? "stream" : "streams"}</span>
      </div>
    `;
    this.shadowRoot.getElementById("b").addEventListener("click", () => openDialog(() => this._hass));
  }

  static getStubConfig() { return {}; }
}

if (!customElements.get("jellymon-card")) {
  customElements.define("jellymon-card", JellyMonCard);
}

customElements.whenDefined("jellymon-card").then(() => {
  window.customCards = window.customCards || [];
  if (!window.customCards.find(c => c.type === "jellymon-card")) {
    window.customCards.push({
      type: "jellymon-card",
      name: "JellyMon Card",
      description: "Shows active Jellyfin streams. Tap to see who is playing what.",
      preview: false,
    });
  }
});

// ─── Badge ────────────────────────────────────────────────────────────────────

class JellyMonBadge extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
  }

  setConfig(config) {
    this._config = config || {};
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  connectedCallback() {
    if (this._hass) this._render();
  }

  _render() {
    if (!this._hass) return;
    const active = getActive(this._hass);
    const count = parseInt(active?.state) || 0;
    const color = count > 0 ? "#AA5CC3" : "var(--secondary-text-color,#888)";
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: inline-block; }
        .badge {
          display: inline-flex; align-items: center; gap: 4px;
          background: var(--ha-card-background, #1c1c1e);
          border: 1px solid var(--divider-color, #333);
          border-radius: 16px; padding: 4px 10px 4px 8px;
          cursor: pointer; user-select: none; transition: background 0.15s;
          font-family: var(--paper-font-body1_-_font-family, sans-serif);
        }
        .badge:hover { background: var(--secondary-background-color, #2a2a2e); }
        .icon { font-size: 15px; }
        .count { font-size: 14px; font-weight: 700; color: ${color}; }
        .label { font-size: 11px; color: var(--secondary-text-color, #888); }
      </style>
      <div class="badge" id="b">
        <span class="icon">🪼</span>
        <span class="count">${count}</span>
        <span class="label">${count === 1 ? "stream" : "streams"}</span>
      </div>
    `;
    this.shadowRoot.getElementById("b").addEventListener("click", () => openDialog(() => this._hass));
  }

  static getStubConfig() { return {}; }
  static getConfigElement() { return document.createElement("div"); }
}

// Register only once, then announce to HA
if (!customElements.get("jellymon-badge")) {
  customElements.define("jellymon-badge", JellyMonBadge);
}

// Announce after element is fully defined so HA picks it up reliably
customElements.whenDefined("jellymon-badge").then(() => {
  window.customBadges = window.customBadges || [];
  if (!window.customBadges.find(b => b.type === "jellymon-badge")) {
    window.customBadges.push({
      type: "jellymon-badge",
      name: "JellyMon Badge",
      description: "Shows active Jellyfin streams. Tap to see who is playing what.",
    });
  }
});
