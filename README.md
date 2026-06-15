# 🪼 JellyMon

> **This integration is fully vibe coded with [Claude](https://claude.ai). Every line of code, every config, and even the icons were generated through conversation with an AI. No IDE, no local environment — just vibes.**

A custom Home Assistant integration for monitoring Jellyfin sessions. See who's watching what, on which device, with what codec and bitrate — right from your HA dashboard.

---

## Features

- **Active stream count** sensor — total sessions currently playing
- **Per-user sensors** — one per selected user, showing:
  - Title (movie with year, or series S01 E01 — episode name)
  - Play method: Direct Play, Direct Stream, or Transcode
  - Video codec, resolution, and profile
  - Audio codec, channel layout, and bitrate
  - Subtitle track
  - Total bitrate in Mbps
  - Device and client name
  - Last connected timestamp
  - Weekly and monthly playtime *(requires Playback Reporting plugin — see below)*
- **Idle detection** — shows `Connected` when a user has a session but isn't playing
- **Config flow** — fully UI-based setup, no YAML needed
- **Configurable poll interval** — 10 to 300 seconds
- **Lovelace card + badge** — built-in custom card, auto-registered as a dashboard resource

---

## Requirements

- Home Assistant 2024.1.0 or newer
- Jellyfin server (tested on Jellyfin 10.8+)
- A Jellyfin **API key** — generate one at **Dashboard → API Keys → ＋**

---

## Optional: Playback Reporting Plugin

Weekly and monthly playtime per user requires the **Jellyfin Playback Reporting** plugin.

👉 [github.com/jellyfin/jellyfin-plugin-playbackreporting](https://github.com/jellyfin/jellyfin-plugin-playbackreporting)

**To install:**
1. In Jellyfin go to **Dashboard → Plugins → Catalog**
2. Search for **Playback Reporting**, install, and restart Jellyfin

The JellyMon config flow detects the plugin automatically and tells you whether it's present. If not installed, all other features still work — playtime attributes are simply omitted.

---

## Installation

### Via HACS (recommended)
1. In HACS go to **Integrations → ⋮ → Custom repositories**
2. Add this repository URL, category: **Integration**
3. Search for **JellyMon** and install
4. Restart Home Assistant

### Manual
1. Copy the `custom_components/jellymon` folder to `/config/custom_components/jellymon/`
2. Restart Home Assistant

---

## Setup

1. Go to **Settings → Integrations → Add Integration**
2. Search for **JellyMon**
3. Enter your Jellyfin host, port, API token, and preferred poll interval
4. Select which users to monitor
5. Done — sensors and the Lovelace card are created automatically

---

## Dashboard

Add the badge to any view:
```yaml
type: custom:jellymon-badge
```
<img width="743" height="146" alt="Screenshot_20260615_102844_Home Assistant" src="https://github.com/user-attachments/assets/f692e0d2-a609-4ca4-9998-2fc69f1f7f67" />


Or as a card:
```yaml
type: custom:jellymon-card
```
<img width="1080" height="1920" alt="Screenshot_20260615_102619_Home Assistant" src="https://github.com/user-attachments/assets/2b365507-454a-4b50-82b4-b460c4cf6d08" />

Tap to open a dialog showing all users sorted by weekly activity, with full playback details for each active session.

---

## Sensors

| Entity | State | Key Attributes |
|--------|-------|----------------|
| `sensor.jellyfin_active_sessions` | Number of active streams | `sessions`, `idle_sessions`, `user_entities` |
| `sensor.jellymon_<username>` | Title or `Connected` / `Not connected` | `status`, `method`, `video`, `audio`, `mbps`, `device`, `last_connected`, `weekly_playtime`* |

*\* Only present if Playback Reporting plugin is installed.*

---

## License

MIT

---

*Built entirely through conversation with [Claude](https://claude.ai). Zero lines typed manually.*
