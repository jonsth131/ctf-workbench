"""Guarded, read-only HTTP retrieval from CTFd API v1."""

from __future__ import annotations

import json
import math
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from typing import Any

from ctfwb.importers.json_import import (
    CTFdAuthenticationError,
    CTFdError,
    CTFdRateLimitError,
    ImportValidationError,
    validate_challenge_json,
)
from ctfwb.logging_setup import APP_LOGGER, log_debug_exception


def _response_page(document: object) -> tuple[list[dict[str, Any]], int | None]:
    if not isinstance(document, Mapping):
        raise CTFdError("CTFd returned a malformed challenge response")
    if document.get("success") is not True:
        raise CTFdError("CTFd returned an unsuccessful challenge response")
    try:
        validate_challenge_json(document)
    except ImportValidationError as exc:
        raise CTFdError(f"CTFd returned malformed challenge data: {exc}") from None
    raw_challenges = document.get("data")
    if not isinstance(raw_challenges, list):
        raise CTFdError("CTFd returned a malformed challenge response")
    challenges: list[dict[str, Any]] = []
    for challenge in raw_challenges:
        if not isinstance(challenge, Mapping):
            raise CTFdError("CTFd returned malformed challenge data")
        challenges.append(dict(challenge))

    pages: int | None = None
    meta = document.get("meta")
    pagination = meta.get("pagination") if isinstance(meta, Mapping) else None
    if isinstance(pagination, Mapping):
        raw_pages = pagination.get("pages", pagination.get("total_pages"))
        if raw_pages is not None:
            if type(raw_pages) is not int or raw_pages < 1:
                raise CTFdError("CTFd returned invalid pagination metadata")
            pages = raw_pages
    return challenges, pages


def _without_ctfd_download_token(file_url: str) -> str:
    """Drop the short-lived file-access token from CTFd's signed file URLs."""
    try:
        parsed = urllib.parse.urlsplit(file_url)
    except ValueError:
        raise CTFdError("CTFd returned an invalid artifact URL") from None
    if not parsed.query:
        return file_url
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() != "token"
    ]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")
    )


