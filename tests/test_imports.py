"""Contract tests for safe CTFd JSON planning and live retrieval."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from threading import Event

import pytest

from ctfwb.imports import (
    ConfirmedImportPlan,
    CTFdAuthenticationError,
    CTFdError,
    CTFdRateLimitError,
    ImportValidationError,
    create_import_plan,
    create_refresh_plan,
    download_ctfd_artifact,
    fetch_ctfd_challenges,
    submit_ctfd_flag,
    validate_challenge_json,
)
from ctfwb.logging_setup import close_file_logging, configure_file_logging
from ctfwb.storage import _validate_artifact


@pytest.fixture
def ctfd_export():
    """Load a representative, non-sensitive CTFd v1 challenge export."""
    fixture = Path(__file__).parent / "fixtures" / "ctfd" / "challenges.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, payload, *, status=200):
        self.status = status
        self.payload = payload
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        if isinstance(self.payload, bytes):
            data = self.payload
        else:
            data = json.dumps(self.payload).encode()
        if size < 0:
            return data
        chunk = data[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def getcode(self):
        return self.status


class FakeOpener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_parses_documented_export_and_api_shapes(ctfd_export):
    export = validate_challenge_json(ctfd_export)
    assert [challenge["remote_id"] for challenge in export] == ["41", None, "43"]
    assert export[0]["points"] == 50
    assert export[0]["artifacts"] == [
        {
            "filename": "welcome.txt",
            "original_filename": "welcome.txt",
            "source_url": "/files/welcome.txt",
        }
    ]
    assert (
        _validate_artifact(export[0]["artifacts"][0], Path("fixture"), 0)
        == export[0]["artifacts"][0]
    )

    api_response = {
        "success": True,
        "data": [ctfd_export["challenges"][0]],
        "meta": {"pagination": {"page": 1, "pages": 1}},
    }
    assert validate_challenge_json(json.dumps(api_response)) == [export[0]]
    assert (
        validate_challenge_json([ctfd_export["challenges"][1]])[0]["name"]
        == "Name-only"
    )


@pytest.mark.parametrize(
    "payload",
    [
        "{broken",
        {"success": False, "data": []},
        {"success": True, "data": {}},
        {"challenges": [{"id": 1, "name": " ", "value": 1}]},
        {"challenges": [{"name": "bad", "value": True}]},
    ],
)
def test_rejects_malformed_or_unsupported_json(payload):
    with pytest.raises(ImportValidationError):
        validate_challenge_json(payload)


def test_import_plan_identifies_remote_matches_and_never_auto_matches_names(
    ctfd_export,
):
    existing = [
        {"id": "local-a", "name": "Renamed locally", "remote_id": "41"},
        {"id": "local-b", "name": "Name-only", "remote_id": None},
        {"id": "local-c", "name": "NAME-ONLY", "remote_id": None},
    ]
    plan = create_import_plan(ctfd_export, existing)

    assert [record["name"] for record in plan.additions] == ["Another"]
    assert plan.remote_matches[0][0]["remote_id"] == "41"
    assert plan.remote_matches[0][1]["id"] == "local-a"
    assert len(plan.name_only_matches) == 1
    assert {candidate["id"] for candidate in plan.ambiguous_name_matches[0][1]} == {
        "local-b",
        "local-c",
    }
    confirmation = plan.confirm()
    assert isinstance(confirmation, ConfirmedImportPlan)
    assert confirmation.plan is plan


def test_name_only_single_match_is_still_a_suggestion_not_a_match():
    plan = create_import_plan(
        [{"name": "Same", "category": None, "points": 5}],
        [{"id": "local", "name": "Same", "remote_id": None}],
    )
    assert plan.additions == ()
    assert plan.remote_matches == ()
    assert len(plan.name_only_matches) == 1
    assert plan.ambiguous_name_matches == ()


def test_refresh_plan_preserves_local_fields_and_reuses_artifact_filename():
    existing = {
        "id": "local-id",
        "name": "Old name",
        "category": "web",
        "points": 10,
        "description": "Old description",
        "artifacts": [
            {
                "filename": "payload.zip",
                "original_filename": "payload.zip",
                "source_url": "/files/old.zip",
            },
            {"filename": "local.txt"},
        ],
        "status": "solved",
        "flag": "flag{local}",
        "source": "ctfd",
        "remote_id": "41",
        "solver": {"relative_path": "solve.py"},
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    plan = create_refresh_plan(
        [
            {
                "id": 41,
                "name": "New name",
                "category": "crypto",
                "value": 25,
                "description": "New description",
                "files": ["/files/new/payload.zip"],
            },
            {"id": 42, "name": "New challenge", "value": 5},
        ],
        [existing],
    )

    assert len(plan.updates) == 1
    merged = plan.updates[0][2]
    assert merged["name"] == "New name"
    assert merged["status"] == "solved"
    assert merged["flag"] == "flag{local}"
    assert merged["solver"] == {"relative_path": "solve.py"}
    assert [item["filename"] for item in merged["artifacts"]] == [
        "payload.zip",
        "local.txt",
    ]
    assert merged["artifacts"][0]["source_url"] == "/files/new/payload.zip"
    assert len(plan.additions) == 1


def test_json_refresh_matches_only_json_imports_and_reports_missing_records():
    json_challenge = {
        "id": "local-json",
        "name": "Old JSON title",
        "category": "web",
        "points": 10,
        "description": "old",
        "artifacts": [],
        "status": "unsolved",
        "flag": None,
        "source": "json_import",
        "remote_id": "41",
        "solver": None,
    }
    ctfd_challenge = {
        **json_challenge,
        "id": "local-ctfd",
        "source": "ctfd",
    }
    missing_challenge = {
        **json_challenge,
        "id": "missing-json",
        "name": "No longer listed",
        "remote_id": "99",
    }

    plan = create_refresh_plan(
        [
            {"id": "41", "name": "Updated JSON title", "value": 20},
            {"id": "42", "name": "New JSON challenge", "value": 5},
        ],
        [json_challenge, ctfd_challenge, missing_challenge],
        source="json_import",
    )

    assert len(plan.updates) == 1
    assert plan.updates[0][1]["id"] == "local-json"
    assert plan.updates[0][2]["name"] == "Updated JSON title"
    assert [row["remote_id"] for row in plan.additions] == ["42"]
    assert [row["id"] for row in plan.missing] == ["missing-json"]


def test_json_refresh_requires_stable_remote_ids_and_valid_source():
    with pytest.raises(ImportValidationError, match="stable remote ID"):
        create_refresh_plan(
            [{"name": "No stable ID"}],
            [],
            source="json_import",
        )

    with pytest.raises(ImportValidationError, match="refresh source"):
        create_refresh_plan([], [], source="manual")


def test_download_ctfd_artifact_uses_fresh_signed_same_origin_reference():
    opener = FakeOpener(
        [
            FakeResponse(
                {
                    "success": True,
                    "data": {
                        "id": 41,
                        "files": ["/files/payload.zip?token=short-lived"],
                    },
                }
            ),
            FakeResponse(b"artifact bytes"),
        ]
    )

    chunks = download_ctfd_artifact(
        "https://ctf.example",
        "api-token",
        "41",
        {
            "filename": "payload.zip",
            "original_filename": "payload.zip",
            "source_url": "/files/payload.zip",
        },
        opener=opener,
    )

    assert b"".join(chunks) == b"artifact bytes"
    assert len(opener.requests) == 2
    assert opener.requests[0].full_url.endswith("/api/v1/challenges/41")
    assert opener.requests[1].full_url == (
        "https://ctf.example/files/payload.zip?token=short-lived"
    )
    assert opener.requests[0].get_header("Authorization") == "Token api-token"
    assert opener.requests[1].get_header("Authorization") == "Token api-token"
    assert opener.timeouts == [10.0, 10.0]


def test_download_ctfd_artifact_rejects_cross_origin_file_reference():
    opener = FakeOpener(
        [
            FakeResponse(
                {
                    "success": True,
                    "data": {
                        "id": 41,
                        "files": ["https://other.example/payload.zip"],
                    },
                }
            )
        ]
    )
    with pytest.raises(CTFdError, match="outside the configured HTTPS host"):
        b"".join(
            download_ctfd_artifact(
                "https://ctf.example",
                "api-token",
                "41",
                {
                    "filename": "payload.zip",
                    "source_url": "https://other.example/payload.zip",
                },
                opener=opener,
            )
        )
    assert len(opener.requests) == 1


def test_download_ctfd_artifact_reports_http_failure_without_signed_url():
    signed_url_token = "temporary-signed-token"
    opener = FakeOpener(
        [
            FakeResponse(
                {
                    "success": True,
                    "data": {
                        "id": 41,
                        "files": [f"/files/payload.zip?token={signed_url_token}"],
                    },
                }
            ),
            urllib.error.HTTPError(
                f"https://ctf.example/files/payload.zip?token={signed_url_token}",
                503,
                "unavailable",
                {},
                io.BytesIO(b""),
            ),
        ]
    )

    with pytest.raises(CTFdError, match="HTTP status 503") as error:
        b"".join(
            download_ctfd_artifact(
                "https://ctf.example",
                "api-token",
                "41",
                {
                    "filename": "payload.zip",
                    "source_url": "/files/payload.zip",
                },
                opener=opener,
            )
        )

    assert signed_url_token not in str(error.value)
    assert len(opener.requests) == 2
    assert signed_url_token in opener.requests[1].full_url


def test_duplicate_remote_ids_are_rejected_before_planning():
    with pytest.raises(ImportValidationError, match="duplicate remote challenge ID"):
        validate_challenge_json(
            [
                {"id": 7, "name": "First"},
                {"id": "7", "name": "Second"},
            ]
        )


def test_fetches_all_reported_pages_with_ctfd_token_to_https_configured_host():
    first = FakeResponse(
        {
            "success": True,
            "data": [{"id": 1, "name": "one", "value": 1}],
            "meta": {"pagination": {"page": 1, "pages": 2}},
        }
    )
    second = FakeResponse(
        {
            "success": True,
            "data": [{"id": 2, "name": "two", "value": 2}],
            "meta": {"pagination": {"page": 2, "pages": 2}},
        }
    )
    first_detail = FakeResponse(
        {
            "success": True,
            "data": {
                "id": 1,
                "name": "one",
                "value": 1,
                "description": "Detailed description",
                "files": ["/files/one.txt?token=temporary-file-token"],
            },
        }
    )
    second_detail = FakeResponse(
        {
            "success": True,
            "data": {
                "id": 2,
                "name": "two",
                "value": 2,
                "description": "Another description",
                "files": [],
            },
        }
    )
    opener = FakeOpener([first, second, first_detail, second_detail])
    records = fetch_ctfd_challenges(
        "https://ctf.example/base/", "secret-token", timeout=3.5, opener=opener
    )

    assert [record["remote_id"] for record in records] == ["1", "2"]
    assert records[0]["description"] == "Detailed description"
    assert records[0]["artifacts"][0]["source_url"] == "/files/one.txt"
    assert "temporary-file-token" not in str(records)
    assert opener.requests[0].full_url == "https://ctf.example/base/api/v1/challenges"
    assert opener.requests[1].full_url.endswith("/api/v1/challenges?page=2")
    assert opener.requests[2].full_url == (
        "https://ctf.example/base/api/v1/challenges/1"
    )
    assert opener.requests[3].full_url == (
        "https://ctf.example/base/api/v1/challenges/2"
    )
    assert all("/files/" not in request.full_url for request in opener.requests)
    assert [request.get_header("Authorization") for request in opener.requests] == [
        "Token secret-token",
        "Token secret-token",
        "Token secret-token",
        "Token secret-token",
    ]
    assert [request.get_header("Content-type") for request in opener.requests] == [
        "application/json"
    ] * 4
    assert [request.get_header("User-agent") for request in opener.requests] == [
        "CTF Workbench"
    ] * 4
    assert opener.timeouts == [3.5] * 4


def test_rejects_details_for_a_different_challenge_id():
    opener = FakeOpener(
        [
            FakeResponse(
                {
                    "success": True,
                    "data": [{"id": 7, "name": "expected", "value": 5}],
                }
            ),
            FakeResponse(
                {
                    "success": True,
                    "data": {"id": 8, "name": "unexpected", "value": 5},
                }
            ),
        ]
    )

    with pytest.raises(CTFdError, match="different challenge"):
        fetch_ctfd_challenges("https://ctf.example", "secret-token", opener=opener)


@pytest.mark.parametrize("page_path", ["/challenges", "/users/profile/"])
def test_failed_page_path_retries_api_at_host_root(page_path):
    first_failure = urllib.error.HTTPError(
        "https://demo.ctfd.io", 404, "not found", {}, io.BytesIO(b"")
    )
    response = FakeResponse(
        {
            "success": True,
            "data": [{"id": 9, "name": "root retry", "value": 10}],
            "meta": {"pagination": {"page": 1, "pages": 1}},
        }
    )
    detail = FakeResponse(
        {
            "success": True,
            "data": {
                "id": 9,
                "name": "root retry",
                "value": 10,
                "description": "Fetched at the host root.",
            },
        }
    )
    opener = FakeOpener([first_failure, response, detail])

    records = fetch_ctfd_challenges(
        f"https://demo.ctfd.io{page_path}", "secret-token", opener=opener
    )

    assert [record["remote_id"] for record in records] == ["9"]
    assert opener.requests[0].full_url == (
        f"https://demo.ctfd.io{page_path.rstrip('/')}/api/v1/challenges"
    )
    assert opener.requests[1].full_url == "https://demo.ctfd.io/api/v1/challenges"
    assert opener.requests[2].full_url == "https://demo.ctfd.io/api/v1/challenges/9"
    assert [request.get_header("Authorization") for request in opener.requests] == [
        "Token secret-token",
        "Token secret-token",
        "Token secret-token",
    ]


def test_ctfd_files_become_storage_safe_artifacts_without_downloading():
    normalized = validate_challenge_json(
        {
            "challenges": [
                {
                    "id": 8,
                    "name": "Files",
                    "files": [
                        "/files/../../payload%3F.zip",
                        "https://cdn.example/data%20set.bin",
                    ],
                }
            ]
        }
    )[0]
    artifacts = normalized["artifacts"]

    assert artifacts[0] == {
        "filename": "payload_.zip",
        "original_filename": "payload?.zip",
        "source_url": "/files/../../payload%3F.zip",
    }
    assert artifacts[1] == {
        "filename": "data set.bin",
        "original_filename": "data set.bin",
        "source_url": "https://cdn.example/data%20set.bin",
    }
    for index, artifact in enumerate(artifacts):
        assert _validate_artifact(artifact, Path("fixture"), index) == artifact


def test_sanitized_artifact_filename_collisions_get_unique_names():
    normalized = validate_challenge_json(
        {
            "challenges": [
                {
                    "id": 8,
                    "name": "Colliding files",
                    "files": [
                        "/files/payload%3F.zip",
                        "/files/payload%2A.zip",
                        "/files/PAYLOAD_.ZIP",
                    ],
                }
            ]
        }
    )[0]["artifacts"]

    assert [item["filename"] for item in normalized] == [
        "payload_.zip",
        "payload_-2.zip",
        "PAYLOAD_-3.ZIP",
    ]
    assert [item["original_filename"] for item in normalized] == [
        "payload?.zip",
        "payload*.zip",
        "PAYLOAD_.ZIP",
    ]
    for index, artifact in enumerate(normalized):
        assert _validate_artifact(artifact, Path("fixture"), index) == artifact


@pytest.mark.parametrize(
    "file_reference",
    [
        "",
        "/files/",
        "/files/%GG",
        "//outside.example/file",
        "javascript:alert(1)",
        "https://user:password@cdn.example/file",
        "https://cdn.example",
        "/files/%00evil",
    ],
)
def test_rejects_malformed_ctfd_file_urls_and_names(file_reference):
    with pytest.raises(ImportValidationError):
        validate_challenge_json(
            {"challenges": [{"id": 1, "name": "Bad file", "files": [file_reference]}]}
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://ctf.example",
        "https://user:pass@ctf.example",
        "https://ctf.example?token=secret",
        "https://",
    ],
)
def test_rejects_non_https_or_credential_bearing_base_urls(url):
    with pytest.raises(CTFdError):
        fetch_ctfd_challenges(url, "token", opener=FakeOpener([]))


@pytest.mark.parametrize(
    "token", ["\r\nX-Injected: yes", "token\tvalue", "bad\x7fvalue"]
)
def test_rejects_control_characters_in_api_tokens(token):
    with pytest.raises(CTFdError, match="control characters"):
        fetch_ctfd_challenges("https://ctf.example", token, opener=FakeOpener([]))


@pytest.mark.parametrize(
    "code,error_type",
    [
        (401, CTFdAuthenticationError),
        (403, CTFdError),
        (429, CTFdRateLimitError),
        (503, CTFdError),
    ],
)
def test_http_failures_are_classified_without_exposing_token(code, error_type):
    opener = FakeOpener(
        [
            urllib.error.HTTPError(
                "https://ctf.example", code, "failure", {}, io.BytesIO(b"secret-token")
            )
        ]
    )
    with pytest.raises(error_type) as error:
        fetch_ctfd_challenges("https://ctf.example", "secret-token", opener=opener)
    assert type(error.value) is error_type
    assert "secret-token" not in str(error.value)
    if code == 403:
        assert "visibility settings" in str(error.value)
        assert "rejected the configured token" not in str(error.value)


def test_debug_http_failure_logs_status_and_trace_without_response_body(tmp_path):
    log_path = configure_file_logging(tmp_path / "logs", debug=True)
    opener = FakeOpener(
        [
            urllib.error.HTTPError(
                "https://ctf.example/api/v1/challenges",
                401,
                "Unauthorized",
                {},
                io.BytesIO(b"private response secret-token"),
            )
        ]
    )
    try:
        with pytest.raises(CTFdAuthenticationError):
            fetch_ctfd_challenges("https://ctf.example", "secret-token", opener=opener)
    finally:
        close_file_logging()

    log_contents = log_path.read_text(encoding="utf-8")
    assert "CTFd API returned HTTP status 401" in log_contents
    assert "CTFd API HTTP request failed (HTTPError)" in log_contents
    assert "_request_json" in log_contents
    assert "private response" not in log_contents
    assert "secret-token" not in log_contents


def test_handles_timeout_and_unavailable_server_without_leaking_details():
    timeout_opener = FakeOpener([TimeoutError("secret-token")])
    with pytest.raises(CTFdError, match="timed out") as error:
        fetch_ctfd_challenges(
            "https://ctf.example", "secret-token", opener=timeout_opener
        )
    assert "secret-token" not in str(error.value)

    unavailable = FakeOpener([urllib.error.URLError("secret-token")])
    with pytest.raises(CTFdError, match="unavailable") as error:
        fetch_ctfd_challenges("https://ctf.example", "secret-token", opener=unavailable)
    assert "secret-token" not in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        {"success": False, "data": []},
        {
            "success": True,
            "data": [{"name": "missing id allowed", "value": "not a number"}],
        },
    ],
)
def test_rejects_malformed_ctfd_responses(payload):
    with pytest.raises(CTFdError):
        fetch_ctfd_challenges(
            "https://ctf.example", "token", opener=FakeOpener([FakeResponse(payload)])
        )


def test_rejects_invalid_pagination_and_nonfinite_timeout():
    opener = FakeOpener(
        [
            FakeResponse(
                {
                    "success": True,
                    "data": [],
                    "meta": {"pagination": {"pages": -1}},
                }
            )
        ]
    )
    with pytest.raises(CTFdError, match="pagination"):
        fetch_ctfd_challenges("https://ctf.example", "token", opener=opener)
    with pytest.raises(CTFdError, match="finite"):
        fetch_ctfd_challenges("https://ctf.example", "token", timeout=float("inf"))


def test_ctfd_fetch_stops_after_cancellation_between_pages():
    cancel_event = Event()

    class CancelAfterPageOpener(FakeOpener):
        def open(self, request, timeout):
            response = super().open(request, timeout)
            cancel_event.set()
            return response

    opener = CancelAfterPageOpener(
        [
            FakeResponse(
                {
                    "success": True,
                    "data": [],
                    "meta": {"pagination": {"page": 1, "pages": 2}},
                }
            )
        ]
    )

    with pytest.raises(CTFdError, match="cancelled"):
        fetch_ctfd_challenges(
            "https://ctf.example",
            "token",
            opener=opener,
            cancel_event=cancel_event,
        )

    assert len(opener.requests) == 1


def test_submit_ctfd_flag_posts_to_configured_https_origin():
    opener = FakeOpener(
        [FakeResponse({"success": True, "data": {"status": "correct"}})]
    )

    assert (
        submit_ctfd_flag(
            "https://ctf.example/event",
            "secret-token",
            "41",
            "flag{private}",
            opener=opener,
        )
        == "correct"
    )

    request = opener.requests[0]
    assert request.full_url == "https://ctf.example/event/api/v1/challenges/attempt"
    assert request.method == "POST"
    assert request.get_header("Authorization") == "Token secret-token"
    assert json.loads(request.data) == {
        "challenge_id": 41,
        "submission": "flag{private}",
    }
    assert opener.timeouts == [10.0]


def test_submit_ctfd_flag_retries_at_same_host_root_after_path_404():
    missing_path = urllib.error.HTTPError(
        "https://ctf.example/event/api/v1/challenges/attempt",
        404,
        "not found",
        {},
        io.BytesIO(b""),
    )
    opener = FakeOpener(
        [missing_path, FakeResponse({"success": True, "data": {"status": "correct"}})]
    )

    assert (
        submit_ctfd_flag(
            "https://ctf.example/event",
            "token",
            "41",
            "flag{x}",
            opener=opener,
        )
        == "correct"
    )
    assert [request.full_url for request in opener.requests] == [
        "https://ctf.example/event/api/v1/challenges/attempt",
        "https://ctf.example/api/v1/challenges/attempt",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"success": False, "data": {"status": "incorrect"}},
        {"success": True, "data": {}},
        {"success": True, "data": {"status": 1}},
    ],
)
def test_submit_ctfd_flag_rejects_malformed_responses(payload):
    with pytest.raises(CTFdError, match="malformed flag submission"):
        submit_ctfd_flag(
            "https://ctf.example",
            "token",
            "41",
            "flag{private}",
            opener=FakeOpener([FakeResponse(payload)]),
        )


def test_submit_ctfd_flag_rejects_invalid_remote_id_before_request():
    opener = FakeOpener([])
    with pytest.raises(CTFdError, match="challenge ID"):
        submit_ctfd_flag(
            "https://ctf.example", "token", "not-a-number", "flag{x}", opener=opener
        )
    assert opener.requests == []
