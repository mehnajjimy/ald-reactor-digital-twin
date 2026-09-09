"""release checks never install files, trust remote urls, or delay shutdown."""

from io import BytesIO
import json
from threading import Lock
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from ald_twin import __version__, desktop, updates


def response(tag="v0.1.2", **changes):
    return BytesIO(json.dumps(dict(tag_name=tag, draft=False, prerelease=False, **changes)).encode())


def test_unconfigured_release_does_not_contact_the_network(monkeypatch):
    monkeypatch.setattr(updates, "urlopen", lambda *a, **k: pytest.fail("Unexpected network request"))
    message, url = updates.check_release("")
    assert "No release location" in message and __version__ in message
    assert url is None


@pytest.mark.parametrize("repository", ["https://github.com/a/b", "a/b/extra", "a b/c"])
def test_invalid_release_location_stays_local(monkeypatch, repository):
    monkeypatch.setattr(updates, "urlopen", lambda *a, **k: pytest.fail("Unexpected network request"))
    assert "invalid" in updates.check_release(repository)[0]


def test_newer_release_uses_numeric_version_and_fixed_github_destination(monkeypatch):
    calls = []
    def fetch(request, timeout):
        calls.append((request, timeout))
        return response("v1.10.0", html_url="file:///untrusted")
    monkeypatch.setattr(updates, "urlopen", fetch)
    message, url = updates.check_release()
    assert "Latest release: v1.10.0" in message
    assert url == "https://github.com/mehnajjimy/ald-reactor-digital-twin/releases/tag/v1.10.0"
    assert calls[0][0].full_url == "https://api.github.com/repos/mehnajjimy/ald-reactor-digital-twin/releases/latest"
    assert calls[0][1] == 5
    assert not calls[0][0].has_header("Authorization")


@pytest.mark.parametrize("tag, expected", [("v"+__version__, "latest release"), ("v0.0.1", "newer than")])
def test_current_or_older_release_never_offers_a_download(monkeypatch, tag, expected):
    monkeypatch.setattr(updates, "urlopen", lambda *a, **k: response(tag))
    message, url = updates.check_release("owner/reactor")
    assert expected in message and url is None


@pytest.mark.parametrize("payload", [b"not json", b"[]", b"{}", b"\xff", b"x"*1048577,
    b'{"tag_name":"v0.2.0rc1","draft":false,"prerelease":false}',
    b'{"tag_name":"v0.2.0","draft":true,"prerelease":false}',
    b'{"tag_name":"v0.2.0","draft":false,"prerelease":true}'])
def test_invalid_release_response_is_a_visible_failure(monkeypatch, payload):
    monkeypatch.setattr(updates, "urlopen", lambda *a, **k: BytesIO(payload))
    message, url = updates.check_release("owner/reactor")
    assert "Could not check" in message and url is None


@pytest.mark.parametrize("error, expected", [
    (HTTPError("", 404, "", {}, None), "No public release"),
    (HTTPError("", 403, "", {}, None), "refused or limited"),
    (HTTPError("", 429, "", {}, None), "refused or limited"),
    (HTTPError("", 500, "", {}, None), "could not complete"),
    (URLError("offline"), "Could not check"), (TimeoutError(), "Could not check")])
def test_network_errors_are_not_reported_as_up_to_date(monkeypatch, error, expected):
    def fail(*a, **k):
        raise error
    monkeypatch.setattr(updates, "urlopen", fail)
    message, url = updates.check_release("owner/reactor")
    assert expected in message and url is None


@pytest.mark.parametrize("confirm", [False, True])
def test_download_page_requires_confirmation(monkeypatch, confirm):
    opened = []
    monkeypatch.setattr(desktop, "check_release", lambda: ("Open download page?", "https://github.com/owner/reactor/releases/tag/v0.2.0"))
    monkeypatch.setattr(desktop.webbrowser, "open", opened.append)
    window = SimpleNamespace(create_confirmation_dialog=lambda *args: confirm)
    lock = Lock()
    desktop.show_updates(window, lambda: False, lock)
    assert bool(opened) is confirm
    assert not lock.locked()


def test_quit_during_lookup_suppresses_the_dialog(monkeypatch):
    closed = False
    def check():
        nonlocal closed
        closed = True
        return "Finished", None
    monkeypatch.setattr(desktop, "check_release", check)
    window = SimpleNamespace(run_js=lambda *a: pytest.fail("Dialog after quit"))
    lock = Lock()
    desktop.show_updates(window, lambda: closed, lock)
    assert not lock.locked()


def test_duplicate_check_does_not_start_another_request(monkeypatch):
    monkeypatch.setattr(desktop, "check_release", lambda: pytest.fail("Duplicate request"))
    lock = Lock()
    lock.acquire()
    desktop.show_updates(None, lambda: False, lock)
    assert lock.locked()
    lock.release()


def test_unconfigured_check_displays_installed_version(monkeypatch):
    messages = []
    monkeypatch.setattr(desktop, "check_release", lambda: updates.check_release(""))
    desktop.show_updates(SimpleNamespace(run_js=messages.append), lambda: False, Lock())
    assert __version__ in messages[0] and "No release location" in messages[0]
