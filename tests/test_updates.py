"""release checks only read a fixed github address and never claim up to date on failure."""

from io import BytesIO
import json
from urllib.error import HTTPError, URLError

from ald_twin import __version__, updates


def release(tag, **changes):
    """a github latest-release reply for tag."""
    return BytesIO(json.dumps(dict(tag_name=tag, draft=False, prerelease=False, **changes)).encode())


def test_release_check_uses_a_fixed_address_and_numeric_versions(monkeypatch):
    """catches a trusted remote link, a string version compare or a sent credential."""
    calls = []

    def fetch(request, timeout):
        """record the request and reply with v1.10.0 and an untrusted link."""
        calls.append((request, timeout))
        return release("v1.10.0", html_url="file:///untrusted")

    monkeypatch.setattr(updates, "urlopen", fetch)
    message, url = updates.check_release()
    assert "Latest release: v1.10.0" in message
    assert url == "https://github.com/mehnajjimy/ald-reactor-digital-twin/releases/tag/v1.10.0"
    assert calls[0][0].full_url == "https://api.github.com/repos/mehnajjimy/ald-reactor-digital-twin/releases/latest"
    assert calls[0][1] == 5
    assert not calls[0][0].has_header("Authorization")

    # the installed or an older release offers no download
    for tag, expected in [("v"+__version__, "latest release"), ("v0.0.1", "newer than")]:
        monkeypatch.setattr(updates, "urlopen", lambda *a, **k: release(tag))
        message, url = updates.check_release("owner/reactor")
        assert expected in message
        assert url is None


def test_failed_release_checks_never_say_up_to_date(monkeypatch):
    """catches a bad reply or network error being shown as no update."""
    replies = [b"not json", b"{}", b"x"*1048577,
               b'{"tag_name":"v0.2.0rc1","draft":false,"prerelease":false}',
               b'{"tag_name":"v0.2.0","draft":true,"prerelease":false}']
    for reply in replies:
        monkeypatch.setattr(updates, "urlopen", lambda *a, **k: BytesIO(reply))
        message, url = updates.check_release("owner/reactor")
        assert "Could not check" in message
        assert url is None

    errors = [(HTTPError("", 404, "", {}, None), "No public release"),
              (HTTPError("", 429, "", {}, None), "refused or limited"),
              (HTTPError("", 500, "", {}, None), "could not complete"),
              (URLError("offline"), "Could not check"),
              (TimeoutError(), "Could not check")]
    for error, expected in errors:
        def fail(*a, **k):
            """raise this network error."""
            raise error

        monkeypatch.setattr(updates, "urlopen", fail)
        message, url = updates.check_release("owner/reactor")
        assert expected in message
        assert url is None
