"""Sensor platform for JellyMon."""

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import JellyMonConfigEntry, JellyMonCoordinator
from .utils import display_name, format_playtime, normalize_username, slugify_username


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JellyMonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up JellyMon sensors from a config entry."""
    coordinator: JellyMonCoordinator = entry.runtime_data
    users: list[str] = entry.data.get("users", [])

    entities = [JellyMonActiveSensor(coordinator, entry)]
    entities += [JellyMonUserSensor(coordinator, entry, user) for user in users]
    async_add_entities(entities)


class JellyMonActiveSensor(CoordinatorEntity[JellyMonCoordinator], SensorEntity):
    """Sensor showing total number of active Jellyfin streams."""

    _attr_translation_key = "active_sessions"
    _attr_native_unit_of_measurement = "streams"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cast-connected"
    _attr_has_entity_name = True

    def __init__(self, coordinator: JellyMonCoordinator, entry: JellyMonConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_active"

    @property
    def native_value(self) -> int:
        if not self.coordinator.data:
            return 0
        return self.coordinator.data["active_count"]

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        data = self.coordinator.data
        return {
            "sessions":              data["sessions"],
            "idle_sessions":         data["idle_sessions"],
            "has_playback_reporting": data["has_playback_reporting"],
            "user_entities":         data["user_entities"],
        }


class JellyMonUserSensor(CoordinatorEntity[JellyMonCoordinator], SensorEntity):
    """Sensor showing what a specific Jellyfin user is currently playing."""

    _attr_icon = "mdi:account-music"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: JellyMonCoordinator,
        entry: JellyMonConfigEntry,
        username: str,
    ) -> None:
        super().__init__(coordinator)
        self._username = username
        self._key = normalize_username(username)  # Computed once; used for all data lookups
        self._attr_name = f"JellyMon {display_name(username)}"
        self._attr_unique_id = f"{entry.entry_id}_{slugify_username(username)}"

    @property
    def _session(self) -> dict | None:
        """Return the active session for this user, or None if not playing."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data["by_user"].get(self._key)

    @property
    def _idle(self) -> dict | None:
        """Return the idle session for this user, or None if not connected."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data["idle_sessions"].get(self._key)

    @property
    def native_value(self) -> str:
        if session := self._session:
            return session["title"]
        if self._idle:
            return "Connected"
        return "Not connected"

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        has_reporting = data.get("has_playback_reporting", False)

        attrs = {
            "username":       display_name(self._username),
            "last_connected": data.get("last_activity", {}).get(self._key),
        }

        if has_reporting:
            week  = data.get("playtime_week", {}).get(self._key, 0)
            month = data.get("playtime_month", {}).get(self._key, 0)
            attrs["weekly_playtime"]          = format_playtime(week)
            attrs["weekly_playtime_seconds"]  = week
            attrs["monthly_playtime"]         = format_playtime(month)
            attrs["monthly_playtime_seconds"] = month

        if session := self._session:
            attrs.update({
                "status":    "Paused" if session["paused"] else "Playing",
                "type":      session["type"],
                "method":    session["method"],
                "video":     session["video"],
                "audio":     session["audio"],
                "subtitles": session["subtitles"],
                "mbps":      session["mbps"],
                "device":    session["device"],
                "client":    session["client"],
            })
        elif idle := self._idle:
            attrs.update({
                "status": "Idle",
                "device": idle["device"],
                "client": idle["client"],
            })
        else:
            attrs["status"] = "Offline"

        return attrs
