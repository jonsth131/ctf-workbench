"""Tests for safe, fixture-based CTFtime event parsing."""

import asyncio
import io
import urllib.error
from email.message import Message

import pytest

from ctfwb import ctftime
from ctfwb.ctftime import CTFTimeLookupError, fetch_ctftime_event, parse_ctftime_html

EVENT_HTML = """
<!doctype html>
<html>
  <head>
    <meta property="og:title" content="DEF CON CTF Qualifier 2011">
    <meta name="description" content="Short page summary">
  </head>
  <body>
    <div class="page-header"><h2>DEF CON CTF Qualifier 2011</h2></div>
    <p>Official URL: <a href="http://ddtek.example/event">event site</a></p>
    <div id="id_description">
      <p>A Jeopardy-style event with <b>security</b> challenges.</p>
      <p>Registration starts soon.</p>
    </div>
    <script>ignored()</script>
  </body>
</html>
"""


def test_parse_ctftime_event_page_fields_as_plain_text() -> None:
    result = parse_ctftime_html(EVENT_HTML, "https://ctftime.org/event/123/")

    assert result == {
        "name": "DEF CON CTF Qualifier 2011",
        "year": 2011,
        "platform_url": "http://ddtek.example/event",
        "description": "A Jeopardy-style event with security challenges.\nRegistration starts soon.",
    }
    assert "<b>" not in result["description"]
    assert "ignored" not in result["description"]


def test_parse_uses_open_graph_title_and_meta_description_as_fallbacks() -> None:
    result = parse_ctftime_html(
        '<meta property="og:title" content="Spring CTF">'
        '<meta name="description" content="An event">',
        "https://ctftime.org/event/123/",
    )

    assert result == {
        "name": "Spring CTF",
        "year": None,
        "platform_url": None,
        "description": "An event",
    }


@pytest.mark.parametrize("href", ["javascript:alert(1)", "http://[invalid"])
def test_ignores_invalid_or_non_http_official_urls(href: str) -> None:
    html = (
        f'<h2>Example CTF 2025</h2><p>Official URL: <a href="{href}">event site</a></p>'
    )

    result = parse_ctftime_html(html, "https://ctftime.org/event/123/")

    assert result["platform_url"] is None


@pytest.mark.parametrize(
    "url",
    [
        "http://ctftime.org/event/123/",
        "https://ctftime.org.evil.example/event/123/",
        "https://example.com/event/123/",
        "https://user@ctftime.org/event/123/",
        "https://ctftime.org/event/123/?next=1",
        "https://ctftime.org/ctf/123/",
        "https://ctftime.org:8443/event/123/",
    ],
)
def test_rejects_non_event_or_unsafe_urls(url: str) -> None:
    with pytest.raises(CTFTimeLookupError):
        ctftime._validate_event_url(url)


def test_rejects_event_pages_without_a_name() -> None:
    with pytest.raises(CTFTimeLookupError, match="event name"):
        parse_ctftime_html(
            "<html><body>No title</body></html>", "https://ctftime.org/event/1/"
        )


class FakeResponse(io.BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.headers = Message()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class FakeOpener:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.request = None
        self.timeout = None

    def open(self, request, timeout: float) -> FakeResponse:
        self.request = request
        self.timeout = timeout
        return FakeResponse(self.content)


def test_fetch_event_uses_https_timeout_and_bounded_fixture_response(
    monkeypatch,
) -> None:
    opener = FakeOpener(EVENT_HTML.encode("utf-8"))
    monkeypatch.setattr(
        ctftime.urllib.request, "build_opener", lambda *_handlers: opener
    )

    result = asyncio.run(fetch_ctftime_event("https://www.ctftime.org/event/123"))

    assert result["name"] == "DEF CON CTF Qualifier 2011"
    assert opener.request.full_url == "https://ctftime.org/event/123/"
    assert opener.timeout == 10


def test_fetch_event_reports_network_errors(monkeypatch) -> None:
    class FailedOpener:
        def open(self, *_args, **_kwargs):
            raise urllib.error.URLError("offline")

    monkeypatch.setattr(
        ctftime.urllib.request, "build_opener", lambda *_handlers: FailedOpener()
    )

    with pytest.raises(CTFTimeLookupError, match="Could not fetch"):
        asyncio.run(fetch_ctftime_event("https://ctftime.org/event/123/"))
