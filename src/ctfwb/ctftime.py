"""Fetch and parse public CTFtime event pages."""

from __future__ import annotations

import asyncio
import re
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import TypedDict
from urllib.parse import urljoin, urlsplit


class CTFTimeDetails(TypedDict):
    """CTF fields that can be populated from a CTFtime event page."""

    name: str
    year: int | None
    platform_url: str | None
    description: str


class CTFTimeLookupError(Exception):
    """An event URL could not be fetched or did not contain usable data."""


_CTFTIME_HOSTS = {"ctftime.org", "www.ctftime.org"}
_MAX_RESPONSE_BYTES = 1_048_576
_REQUEST_TIMEOUT_SECONDS = 10
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def _validate_event_url(url: str) -> str:
    url = url.strip()
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise CTFTimeLookupError("Enter a valid CTFtime event URL.") from exc

    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or hostname not in _CTFTIME_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise CTFTimeLookupError(
            "Use an HTTPS CTFtime event URL, such as https://ctftime.org/event/123/."
        )

    match = re.fullmatch(r"/event/([0-9]+)/?", parsed.path)
    if match is None:
        raise CTFTimeLookupError("The URL must point to a CTFtime event page.")
    return f"https://ctftime.org/event/{match.group(1)}/"


def _is_safe_redirect(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() in _CTFTIME_HOSTS
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
    )


class _CTFTimeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_safe_redirect(newurl):
            raise CTFTimeLookupError("CTFtime redirected to an unsupported URL.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _EventPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.open_graph_title = ""
        self.meta_description = ""
        self.description_parts: list[str] = []
        self.official_url: str | None = None
        self._title_parts: list[str] = []
        self._in_title = False
        self._description_depth = 0
        self._in_paragraph = False
        self._paragraph_parts: list[str] = []
        self._paragraph_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "meta":
            if attributes.get("property") == "og:title":
                self.open_graph_title = attributes.get("content") or ""
            elif attributes.get("name") == "description":
                self.meta_description = attributes.get("content") or ""

        if tag == "h2" and not self.title:
            self._in_title = True

        if tag == "p":
            self._in_paragraph = True
            self._paragraph_parts = []
            self._paragraph_links = []
        elif tag == "a" and self._in_paragraph and attributes.get("href"):
            self._paragraph_links.append(attributes["href"] or "")

        if self._description_depth:
            if tag in {"br", "p"}:
                self.description_parts.append("\n")
            if tag not in _VOID_TAGS:
                self._description_depth += 1
        elif tag == "div" and attributes.get("id") == "id_description":
            self._description_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self._in_title:
            self.title = "".join(self._title_parts).strip()
            self._in_title = False

        if tag == "p" and self._in_paragraph:
            paragraph = " ".join("".join(self._paragraph_parts).split())
            if paragraph.lower().startswith("official url:") and self._paragraph_links:
                self.official_url = self._paragraph_links[0]
            self._in_paragraph = False

        if self._description_depth and tag not in _VOID_TAGS:
            if tag == "p":
                self.description_parts.append("\n")
            self._description_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._in_paragraph:
            self._paragraph_parts.append(data)
        if self._description_depth:
            self.description_parts.append(data)


def _normalized_text(parts: list[str]) -> str:
    lines = [" ".join(line.split()) for line in "".join(parts).splitlines()]
    return "\n".join(line for line in lines if line)


def _safe_official_url(source_url: str, href: str | None) -> str | None:
    if not href:
        return None
    try:
        candidate = urljoin(source_url, href.strip())
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return candidate


def parse_ctftime_html(html: str, source_url: str) -> CTFTimeDetails:
    """Extract a name, year, official URL, and description from an event page."""
    parser = _EventPageParser()
    parser.feed(html)
    parser.close()

    name = (parser.title or parser.open_graph_title).strip()
    name = re.sub(r"^CTFtime\.org\s*/\s*", "", name, flags=re.IGNORECASE).strip()
    if not name:
        raise CTFTimeLookupError("The CTFtime page did not contain an event name.")

    year_match = re.search(r"\b(?:19|20|21)\d{2}\b", name)
    description = (
        _normalized_text(parser.description_parts) or parser.meta_description.strip()
    )
    official_url = _safe_official_url(source_url, parser.official_url)

    return {
        "name": name,
        "year": int(year_match.group()) if year_match else None,
        "platform_url": official_url,
        "description": description,
    }


def _fetch_event(url: str) -> CTFTimeDetails:
    event_url = _validate_event_url(url)
    request = urllib.request.Request(
        event_url,
        headers={"User-Agent": "CTFWorkbench/0.1 (+https://ctftime.org/)"},
    )
    opener = urllib.request.build_opener(_CTFTimeRedirectHandler())
    try:
        with opener.open(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            content = response.read(_MAX_RESPONSE_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as exc:
        raise CTFTimeLookupError(f"CTFtime returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise CTFTimeLookupError("Could not fetch the CTFtime event page.") from exc

    if len(content) > _MAX_RESPONSE_BYTES:
        raise CTFTimeLookupError("The CTFtime event page is larger than 1 MiB.")
    try:
        html = content.decode(charset, errors="replace")
    except LookupError:
        html = content.decode("utf-8", errors="replace")
    return parse_ctftime_html(html, event_url)


async def fetch_ctftime_event(url: str) -> CTFTimeDetails:
    """Fetch and parse a CTFtime event page without blocking the TUI."""
    return await asyncio.to_thread(_fetch_event, url)
