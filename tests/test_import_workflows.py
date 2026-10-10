"""End-to-end keyboard workflows for CTFd and JSON challenge imports."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from textual.widgets import Button, Input, ListView, Static, TextArea

from ctfwb import CTFWorkbenchApp, DataStore, generate_id
from ctfwb.app import CTFChallengeScreen, ImportJSONDialog, RefreshSourceDialog
from ctfwb.importers import CTFdError
from ctfwb.storage import DataFileError, utc_timestamp


def _seed_store(tmp_path, challenges=()):
    store = DataStore(tmp_path / "user-data")
    ctf_id = generate_id()
    timestamp = utc_timestamp()
    store.save_ctfs(
        [
            {
                "id": ctf_id,
                "name": "Import CTF",
                "year": 2026,
                "platform_url": "https://ctfd.example",
                "description": "",
                "source": "manual",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        ]
    )
    store.load_challenges(ctf_id)
    if challenges:
        store.save_challenges(ctf_id, challenges)
    return store, ctf_id


def _challenge(
    name: str,
    *,
    remote_id: str | None = None,
    status: str = "unsolved",
    flag: str | None = None,
):
    timestamp = utc_timestamp()
    return {
        "id": generate_id(),
        "name": name,
        "category": None,
        "points": None,
        "description": "Local details",
        "artifacts": [],
        "status": status,
        "flag": flag,
        "source": "manual",
        "remote_id": remote_id,
        "solver": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


async def _open_challenge_screen(app, pilot):
    await pilot.press("enter")
    await pilot.pause()


async def _open_json_preview(app, pilot, json_text: str):
    await pilot.press("m")
    await pilot.click("#import-json-source")
    app.screen.query_one("#import-json-text", TextArea).text = json_text
    await pilot.click("#load-import-json")


def test_json_import_preview_can_be_cancelled_then_confirmed(tmp_path):
    async def exercise() -> None:
        fixture = Path(__file__).parent / "fixtures" / "ctfd" / "challenges.json"
        json_text = fixture.read_text(encoding="utf-8")
        existing = [
            _challenge(
                "Renamed welcome", remote_id="41", status="solved", flag="flag{local}"
            ),
            _challenge("Name-only", status="in_progress"),
        ]
        store, ctf_id = _seed_store(tmp_path, existing)
        app = CTFWorkbenchApp(data_store=store)

        async with app.run_test() as pilot:
            await _open_challenge_screen(app, pilot)
            await _open_json_preview(app, pilot, json_text)
            preview = str(
                app.screen.query_one("#import-preview-content", Static).render()
            )
            assert app.screen.query_one("#confirm-import", Button).has_focus
            assert "Challenges to add: 2" in preview
            assert "Already present by remote ID (unchanged): 1" in preview
            assert (
                "Name-only suggestions (will be added separately, not merged): 1"
                in preview
            )
            assert "Renamed welcome" in preview
            assert len(store.load_challenges(ctf_id)) == 2

            await pilot.click("#cancel-import-preview")
            await pilot.pause()
            assert len(store.load_challenges(ctf_id)) == 2

            await _open_json_preview(app, pilot, json_text)
            await pilot.press("enter")
            await pilot.pause()

            records = store.load_challenges(ctf_id)
            assert len(records) == 4
            local_match = next(
                record for record in records if record["remote_id"] == "41"
            )
            assert local_match["name"] == "Renamed welcome"
            assert local_match["status"] == "solved"
            assert local_match["flag"] == "flag{local}"
            assert sum(record["name"] == "Name-only" for record in records) == 2
            added = next(record for record in records if record["remote_id"] == "43")
            assert added["source"] == "json_import"
            assert added["points"] == 100
            assert added["artifacts"] == []
            assert "Imported 2 challenge(s)" in str(
                app.screen.query_one("#log-message", Static).render()
            )
            assert len(app.screen.query_one("#challenge-list", ListView).children) == 4

    asyncio.run(exercise())


def test_pasted_json_validation_keeps_dialog_open_on_invalid_input(tmp_path):
    async def exercise() -> None:
        fixture = Path(__file__).parent / "fixtures" / "ctfd" / "challenges.json"
        store, _ = _seed_store(tmp_path)
        app = CTFWorkbenchApp(data_store=store)

        async with app.run_test() as pilot:
            await _open_challenge_screen(app, pilot)
            await pilot.press("m")
            await pilot.pause()
            await pilot.click("#import-json-source")
            await pilot.pause()
            text_area = app.screen.query_one("#import-json-text", TextArea)
            text_area.text = "{ invalid"
            await pilot.click("#load-import-json")
            await pilot.pause()

            assert isinstance(app.screen, ImportJSONDialog)
            assert "invalid challenge JSON" in str(
                app.screen.query_one("#import-json-error", Static).render()
            )

            text_area.text = fixture.read_text(encoding="utf-8")
            await pilot.pause()
            await pilot.click("#load-import-json")
            await pilot.pause()
            await pilot.pause()
            app.screen.query_one("#import-preview-content", Static)

    asyncio.run(exercise())


def test_ctfd_import_masks_and_saves_host_bound_token_and_confirms(
    tmp_path, monkeypatch
):
    async def exercise() -> None:
        store, ctf_id = _seed_store(tmp_path)
        requests: list[tuple[str, str]] = []

        def fetch(base_url: str, token: str):
            requests.append((base_url, token))
            return [
                {
                    "remote_id": "ctfd-17",
                    "name": "API challenge",
                    "category": "web",
                    "points": 75,
                    "description": "Imported text.",
                    "artifacts": [
                        {
                            "filename": "payload.zip",
                            "original_filename": "payload.zip",
                            "source_url": "/files/payload.zip",
                        }
                    ],
                }
            ]

        monkeypatch.setattr("ctfwb.ui.dialogs.fetch_ctfd_challenges", fetch)
        app = CTFWorkbenchApp(data_store=store)

        async with app.run_test() as pilot:
            await _open_challenge_screen(app, pilot)
            await pilot.press("m")
            await pilot.click("#import-ctfd-source")
            app.screen.query_one(
                "#ctfd-import-url", Input
            ).value = "https://ctfd.example/challenges/"
            token_input = app.screen.query_one("#ctfd-import-token", Input)
            assert token_input.password
            assert not app.screen.query("#ctfd-import-info")
            assert token_input.value == ""
            token_input.value = "sensitive-test-token"
            await pilot.click("#fetch-ctfd-challenges")
            await pilot.pause()

            assert requests == [
                ("https://ctfd.example/challenges/", "sensitive-test-token")
            ]
            credentials_path = store.data_dir / "ctfs" / ctf_id / "token.json"
            assert json.loads(credentials_path.read_text(encoding="utf-8")) == {
                "base_url": "https://ctfd.example/challenges",
                "token": "sensitive-test-token",
            }
            assert "API challenge" in str(
                app.screen.query_one("#import-preview-content", Static).render()
            )

            await pilot.click("#confirm-import")
            await pilot.pause()
            assert store.load_ctfs()[0]["platform_url"] == (
                "https://ctfd.example/challenges/"
            )
            saved = store.load_challenges(ctf_id)[0]
            assert saved["name"] == "API challenge"
            assert saved["source"] == "ctfd"
            assert saved["remote_id"] == "ctfd-17"
            assert saved["artifacts"][0]["filename"] == "payload.zip"
            assert "sensitive-test-token" not in str(
                app.screen.query_one("#log-message", Static).render()
            )

    asyncio.run(exercise())


def test_saved_ctfd_token_is_prefilled_and_cleared_when_url_changes(tmp_path):
    async def exercise() -> None:
        store, ctf_id = _seed_store(tmp_path)
        store.save_ctfd_token(ctf_id, "https://ctfd.example", "test-saved-token")
        app = CTFWorkbenchApp(data_store=store)

        async with app.run_test() as pilot:
            await _open_challenge_screen(app, pilot)
            await pilot.press("m")
            await pilot.click("#import-ctfd-source")
            token_input = app.screen.query_one("#ctfd-import-token", Input)
            url_input = app.screen.query_one("#ctfd-import-url", Input)
            assert token_input.password
            assert token_input.value == "test-saved-token"
            assert not app.screen.query("#ctfd-import-info")

            url_input.value = "https://ctfd.example/"
            await pilot.pause()
            assert token_input.value == "test-saved-token"
            url_input.value = "https://other.example"
            await pilot.pause()
            assert token_input.value == ""

    asyncio.run(exercise())


def test_ctfd_refresh_previews_and_preserves_local_challenge_fields(
    tmp_path, monkeypatch
):
    async def exercise() -> None:
        existing = _challenge(
            "Old title", remote_id="41", status="solved", flag="flag{local}"
        )
        existing.update(
            {
                "source": "ctfd",
                "artifacts": [{"filename": "local.txt"}],
                "solver": {"file_type": "python", "relative_path": "solve.py"},
            }
        )
        missing = _challenge("Offline challenge", remote_id="99")
        missing["source"] = "ctfd"
        store, ctf_id = _seed_store(tmp_path, [existing, missing])
        platform_url = "https://ctfd.example"
        store.save_ctfd_token(ctf_id, platform_url, "refresh-token")
        calls = []

        def fetch(base_url, token):
            calls.append((base_url, token))
            return [
                {
                    "remote_id": "41",
                    "name": "Updated title",
                    "category": "crypto",
                    "points": 250,
                    "description": "Updated remote details",
                    "artifacts": [
                        {
                            "filename": "remote.zip",
                            "original_filename": "remote.zip",
                            "source_url": "/files/remote.zip",
                        }
                    ],
                },
                {
                    "remote_id": "42",
                    "name": "New challenge",
                    "category": "web",
                    "points": 50,
                    "description": "New remote challenge",
                    "artifacts": [],
                },
            ]

        monkeypatch.setattr("ctfwb.ui.screens.challenges.fetch_ctfd_challenges", fetch)
        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await _open_challenge_screen(app, pilot)
            assert app.screen.check_action("refresh_ctfd_challenges", ()) is True
            await pilot.press("r")
            await pilot.pause()
            preview = str(
                app.screen.query_one("#ctfd-refresh-content", Static).render()
            )
            assert app.screen.query_one("#confirm-ctfd-refresh", Button).has_focus
            assert "Updated title" in preview
            assert "Offline challenge" in preview
            await pilot.click("#cancel-ctfd-refresh")
            await pilot.pause()
            assert store.load_challenges(ctf_id)[0]["name"] == "Old title"

            await pilot.press("r")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

        records = store.load_challenges(ctf_id)
        updated = next(record for record in records if record["remote_id"] == "41")
        added = next(record for record in records if record["remote_id"] == "42")
        preserved = next(record for record in records if record["remote_id"] == "99")
        assert updated["name"] == "Updated title"
        assert updated["status"] == "solved"
        assert updated["flag"] == "flag{local}"
        assert updated["solver"] == {
            "file_type": "python",
            "relative_path": "solve.py",
        }
        assert {item["filename"] for item in updated["artifacts"]} == {
            "local.txt",
            "remote.zip",
        }
        assert added["source"] == "ctfd"
        assert preserved["name"] == "Offline challenge"
        assert calls == [
            (platform_url, "refresh-token"),
            (platform_url, "refresh-token"),
        ]

    asyncio.run(exercise())


def test_json_refresh_previews_before_applying_and_keeps_missing_challenges(tmp_path):
    async def exercise() -> None:
        existing = _challenge(
            "Old JSON title", remote_id="61", status="solved", flag="flag{kept}"
        )
        existing.update(
            {
                "source": "json_import",
                "category": "web",
                "points": 10,
                "solver": {"file_type": "python", "relative_path": "solve.py"},
            }
        )
        missing = _challenge("No longer listed", remote_id="99")
        missing["source"] = "json_import"
        other_source = _challenge("Live CTFd challenge", remote_id="71")
        other_source["source"] = "ctfd"
        store, ctf_id = _seed_store(tmp_path, [existing, missing, other_source])
        app = CTFWorkbenchApp(data_store=store)
        json_text = json.dumps(
            {
                "challenges": [
                    {
                        "id": "61",
                        "name": "Updated JSON title",
                        "category": "crypto",
                        "value": 50,
                        "description": "Updated from JSON",
                        "files": ["/files/remote.zip"],
                    },
                    {"id": "62", "name": "New JSON challenge", "value": 5},
                ]
            }
        )
        refresh_log = ""

        async with app.run_test() as pilot:
            await _open_challenge_screen(app, pilot)
            assert app.screen.check_action("refresh_ctfd_challenges", ()) is True
            await pilot.press("r")
            await pilot.pause()
            assert isinstance(app.screen, RefreshSourceDialog)
            await pilot.click("#refresh-json-source")
            await pilot.pause()
            assert isinstance(app.screen, ImportJSONDialog)
            app.screen.query_one("#import-json-text", TextArea).text = json_text
            await pilot.click("#load-import-json")
            await pilot.pause()

            preview = str(
                app.screen.query_one("#ctfd-refresh-content", Static).render()
            )
            assert "Source: CTFd JSON" in preview
            assert "Updated JSON title" in preview
            assert "No longer listed" in preview
            assert "New JSON challenge" in preview
            assert store.load_challenges(ctf_id) == [existing, missing, other_source]

            await pilot.click("#cancel-ctfd-refresh")
            await pilot.pause()
            assert store.load_challenges(ctf_id) == [existing, missing, other_source]

            await pilot.press("r")
            await pilot.pause()
            await pilot.click("#refresh-json-source")
            await pilot.pause()
            app.screen.query_one("#import-json-text", TextArea).text = json_text
            await pilot.click("#load-import-json")
            await pilot.pause()
            apply_refresh = app.screen.query_one("#confirm-ctfd-refresh", Button)
            assert apply_refresh.has_focus
            await pilot.click("#confirm-ctfd-refresh")
            await pilot.pause()
            await pilot.pause()
            refresh_log = str(app.query_one("#log-message", Static).render())

        records = store.load_challenges(ctf_id)
        updated = next(record for record in records if record["remote_id"] == "61")
        added = next(record for record in records if record["remote_id"] == "62")
        retained = next(record for record in records if record["remote_id"] == "99")
        other_retained = next(
            record for record in records if record["remote_id"] == "71"
        )
        assert updated["name"] == "Updated JSON title"
        assert updated["status"] == "solved"
        assert updated["flag"] == "flag{kept}"
        assert updated["solver"] == {
            "file_type": "python",
            "relative_path": "solve.py",
        }
        assert added["source"] == "json_import"
        assert retained["name"] == "No longer listed"
        assert other_retained["name"] == "Live CTFd challenge"
        assert "CTFd JSON refresh applied: 1 added, 1 updated" in refresh_log

    asyncio.run(exercise())


def test_import_write_failure_keeps_existing_challenges(tmp_path, monkeypatch):
    async def exercise() -> None:
        existing = [_challenge("Local only", status="in_progress")]
        store, ctf_id = _seed_store(tmp_path, existing)
        app = CTFWorkbenchApp(data_store=store)
        fixture = Path(__file__).parent / "fixtures" / "ctfd" / "challenges.json"

        async with app.run_test() as pilot:
            await _open_challenge_screen(app, pilot)
            await _open_json_preview(app, pilot, fixture.read_text(encoding="utf-8"))

            def fail_save(_ctf_id, _records):
                raise DataFileError(
                    store.data_dir
                    / "ctfs"
                    / ctf_id
                    / "challenges"
                    / "information.json",
                    "simulated write failure",
                )

            monkeypatch.setattr(store, "save_challenges", fail_save)
            await pilot.click("#confirm-import")
            await pilot.pause()
            assert store.load_challenges(ctf_id) == existing
            assert "simulated write failure" in str(
                app.screen.query_one("#log-message", Static).render()
            )

    asyncio.run(exercise())


def test_cancel_button_stops_pending_ctfd_import_before_saving_token(
    tmp_path, monkeypatch
):
    async def exercise() -> None:
        store, ctf_id = _seed_store(tmp_path)
        started = threading.Event()
        release = threading.Event()

        def fetch(_base_url: str, _token: str):
            started.set()
            release.wait(timeout=5)
            return [
                {
                    "remote_id": "late-response",
                    "name": "Should not be imported",
                    "category": None,
                    "points": None,
                    "description": "",
                    "artifacts": [],
                }
            ]

        monkeypatch.setattr("ctfwb.ui.dialogs.fetch_ctfd_challenges", fetch)
        app = CTFWorkbenchApp(data_store=store)

        async with app.run_test() as pilot:
            await _open_challenge_screen(app, pilot)
            await pilot.press("m")
            await pilot.click("#import-ctfd-source")
            app.screen.query_one("#ctfd-import-token", Input).value = "cancel-token"

            fetch_click = asyncio.create_task(pilot.click("#fetch-ctfd-challenges"))
            assert await asyncio.to_thread(started.wait, 2)
            await pilot.click("#cancel-ctfd-import")
            await pilot.pause()
            release.set()
            await fetch_click
            await pilot.pause()

            assert isinstance(app.screen, CTFChallengeScreen)
            assert not (store.data_dir / "ctfs" / ctf_id / "token.json").exists()
            assert store.load_challenges(ctf_id) == []

    asyncio.run(exercise())


def test_artifact_download_skips_dialog_and_cleans_partial_failure(
    tmp_path, monkeypatch
):
    async def exercise() -> None:
        challenge = _challenge("Download challenge", remote_id="51")
        challenge.update(
            {
                "source": "ctfd",
                "artifacts": [
                    {
                        "filename": "payload.zip",
                        "original_filename": "../payload.zip",
                        "source_url": "/files/payload.zip",
                    }
                ],
            }
        )
        store, ctf_id = _seed_store(tmp_path, [challenge])
        platform_url = "https://ctfd.example"
        store.save_ctfd_token(ctf_id, platform_url, "download-token")
        app = CTFWorkbenchApp(data_store=store)
        download_calls = []

        def interrupted_download(*_args, **_kwargs):
            download_calls.append(True)
            yield b"partial bytes"
            raise CTFdError("CTFd artifact download failed")

        monkeypatch.setattr(
            "ctfwb.ui.screens.challenges.download_ctfd_artifact",
            interrupted_download,
        )

        async with app.run_test() as pilot:
            await _open_challenge_screen(app, pilot)
            await pilot.press("x")
            await pilot.pause()
            assert not app.screen.query("#artifact-download-content")
            await pilot.pause()

            artifact_directory = (
                store.data_dir
                / "ctfs"
                / ctf_id
                / "challenges"
                / challenge["id"]
                / "artifacts"
            )
            assert download_calls == [True]
            assert not (artifact_directory / "payload.zip").exists()
            assert list(artifact_directory.glob(".ctfwb-artifact-*.tmp")) == []
            log = str(app.query_one("#log-message", Static).render())
            assert "payload.zip: CTFd artifact download failed" in log
            assert "1 failed" in log

    asyncio.run(exercise())
