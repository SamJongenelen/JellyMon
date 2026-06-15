"""Config flow for JellyMon."""

import asyncio
import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .const import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


# ── Jellyfin API helpers ──────────────────────────────────────────────────────

async def _jellyfin_get(hass, host: str, port: int, token: str, path: str) -> tuple[int, any]:
    """GET a Jellyfin endpoint. Returns (http_status, json_data_or_none)."""
    session = async_get_clientsession(hass, verify_ssl=False)
    try:
        async with session.get(
            f"http://{host}:{port}{path}",
            headers={"Authorization": f"MediaBrowser Token={token}", "accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            try:
                data = await resp.json()
            except (aiohttp.ContentTypeError, ValueError):
                data = None
            return resp.status, data
    except aiohttp.ClientError as err:
        _LOGGER.debug("JellyMon: connection to %s:%s failed: %s", host, port, err)
        return 0, None


async def _test_connection(hass, host: str, port: int, token: str) -> None:
    """Test that we can reach Jellyfin with the given credentials.
    
    Raises ValueError with an error key on failure.
    """
    status, _ = await _jellyfin_get(hass, host, port, token, "/Sessions")
    if status == 401:
        raise ValueError("invalid_auth")
    if status != 200:
        raise ValueError("cannot_connect")


async def _fetch_users(hass, host: str, port: int, token: str) -> list[str]:
    """Return a list of all Jellyfin usernames."""
    status, data = await _jellyfin_get(hass, host, port, token, "/Users")
    if status == 200 and isinstance(data, list):
        return [u["Name"] for u in data if "Name" in u]
    return []


async def _detect_playback_reporting(hass, host: str, port: int, token: str) -> bool:
    """Return True if the Playback Reporting plugin is installed."""
    status, _ = await _jellyfin_get(
        hass, host, port, token,
        "/user_usage_stats/user_activity?days=1&endDate=2099-01-01T00:00:00",
    )
    return status == 200


def _connection_schema(defaults: dict | None = None) -> vol.Schema:
    """Return the connection step schema, optionally pre-filled with defaults."""
    d = defaults or {}
    return vol.Schema({
        vol.Required("host",          default=d.get("host",          DEFAULT_HOST)):          str,
        vol.Required("port",          default=d.get("port",          DEFAULT_PORT)):          int,
        vol.Required("token",         default=d.get("token",         "")):                    str,
        vol.Required("scan_interval", default=d.get("scan_interval", DEFAULT_SCAN_INTERVAL)): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=300)
        ),
    })


def _user_schema(available_users: list[str], selected: list[str]) -> vol.Schema:
    """Return the user selection schema."""
    if available_users:
        return vol.Schema({
            vol.Required("users", default=selected): cv.multi_select({u: u for u in available_users})
        })
    # Fallback if /Users fetch failed: free-text comma-separated entry
    return vol.Schema({vol.Required("users", default=", ".join(selected)): str})


def _parse_user_input(user_input: dict) -> list[str]:
    """Parse the users field from either a multi-select list or a comma-separated string."""
    selected = user_input.get("users", [])
    if isinstance(selected, str):
        selected = [u.strip() for u in selected.split(",") if u.strip()]
    return selected


# ── Config flow ───────────────────────────────────────────────────────────────

class JellyMonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step config flow: connection details → user selection."""

    VERSION = 1

    def __init__(self) -> None:
        self._connection_data: dict = {}
        self._available_users: list[str] = []
        self._has_playback_reporting: bool = False

    def _plugin_status(self) -> str:
        if self._has_playback_reporting:
            return "✅ Playback Reporting plugin detected — weekly playtime will be available."
        return (
            "⚠️ Playback Reporting plugin not detected — weekly playtime unavailable. "
            "Install via Jellyfin Dashboard → Plugins → Catalog → Playback Reporting."
        )

    async def _validate_and_probe(self, host: str, port: int, token: str) -> str | None:
        """Test connection and fetch users + plugin status in parallel.
        
        Returns an error key string on failure, or None on success.
        """
        try:
            await _test_connection(self.hass, host, port, token)
        except ValueError as e:
            return str(e)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("JellyMon: unexpected error during connection test")
            return "unknown"

        self._has_playback_reporting, self._available_users = await asyncio.gather(
            _detect_playback_reporting(self.hass, host, port, token),
            _fetch_users(self.hass, host, port, token),
        )
        return None  # Success

    # Step 1 — connection details

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Collect host, port, token, and poll interval."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input["host"].strip()
            error = await self._validate_and_probe(host, user_input["port"], user_input["token"])
            if error:
                errors["base"] = error
            else:
                self._connection_data = {**user_input, "host": host}
                return await self.async_step_select_users()

        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(user_input),
            errors=errors,
        )

    # Step 2 — user selection

    async def async_step_select_users(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Select which Jellyfin users to create sensors for."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected = _parse_user_input(user_input)
            if not selected:
                errors["base"] = "no_users_selected"
            else:
                return self.async_create_entry(
                    title=f"Jellyfin ({self._connection_data['host']}:{self._connection_data['port']})",
                    data={
                        **self._connection_data,
                        "users": selected,
                        "has_playback_reporting": self._has_playback_reporting,
                    },
                )

        return self.async_show_form(
            step_id="select_users",
            data_schema=_user_schema(self._available_users, self._available_users),
            errors=errors,
            description_placeholders={"plugin_status": self._plugin_status()},
        )

    # Reconfigure flow (same two steps, pre-filled with current values)

    async def async_step_reconfigure(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Update connection details."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            host = user_input["host"].strip()
            error = await self._validate_and_probe(host, user_input["port"], user_input["token"])
            if error:
                errors["base"] = error
            else:
                self._connection_data = {**entry.data, **user_input, "host": host}
                return await self.async_step_reconfigure_users()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(entry.data),
            errors=errors,
        )

    async def async_step_reconfigure_users(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Update user selection."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            selected = _parse_user_input(user_input)
            if not selected:
                errors["base"] = "no_users_selected"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **self._connection_data,
                        "users": selected,
                        "has_playback_reporting": self._has_playback_reporting,
                    },
                )

        current_users = self._connection_data.get("users", [])
        return self.async_show_form(
            step_id="reconfigure_users",
            data_schema=_user_schema(self._available_users, current_users),
            errors=errors,
            description_placeholders={"plugin_status": self._plugin_status()},
        )
