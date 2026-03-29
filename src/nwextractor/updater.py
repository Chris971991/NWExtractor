"""Version checking against GitHub releases."""

from __future__ import annotations

import json
from urllib.request import urlopen, Request
from nwextractor import __version__

GITHUB_REPO = "Chris971991/NWExtractor"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def check_for_updates() -> dict | None:
    """Check GitHub for a newer release.

    Returns:
        dict with 'latest_version', 'current_version', 'update_available',
        'download_url', 'release_notes' if check succeeds.
        None if check fails (no internet, etc).
    """
    try:
        req = Request(RELEASES_URL, headers={"Accept": "application/vnd.github.v3+json"})
        response = urlopen(req, timeout=5)
        data = json.loads(response.read())

        latest_tag = data.get("tag_name", "").lstrip("v")
        current = __version__

        # Simple version compare (semver-like)
        update_available = _version_newer(latest_tag, current)

        return {
            "latest_version": latest_tag,
            "current_version": current,
            "update_available": update_available,
            "download_url": data.get("html_url", ""),
            "release_notes": data.get("body", "")[:500],
        }
    except Exception:
        return None


def _version_newer(latest: str, current: str) -> bool:
    """Check if latest version is newer than current."""
    try:
        lat = [int(x) for x in latest.split(".")]
        cur = [int(x) for x in current.split(".")]
        # Pad to same length
        while len(lat) < 3: lat.append(0)
        while len(cur) < 3: cur.append(0)
        return lat > cur
    except (ValueError, AttributeError):
        return False
