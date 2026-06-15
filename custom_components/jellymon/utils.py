"""Utility functions for JellyMon."""

import re
import unicodedata


def normalize_username(username: str) -> str:
    """Return a normalized key for username lookups.

    Converts to ASCII, lowercases, and replaces any non-alphanumeric
    character with a space. This means 'Walter en Klaske', 'WALTER EN KLASKE',
    and 'walter-en-klaske' all produce the same key: 'walter en klaske'.
    """
    ascii_str = unicodedata.normalize("NFKD", username).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_str.lower()).strip()


def slugify_username(username: str) -> str:
    """Convert a username to a valid HA entity ID slug (e.g. 'Walter en Klaske' → 'walter_en_klaske')."""
    ascii_str = unicodedata.normalize("NFKD", username).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_str.lower()).strip("_") or "unknown"


def display_name(username: str) -> str:
    """Return a nicely formatted display name.

    Preserves mixed casing ('Walter en Klaske', 'MacBook Pro').
    Title-cases all-lowercase or all-uppercase names ('sam' → 'Sam', 'TV' → 'Tv').
    """
    cleaned = username.replace("_", " ").strip()
    ascii_only = cleaned.encode("ascii", "ignore").decode("ascii")
    if ascii_only not in (ascii_only.lower(), ascii_only.upper()):
        return cleaned  # Already mixed case — preserve as-is
    return " ".join(word.capitalize() for word in cleaned.split())


def format_playtime(seconds: int) -> str:
    """Format seconds into a human-readable string like '4h 23m'."""
    if seconds <= 0:
        return "0m"
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"


def parse_playtime(raw: object) -> int:
    """Parse a playtime value from the Playback Reporting plugin.

    Handles both integer seconds and strings like '19 hours 16 minutes'.
    """
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw)
    hours = int(m.group(1)) if (m := re.search(r"(\d+)\s*hour", text)) else 0
    minutes = int(m.group(1)) if (m := re.search(r"(\d+)\s*min", text)) else 0
    return hours * 3600 + minutes * 60


def build_title(item: dict) -> str:
    """Build a display title from a Jellyfin NowPlayingItem."""
    match item.get("Type"):
        case "Episode":
            season = item.get("ParentIndexNumber", 0)
            episode = item.get("IndexNumber", 0)
            return f"{item.get('SeriesName', '')} S{season:02d} E{episode:02d} — {item.get('Name', '')}"
        case "Movie":
            year = item.get("ProductionYear", "")
            return f"{item.get('Name', '')} ({year})" if year else item.get("Name", "Unknown")
        case _:
            return item.get("Name", "Unknown")


def build_stream_info(media_streams: list) -> tuple[str, str]:
    """Return (video_info, audio_info) strings from a MediaStreams list."""
    video = next((ms for ms in media_streams if ms.get("Type") == "Video"), None)
    audio_streams = [ms for ms in media_streams if ms.get("Type") == "Audio"]
    audio = next((ms for ms in audio_streams if ms.get("IsDefault")), audio_streams[0] if audio_streams else None)

    video_info = ""
    if video:
        video_info = f"{video.get('Codec', '').upper()} {video.get('Profile', '')} {video.get('Width', '')}x{video.get('Height', '')}".strip()

    audio_info = ""
    if audio:
        bitrate_kbps = int(audio.get("BitRate", 0)) // 1000
        audio_info = f"{audio.get('Codec', '').upper()} {audio.get('ChannelLayout', '')} {bitrate_kbps} kbps".strip()

    return video_info, audio_info


def calculate_mbps(session: dict, media_streams: list) -> float:
    """Calculate stream bitrate in Mbps."""
    if transcode := session.get("TranscodingInfo"):
        return round(int(transcode.get("Bitrate", 0)) / 1_000_000, 2)
    total_bits = sum(int(ms.get("BitRate", 0)) for ms in media_streams if ms.get("BitRate"))
    return round(total_bits / 1_000_000, 2)
