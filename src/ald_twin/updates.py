"""manual public-release lookup. never download or install application files."""

import json
import re
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import __version__

# release checks send no credentials or run data.
REPOSITORY = "mehnajjimy/ald-reactor-digital-twin"

# stable vmajor.minor.patch tags only, with no leading zeros and no prerelease part
VERSION_PATTERN = r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"

# github owner/name
REPOSITORY_PATTERN = r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+"

# the release reply is small, so refuse anything over 1 MiB
MAX_RESPONSE_BYTES = 1048576

# give up on github after this many seconds
TIMEOUT_SECONDS = 5


def version_parts(tag):
    """compare stable vmajor.minor.patch tags numerically, without prereleases."""
    if not isinstance(tag, str) or not re.fullmatch(VERSION_PATTERN, tag):
        raise ValueError("Expected a stable release version")
    parts = tag.removeprefix("v").split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def check_release(repository=None):
    """return a short status and an optional github download-page url."""
    if repository is None:
        repository = REPOSITORY
    installed = f"Installed version: {__version__}."
    if not repository:
        return f"{installed}\nNo release location is configured yet.", None
    if not re.fullmatch(REPOSITORY_PATTERN, repository):
        return f"{installed}\nThe release location is invalid.", None

    # ask github for the latest published release
    request = Request(f"https://api.github.com/repos/{repository}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"ALD-Reactor/{__version__}"})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
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

    # a newer release gets a link. build it here and ignore remote download links.
    if latest > current:
        url = f"https://github.com/{repository}/releases/tag/{quote(tag, safe='')}"
        return f"{installed}\nLatest release: {tag}.\nOpen download page?", url
    if latest == current:
        message = "You have the latest release."
    else:
        message = "This build is newer than the latest public release."
    return f"{installed}\nLatest release: {tag}.\n{message}", None