def _response_challenge_detail(
    document: object,
    summary: Mapping[str, Any],
    expected_id: str,
) -> dict[str, Any]:
    if not isinstance(document, Mapping) or document.get("success") is not True:
        raise CTFdError("CTFd returned an unsuccessful challenge detail response")
    detail = document.get("data")
    if not isinstance(detail, Mapping):
        raise CTFdError("CTFd returned malformed challenge details")

    raw_id = detail.get("id", detail.get("remote_id"))
    if raw_id is not None and str(raw_id).strip() != expected_id:
        raise CTFdError("CTFd returned details for a different challenge")

    challenge = dict(summary)
    challenge.update(detail)
    challenge.setdefault("id", expected_id)

    files = challenge.get("files")
    if isinstance(files, list):
        challenge["files"] = [
            _without_ctfd_download_token(file_url)
            if isinstance(file_url, str)
            else file_url
            for file_url in files
        ]

    try:
        record = validate_challenge_json([challenge])[0]
    except ImportValidationError as exc:
        raise CTFdError(f"CTFd returned malformed challenge details: {exc}") from None
    if record["remote_id"] != expected_id:
        raise CTFdError("CTFd returned details for a different challenge")
    return record


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent CTFd credentials from following a redirect to another host."""

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class _CTFdHTTPStatusError(CTFdError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"CTFd request failed with HTTP status {status}")


def _http_status_error(status: int) -> CTFdError:
    if status == 429:
        return CTFdRateLimitError("CTFd rate limit exceeded; retry later")
    if status == 401:
        return CTFdAuthenticationError("CTFd rejected the configured token")
    if status == 403:
        return CTFdError(
            "CTFd denied access to the challenge API (HTTP 403). Check that the "
            "API token's account can access challenges; event timing, team "
            "membership, email verification, or visibility settings may also "
            "restrict access."
        )
    if status == 404:
        return _CTFdHTTPStatusError(status)
    return CTFdError(f"CTFd request failed with HTTP status {status}")


def _request_json(
    request_opener: Any,
    url: str,
    origin: tuple[str, str, int],
    token: str,
    timeout: float,
    *,
    resource: str,
    body: Mapping[str, Any] | None = None,
) -> object:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={
            "Authorization": f"Token {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "CTF Workbench",
        },
        method="POST" if body is not None else "GET",
    )
    requested = urllib.parse.urlsplit(request.full_url)
    requested_origin = (
        requested.scheme.lower(),
        (requested.hostname or "").lower(),
        requested.port or 443,
    )
    if requested_origin != origin:
        raise CTFdError("CTFd request escaped the configured host")

    APP_LOGGER.debug("Requesting CTFd API %s %s", resource, url)
    try:
        response = request_opener.open(request, timeout=float(timeout))
        with response:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if type(status) is not int:
                raise CTFdError("CTFd returned an invalid HTTP status")
            if status < 200 or status >= 300:
                APP_LOGGER.debug("CTFd API returned HTTP status %s", status)
                raise _http_status_error(status)
            try:
                return json.loads(response.read())
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise CTFdError("CTFd returned invalid JSON") from None
    except urllib.error.HTTPError as exc:
        log_debug_exception("CTFd API HTTP request failed", exc)
        APP_LOGGER.debug("CTFd API returned HTTP status %s", exc.code)
        raise _http_status_error(exc.code) from None
    except (TimeoutError, socket.timeout) as exc:
        log_debug_exception("CTFd API request timed out", exc)
        raise CTFdError("CTFd request timed out") from None
    except urllib.error.URLError as exc:
        log_debug_exception("CTFd API connection failed", exc)
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise CTFdError("CTFd request timed out") from None
        raise CTFdError("CTFd server is unavailable") from None
    except CTFdError as exc:
        log_debug_exception("CTFd API request failed", exc)
        raise
    except Exception as exc:
        log_debug_exception("Unexpected CTFd API request failure", exc)
        if isinstance(exc, (TimeoutError, socket.timeout)):
            raise CTFdError("CTFd request timed out") from None
        raise CTFdError("CTFd server is unavailable") from None


def _request_context(
    base_url: str,
    token: str,
    timeout: float,
    opener: Any | None,
) -> tuple[
    urllib.parse.SplitResult,
    tuple[str, str, int],
    str,
    Any,
]:
    if not isinstance(base_url, str):
        raise CTFdError("CTFd base URL must use HTTPS")
    try:
        parsed = urllib.parse.urlsplit(base_url)
        port = parsed.port
    except ValueError:
        raise CTFdError("CTFd base URL is invalid") from None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise CTFdError(
            "CTFd base URL must be an HTTPS origin or path without credentials"
        )
    if not isinstance(token, str) or not token.strip():
        raise CTFdError("CTFd token must be a non-empty string")
    if any(ord(character) < 32 or ord(character) == 127 for character in token):
        raise CTFdError("CTFd token contains invalid control characters")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
        or not math.isfinite(timeout)
    ):
        raise CTFdError("CTFd request timeout must be finite and greater than zero")
    origin = (parsed.scheme.lower(), parsed.hostname.lower(), port or 443)
    return (
        parsed,
        origin,
        parsed.path.rstrip("/"),
        opener or urllib.request.build_opener(_NoRedirectHandler()),
    )


def _fetch_ctfd_challenges_at_base_url(
    base_url: str,
    token: str,
    *,
    timeout: float = 10.0,
    opener: Any | None = None,
) -> list[dict[str, Any]]:
    """Fetch CTFd v1 challenge pages and per-challenge details over HTTPS.

    Sends ``Authorization: ****** only to the configured origin.
    Redirects are disabled so a server cannot redirect credentials elsewhere.
    Every request uses a finite timeout. An optional urllib-compatible opener
    exists for deterministic tests and must not be used to bypass host checks.
    Challenge file URLs are retained as metadata; the referenced files are not
    requested or downloaded.

    Raises typed CTFd errors for authentication rejection, rate limiting,
    other HTTP/API errors, network failures, timeouts, and malformed replies.
    Exception text intentionally excludes the token and request headers.
    """
    parsed, origin, base_path, request_opener = _request_context(
        base_url, token, timeout, opener
    )
    endpoint = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, f"{base_path}/api/v1/challenges", "", "")
    )
    raw_records: list[dict[str, Any]] = []
    page = 1
    known_pages: int | None = None
    visited: set[int] = set()

    while known_pages is None or page <= known_pages:
        if page in visited:
            raise CTFdError("CTFd pagination repeated a page")
        visited.add(page)
        url = endpoint if page == 1 else f"{endpoint}?page={page}"
        document = _request_json(
            request_opener, url, origin, token, timeout, resource="page"
        )
        records, reported_pages = _response_page(document)
        raw_records.extend(records)
        if reported_pages is not None:
            if known_pages is not None and reported_pages != known_pages:
                raise CTFdError("CTFd pagination metadata changed during retrieval")
            known_pages = reported_pages
        if known_pages is None:
            break
        page += 1

    try:
        summaries = validate_challenge_json({"success": True, "data": raw_records})
    except ImportValidationError as exc:
        raise CTFdError(f"CTFd returned malformed challenge data: {exc}") from None

    detailed_records: list[dict[str, Any]] = []
    for summary, raw_summary in zip(summaries, raw_records, strict=True):
        remote_id = summary["remote_id"]
        if remote_id is None:
            raise CTFdError("CTFd challenge list omitted a stable challenge ID")
        detail_id = urllib.parse.quote(remote_id, safe="")
        detail_url = f"{endpoint}/{detail_id}"
        document = _request_json(
            request_opener,
            detail_url,
            origin,
            token,
            timeout,
            resource="challenge",
        )
        detailed_records.append(
            _response_challenge_detail(document, raw_summary, remote_id)
        )
    return detailed_records


def download_ctfd_artifact(
    base_url: str,
    token: str,
    remote_id: str,
    artifact: Mapping[str, object],
    *,
    timeout: float = 10.0,
    opener: Any | None = None,
) -> Iterator[bytes]:
    """Stream one registered artifact using a fresh, same-origin CTFd file URL."""
    parsed, origin, base_path, request_opener = _request_context(
        base_url, token, timeout, opener
    )
    try:
        normalized = validate_challenge_json(
            [
                {
                    "id": remote_id,
                    "name": "artifact download",
                    "artifacts": [dict(artifact)],
                }
            ]
        )[0]["artifacts"][0]
    except (ImportValidationError, TypeError, ValueError) as exc:
        raise CTFdError(f"Invalid CTFd artifact reference: {exc}") from None
    filename = normalized["filename"]
    source_url = normalized.get("source_url")
    if not isinstance(remote_id, str) or not remote_id:
        raise CTFdError("CTFd challenge ID is invalid")

    def stream() -> Iterator[bytes]:
        endpoint = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, f"{base_path}/api/v1/challenges", "", "")
        )
        detail_url = f"{endpoint}/{urllib.parse.quote(remote_id, safe='')}"
        try:
            try:
                detail = _request_json(
                    request_opener,
                    detail_url,
                    origin,
                    token,
                    timeout,
                    resource="challenge",
                )
            except CTFdError:
                if not base_path:
                    raise
                root_endpoint = urllib.parse.urlunsplit(
                    (
                        parsed.scheme,
                        parsed.netloc,
                        "/api/v1/challenges",
                        "",
                        "",
                    )
                )
                detail = _request_json(
                    request_opener,
                    f"{root_endpoint}/{urllib.parse.quote(remote_id, safe='')}",
                    origin,
                    token,
                    timeout,
                    resource="challenge",
                )
            if not isinstance(detail, Mapping) or detail.get("success") is not True:
                raise CTFdError(
                    "CTFd returned an unsuccessful challenge detail response"
                )
            data = detail.get("data")
            if not isinstance(data, Mapping):
                raise CTFdError("CTFd returned malformed challenge details")
            returned_id = data.get("id", data.get("remote_id"))
            if returned_id is not None and str(returned_id).strip() != remote_id:
                raise CTFdError("CTFd returned details for a different challenge")
            files = data.get("files")
            if not isinstance(files, list):
                raise CTFdError("CTFd returned malformed challenge artifact references")

            candidate_urls = [
                file_url
                for file_url in files
                if isinstance(file_url, str)
                and (
                    (
                        isinstance(source_url, str)
                        and _without_ctfd_download_token(file_url) == source_url
                    )
                    or (
                        not isinstance(source_url, str)
                        and urllib.parse.unquote(
                            urllib.parse.urlsplit(file_url).path.rsplit("/", 1)[-1]
                        )
                        == filename
                    )
                )
            ]
            if len(candidate_urls) != 1:
                raise CTFdError(
                    f"CTFd no longer provides a unique file reference for {filename}"
                )
            download_url = urllib.parse.urljoin(
                f"{parsed.scheme}://{parsed.netloc}/", candidate_urls[0]
            )
            actual = urllib.parse.urlsplit(download_url)
            actual_origin = (
                actual.scheme.lower(),
                (actual.hostname or "").lower(),
                actual.port or 443,
            )
            if (
                actual_origin != origin
                or actual.scheme.lower() != "https"
                or actual.username is not None
                or actual.password is not None
                or actual.fragment
            ):
                raise CTFdError(
                    "CTFd artifact URL is outside the configured HTTPS host"
                )
            request = urllib.request.Request(
                download_url,
                headers={
                    "Authorization": f"Token {token}",
                    "Accept": "*/*",
                    "User-Agent": "CTF Workbench",
                },
                method="GET",
            )
            requested = urllib.parse.urlsplit(request.full_url)
            requested_origin = (
                requested.scheme.lower(),
                (requested.hostname or "").lower(),
                requested.port or 443,
            )
            if requested_origin != origin:
                raise CTFdError("CTFd artifact request escaped the configured host")

            APP_LOGGER.debug("Requesting CTFd artifact %s", filename)
            response = request_opener.open(request, timeout=float(timeout))
            with response:
                status = getattr(response, "status", None)
                if status is None:
                    status = response.getcode()
                if type(status) is not int:
                    raise CTFdError("CTFd returned an invalid HTTP status")
                if status < 200 or status >= 300:
                    APP_LOGGER.debug("CTFd artifact returned HTTP status %s", status)
                    raise _http_status_error(status)
                while chunk := response.read(64 * 1024):
                    yield chunk
        except urllib.error.HTTPError as exc:
            log_debug_exception("CTFd artifact HTTP request failed", exc)
            APP_LOGGER.debug("CTFd artifact returned HTTP status %s", exc.code)
            raise _http_status_error(exc.code) from None
        except (TimeoutError, socket.timeout) as exc:
            log_debug_exception("CTFd artifact request timed out", exc)
            raise CTFdError("CTFd artifact request timed out") from None
        except urllib.error.URLError as exc:
            log_debug_exception("CTFd artifact connection failed", exc)
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise CTFdError("CTFd artifact request timed out") from None
            raise CTFdError("CTFd server is unavailable") from None
        except CTFdError:
            raise
        except Exception as exc:
            log_debug_exception("Unexpected CTFd artifact request failure", exc)
            if isinstance(exc, (TimeoutError, socket.timeout)):
                raise CTFdError("CTFd artifact request timed out") from None
            raise CTFdError("CTFd artifact download failed") from None

    return stream()


def submit_ctfd_flag(
    base_url: str,
    token: str,
    remote_id: str,
    flag: str,
    *,
    timeout: float = 10.0,
    opener: Any | None = None,
) -> str:
    """Submit a flag to the configured CTFd instance and return its status."""
    parsed, origin, base_path, request_opener = _request_context(
        base_url, token, timeout, opener
    )
    if (
        not isinstance(remote_id, str)
        or not remote_id.strip().isascii()
        or not remote_id.strip().isdecimal()
    ):
        raise CTFdError("CTFd challenge ID is invalid")
    if not isinstance(flag, str) or not flag.strip():
        raise CTFdError("A non-empty flag is required")
    try:
        challenge_id = int(remote_id.strip())
    except ValueError:
        raise CTFdError("CTFd challenge ID is invalid") from None
    endpoint = urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"{base_path}/api/v1/challenges/attempt",
            "",
            "",
        )
    )
    body = {"challenge_id": challenge_id, "submission": flag}
    try:
        document = _request_json(
            request_opener,
            endpoint,
            origin,
            token,
            timeout,
            resource="flag attempt",
            body=body,
        )
    except _CTFdHTTPStatusError as error:
        if not base_path or error.status != 404:
            raise
        root_endpoint = urllib.parse.urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                "/api/v1/challenges/attempt",
                "",
                "",
            )
        )
        document = _request_json(
            request_opener,
            root_endpoint,
            origin,
            token,
            timeout,
            resource="flag attempt",
            body=body,
        )
    data = document.get("data") if isinstance(document, Mapping) else None
    if (
        not isinstance(document, Mapping)
        or document.get("success") is not True
        or not isinstance(data, Mapping)
        or not isinstance(data.get("status"), str)
    ):
        raise CTFdError("CTFd returned a malformed flag submission response")
    return data["status"]


def fetch_ctfd_challenges(
    base_url: str,
    token: str,
    *,
    timeout: float = 10.0,
    opener: Any | None = None,
) -> list[dict[str, Any]]:
    """Fetch CTFd challenges, retrying at the host root if a path fails.

    The API path is appended to the entered URL first. If retrieval fails and
    the URL includes a path, retry against the HTTPS host root. Redirects
    remain disabled and both attempts target the same host.
    """
    try:
        return _fetch_ctfd_challenges_at_base_url(
            base_url, token, timeout=timeout, opener=opener
        )
    except CTFdError as first_error:
        if not isinstance(base_url, str):
            raise first_error from None
        try:
            parsed = urllib.parse.urlsplit(base_url)
        except ValueError:
            raise first_error from None
        if parsed.query or parsed.fragment or not parsed.path.rstrip("/"):
            raise first_error from None
        APP_LOGGER.debug(
            "CTFd API request using the entered path failed; retrying at the host root: %s",
            first_error,
        )
        host_root = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        return _fetch_ctfd_challenges_at_base_url(
            host_root, token, timeout=timeout, opener=opener
        )
