"""Manual public-release lookup; never download or install application files."""

import json
import re
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import __version__

# Public release destination; the check never sends credentials or run data.
REPOSITORY = "mehnajjimy/ald-reactor-digital-twin"


def version_parts(tag):
    """Compare stable vMAJOR.MINOR.PATCH tags numerically, without prereleases."""
    if not isinstance(tag, str) or not re.fullmatch(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag):
        raise ValueError("Expected a stable release version")
    return tuple(int(part) for part in tag.removeprefix("v").split("."))


def check_release(repository=None):
    """Return a short status and an optional GitHub download-page URL."""
    repository = REPOSITORY if repository is None else repository
    installed = f"Installed version: {__version__}."
    if not repository:
        return f"{installed}\nNo release location is configured yet.", None
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repository):
        return f"{installed}\nThe release location is invalid.", None
    request = Request(f"https://api.github.com/repos/{repository}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"ALD-Reactor/{__version__}"})
    try:
        with urlopen(request, timeout=5) as response:
            payload = response.read(1048577)
        if len(payload) > 1048576:
            raise ValueError("Release response is too large")
        release = json.loads(payload)
        if not isinstance(release, dict) or release.get("draft") is not False or release.get("prerelease") is not False:
            raise ValueError("Expected a published stable release")
        tag = release.get("tag_name")
        latest = version_parts(tag)
        current = version_parts(__version__)
    except HTTPError as error:
        if error.code == 404:
            message = "No public release was found. The repository may not be public yet."
        elif error.code in (403, 429):
            message = "GitHub refused or limited the request. Try again later."
        else:
            message = "GitHub could not complete the update check. Try again later."
        return f"{installed}\n{message}", None
    except (OSError, ValueError):
        return f"{installed}\nCould not check for updates. Check your connection or try again later.", None
    if latest > current:
        # Construct the destination ourselves; never open a URL supplied in a response.
        url = f"https://github.com/{repository}/releases/tag/{quote(tag, safe='')}"
        return f"{installed}\nLatest release: {tag}.\nOpen download page?", url
    message = "You have the latest release." if latest == current else "This build is newer than the latest public release."
    return f"{installed}\nLatest release: {tag}.\n{message}", None
