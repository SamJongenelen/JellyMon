"""JellyMon — Jellyfin session monitor for Home Assistant."""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path

import aiohttp
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .utils import (
    build_stream_info,
    build_title,
    calculate_mbps,
    display_name,
    format_playtime,
    normalize_username,
    parse_playtime,
    slugify_username,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]

type JellyMonConfigEntry = ConfigEntry[JellyMonCoordinator]


# ── Lovelace card registration ────────────────────────────────────────────────

async def _register_card_resource(hass: HomeAssistant, url: str) -> None:
    """Register the Lovelace card JS as a dashboard resource if not already present."""
    try:
        lovelace = hass.data.get("lovelace")
        if not lovelace:
            return
        resources = lovelace.resources
        await resources.async_load()
        base_url = url.split("?")[0]
        if any(r["url"].split("?")[0] == base_url for r in resources.async_items()):
            return
        await resources.async_create_item({"res_type": "module", "url": url})
        _LOGGER.info("JellyMon: registered Lovelace resource %s", url)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("JellyMon: could not register Lovelace resource: %s", err)


# ── Integration lifecycle ─────────────────────────────────────────────────────

async def async_setup_entry(hass: HomeAssistant, entry: JellyMonConfigEntry) -> bool:
    """Set up JellyMon from a config entry."""
    # Serve the card JS as a static path (registered once per HA run)
    card_path = Path(__file__).parent / "www" / "jellymon-card.js"
    card_url = "/jellymon/jellymon-card.js"
    if not hass.data.get(f"{DOMAIN}_card_served"):
        try:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(card_url, str(card_path), cache_headers=False)]
            )
        except RuntimeError:
            pass  # Already registered on a previous setup
        hass.data[f"{DOMAIN}_card_served"] = True

    await _register_card_resource(hass, card_url)

    coordinator = JellyMonCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: JellyMonConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: JellyMonConfigEntry) -> None:
    """Reload JellyMon without restarting Home Assistant."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


# ── Coordinator ───────────────────────────────────────────────────────────────

class JellyMonCoordinator(DataUpdateCoordinator[dict]):
    """Polls Jellyfin and processes session data on a schedule."""

    def __init__(self, hass: HomeAssistant, entry: JellyMonConfigEntry) -> None:
        scan_interval = entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=scan_interval),
            always_update=True,
        )
        config = entry.data
        self._base_url = f"http://{config['host']}:{config['port']}"
        self._scan_interval = scan_interval
        self._has_playback_reporting: bool = config.get("has_playback_reporting", False)
        self._headers = {
            "Authorization": f"MediaBrowser Token={config['token']}",
            "accept": "application/json",
        }

    async def _get(self, path: str) -> list | dict | None:
        """Fetch a Jellyfin API endpoint. Returns parsed JSON or None on failure."""
        session = async_get_clientsession(self.hass, verify_ssl=False)
        try:
            async with session.get(
                f"{self._base_url}{path}",
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 404:
                    _LOGGER.debug("JellyMon: %s not found", path)
                    return None
                if resp.status != 200:
                    _LOGGER.warning("JellyMon: %s returned HTTP %s", path, resp.status)
                    return None
                return await resp.json()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("JellyMon: request to %s failed: %s", path, err)
            return None

    async def _async_update_data(self) -> dict:
        """Fetch all data from Jellyfin and return a processed snapshot."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        # Sessions window is at least 2× poll interval so we never miss a session
        active_window = max(120, self._scan_interval * 2)

        # Fire all API requests in parallel
        requests = [
            self._get(f"/Sessions?activeWithinSeconds={active_window}"),
            self._get("/Users"),
        ]
        if self._has_playback_reporting:
            requests += [
                self._get(f"/user_usage_stats/user_activity?days=7&endDate={now}"),
                self._get(f"/user_usage_stats/user_activity?days=30&endDate={now}"),
            ]
        results = await asyncio.gather(*requests)

        sessions_raw = results[0]
        users_raw    = results[1]
        week_raw     = results[2] if len(results) > 2 else None
        month_raw    = results[3] if len(results) > 3 else None

        if sessions_raw is None:
            raise UpdateFailed("Could not reach Jellyfin — check host, port, and token")

        # --- Last activity per user (from /Users) ---
        # Keyed by normalize_username() so lookups are case/encoding insensitive.
        last_activity = {
            normalize_username(u["Name"]): u.get("LastActivityDate")
            for u in (users_raw or [])
            if "Name" in u
        }

        # --- Weekly and monthly playtime (from Playback Reporting plugin) ---
        def parse_activity_list(raw: list | None) -> dict[str, int]:
            if not raw:
                return {}
            return {
                normalize_username(entry["user_name"]): parse_playtime(entry.get("total_play_time", 0))
                for entry in raw
                if "user_name" in entry
            }

        playtime_week  = parse_activity_list(week_raw)
        playtime_month = parse_activity_list(month_raw)

        # --- Idle sessions (connected but not playing) ---
        idle_sessions: dict[str, dict] = {}
        for s in sessions_raw:
            if not (username := s.get("UserName")) or "NowPlayingItem" in s:
                continue
            key = normalize_username(username)
            if key not in idle_sessions:
                idle_sessions[key] = {
                    "device": s.get("DeviceName", ""),
                    "client": s.get("Client", ""),
                }

        # --- Active (playing) sessions ---
        active_sessions = []
        for s in sessions_raw:
            if "NowPlayingItem" not in s:
                continue

            username = s.get("UserName", "Unknown")
            key = normalize_username(username)
            item = s["NowPlayingItem"]
            play_state = s.get("PlayState", {})
            media_streams = item.get("MediaStreams", [])
            video_info, audio_info = build_stream_info(media_streams)
            default_sub = next(
                (ms.get("DisplayTitle", "") for ms in media_streams
                 if ms.get("Type") == "Subtitle" and ms.get("IsDefault")),
                None
            )

            active_sessions.append({
                "user":          username,
                "display_name":  display_name(username),
                "title":         build_title(item),
                "type":          item.get("Type", ""),
                "device":        s.get("DeviceName", ""),
                "client":        s.get("Client", ""),
                "method":        play_state.get("PlayMethod", "Unknown"),
                "paused":        play_state.get("IsPaused", False),
                "video":         video_info,
                "audio":         audio_info,
                "subtitles":     default_sub or "none",
                "mbps":          calculate_mbps(s, media_streams),
                "last_connected":        last_activity.get(key),
                "weekly_playtime":       format_playtime(playtime_week.get(key, 0)),
                "weekly_playtime_seconds":  playtime_week.get(key, 0),
                "monthly_playtime":      format_playtime(playtime_month.get(key, 0)),
                "monthly_playtime_seconds": playtime_month.get(key, 0),
            })

        users = self.config_entry.data.get("users", [])

        return {
            "active_count":   len(active_sessions),
            "sessions":       active_sessions,
            "by_user":        {normalize_username(s["user"]): s for s in active_sessions},
            "idle_sessions":  idle_sessions,
            "last_activity":  last_activity,
            "playtime_week":  playtime_week,
            "playtime_month": playtime_month,
            "has_playback_reporting": self._has_playback_reporting,
            "user_entities":  [f"sensor.jellymon_{slugify_username(u)}" for u in users],
        }
