"""Regression tests for editing, tracking, and removing challenges in the TUI."""

import asyncio
import json
import threading

import pytest
from textual.containers import Horizontal
from textual.widgets import Input, ListView, Static, TextArea

from ctfwb import CTFWorkbenchApp, DataStore, generate_id
from ctfwb.app import CTFChallengeScreen
from ctfwb.importers import CTFdError


def _seed_store(tmp_path, names=("Original challenge",)):
    """Create a file-backed CTF with representative challenge and file records."""
    store = DataStore(tmp_path / "user-data")
    ctf_id = generate_id()
    timestamp = "2025-01-02T03:04:05Z"
    store.save_ctfs(
        [
            {
                "id": ctf_id,
                "name": "Test CTF",
                "year": 2025,
                "platform_url": None,
                "description": "",
                "source": "manual",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        ]
    )

    records = []
    for index, name in enumerate(names):
        challenge_id = generate_id()
        records.append(
            {
                "id": challenge_id,
                "name": name,
                "category": "web",
                "points": 100 + index,
                "description": "Initial description",
                "artifacts": [
                    {
                        "filename": f"payload-{index}.zip",
                        "original_filename": "payload.zip",
                        "source_url": "https://files.example/payload.zip",
                    }
                ],
                "status": "unsolved",
                "flag": None,
                "source": "ctfd",
                "remote_id": f"remote-{index}",
                "solver": {
                    "file_type": "python",
                    "relative_path": "solver/solve.py",
                },
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )
    store.load_challenges(ctf_id)
    store.save_challenges(ctf_id, records)

    challenge_root = store.data_dir / "ctfs" / ctf_id / "challenges"
    for record in records:
        challenge_dir = challenge_root / record["id"]
        solver_path = challenge_dir / "solver" / "solve.py"
        artifact_path = challenge_dir / "artifacts" / record["artifacts"][0]["filename"]
        solver_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        solver_path.write_text("# local solver\n", encoding="utf-8")
        artifact_path.write_bytes(b"challenge artifact")
    return store, ctf_id, records


async def _open_challenges(app, pilot):
    await pilot.press("enter")


def test_edit_challenge_persists_fields_and_preserves_stable_metadata(tmp_path) -> None:
    async def exercise() -> None:
        store, ctf_id, seeded = _seed_store(tmp_path)
        original = seeded[0]
        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await _open_challenges(app, pilot)
            await pilot.press("e")
            dialog = app.screen
            assert not dialog.query_one("#edit-challenge-flag", Input).password
            dialog.query_one(
                "#edit-challenge-name", Input
            ).value = "  Updated challenge "
            dialog.query_one("#edit-challenge-category", Input).value = " crypto "
            dialog.query_one("#edit-challenge-points", Input).value = "350"
            dialog.query_one("#edit-challenge-status", Input).value = "in_progress"
            dialog.query_one(
                "#edit-challenge-flag", Input
            ).value = "flag{edited-secret}"
            dialog.query_one(
                "#edit-challenge-description", TextArea
            ).text = "Updated description"
            dialog.query_one("#edit-challenge-artifacts", TextArea).text = json.dumps(
                [
                    {
                        "filename": "updated.bin",
                        "original_filename": "original.bin",
                        "source_url": "https://files.example/updated.bin",
                    }
                ]
            )
            await pilot.click("#confirm-edit-challenge")

            updated = store.load_challenges(ctf_id)[0]
            assert updated["name"] == "Updated challenge"
            assert updated["category"] == "crypto"
            assert updated["points"] == 350
            assert updated["description"] == "Updated description"
            assert updated["artifacts"] == [
                {
                    "filename": "updated.bin",
                    "original_filename": "original.bin",
                    "source_url": "https://files.example/updated.bin",
                }
            ]
            assert updated["status"] == "in_progress"
            assert updated["flag"] == "flag{edited-secret}"
            for field in ("id", "source", "remote_id", "solver", "created_at"):
                assert updated[field] == original[field]
            assert "[Updated challenge] Challenge updated." in str(
                app.screen.query_one("#log-message", Static).render()
            )

        restarted = CTFWorkbenchApp(data_store=store)
        async with restarted.run_test() as pilot:
            await _open_challenges(restarted, pilot)
            persisted = store.load_challenges(ctf_id)[0]
            assert persisted["name"] == "Updated challenge"

    asyncio.run(exercise())


def test_invalid_edit_values_keep_dialog_open_and_report_errors(tmp_path) -> None:
    async def exercise() -> None:
        store, _ctf_id, _seeded = _seed_store(tmp_path)
        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await _open_challenges(app, pilot)
            await pilot.press("e")
            dialog = app.screen

            dialog.query_one("#edit-challenge-points", Input).value = "many"
            await pilot.click("#confirm-edit-challenge")
            assert dialog.is_mounted
            assert "Points must be a whole number." in str(
                dialog.query_one("#edit-challenge-error", Static).render()
            )

            await pilot.press("escape")
            await pilot.press("e")
            dialog = app.screen
            dialog.query_one("#edit-challenge-status", Input).value = "finished"
            await pilot.click("#confirm-edit-challenge")
            assert dialog.is_mounted
            assert "Status must be one of:" in str(
                dialog.query_one("#edit-challenge-error", Static).render()
            )

            await pilot.press("escape")
            await pilot.press("e")
            dialog = app.screen
            dialog.query_one("#edit-challenge-artifacts", TextArea).text = "[broken"
            await pilot.click("#confirm-edit-challenge")
            assert dialog.is_mounted
            assert "Artifacts must be valid JSON:" in str(
                dialog.query_one("#edit-challenge-error", Static).render()
            )

    asyncio.run(exercise())


def test_status_command_opens_selector_and_persists_selected_status(tmp_path) -> None:
    async def exercise() -> None:
        store, ctf_id, seeded = _seed_store(tmp_path)
        seeded[0]["status"] = "skipped"
        store.save_challenges(ctf_id, seeded)
        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await _open_challenges(app, pilot)
            challenge_list = app.screen.query_one("#challenge-list", ListView)
            item = challenge_list.children[0]
            row = item.query_one(".challenge-list-row", Horizontal)
            indicator = item.query_one(".challenge-status-indicator", Static)
            assert row.children[-1] is indicator
            assert "SKIPPED" in str(indicator.render())

            await pilot.press("t")
            status_options = app.screen.query_one(
                "#select-challenge-status-options", ListView
            )
            assert status_options.has_focus
            assert status_options.index == 3
            await pilot.press("k")
            assert status_options.index == 2
            await pilot.press("j")
            assert status_options.index == 3
            await pilot.press("escape")
            assert store.load_challenges(ctf_id)[0]["status"] == "skipped"

            labels = {
                "unsolved": ("UNSOLVED", "Unsolved"),
                "in_progress": ("IN PROG", "In Progress"),
                "solved": ("SOLVED", "Solved"),
                "skipped": ("SKIPPED", "Skipped"),
            }
            for expected, (label, status_label) in labels.items():
                await pilot.press("t")
                button_id = expected.replace("_", "-")
                await pilot.click(f"#status-{button_id}")
                assert store.load_challenges(ctf_id)[0]["status"] == expected
                assert label in str(indicator.render())
                assert (
                    f"[Original challenge]: Status changed to: {status_label}"
                    in str(app.screen.query_one("#log-message", Static).render())
                )

    asyncio.run(exercise())


def test_flag_command_adds_flag_and_marks_challenge_solved(
    tmp_path,
) -> None:
    async def exercise() -> None:
        store, ctf_id, _seeded = _seed_store(tmp_path)
        flag = "flag{new_flag}"
        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await _open_challenges(app, pilot)
            await pilot.press("f")
            assert not app.screen.query("#save-and-submit-flag")
            dialog = app.screen
            flag_input = dialog.query_one("#edit-flag-input", Input)
            assert not flag_input.password
            assert flag_input.value == ""
            assert flag_input.has_focus
            flag_input.value = flag
            await pilot.press("enter")
            await pilot.pause()

            saved = store.load_challenges(ctf_id)[0]
            assert saved["flag"] == flag
            assert saved["status"] == "solved"
            details = str(
                app.screen.query_one("#challenge-details-content", Static).render()
            )
            log = str(app.screen.query_one("#log-message", Static).render())
            assert f"Flag: {flag}" in details
            assert f"[Original challenge] Added flag: {flag}" in log

    asyncio.run(exercise())


def test_flag_editor_prefills_updates_and_clears_without_changing_status(
    tmp_path,
) -> None:
    async def exercise() -> None:
        store, ctf_id, seeded = _seed_store(tmp_path)
        seeded[0]["flag"] = "flag{existing}"
        seeded[0]["status"] = "in_progress"
        store.save_challenges(ctf_id, seeded)
        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await _open_challenges(app, pilot)
            await pilot.press("f")
            app.screen.query_one("#edit-flag-input", Input).value = "flag{discarded}"
            await pilot.press("escape")
            await pilot.pause()
            assert store.load_challenges(ctf_id)[0]["flag"] == "flag{existing}"
            assert store.load_challenges(ctf_id)[0]["status"] == "in_progress"

            await pilot.press("f")
            input_field = app.screen.query_one("#edit-flag-input", Input)
            assert input_field.value == "flag{existing}"
            assert not input_field.password
            input_field.value = "flag{updated}"
            await pilot.click("#save-flag")
            await pilot.pause()

            saved = store.load_challenges(ctf_id)[0]
            assert saved["flag"] == "flag{updated}"
            assert saved["status"] == "in_progress"
            assert "[Original challenge] Updated flag: flag{updated}" in str(
                app.screen.query_one("#log-message", Static).render()
            )
            assert "Flag: flag{updated}" in str(
                app.screen.query_one("#challenge-details-content", Static).render()
            )

            await pilot.press("f")
            app.screen.query_one("#edit-flag-input", Input).value = ""
            await pilot.click("#save-flag")
            await pilot.pause()
            saved = store.load_challenges(ctf_id)[0]
            assert saved["flag"] is None
            assert saved["status"] == "in_progress"
            assert "[Original challenge] Removed flag; status unchanged." in str(
                app.screen.query_one("#log-message", Static).render()
            )
            assert "Flag: —" in str(
                app.screen.query_one("#challenge-details-content", Static).render()
            )

    asyncio.run(exercise())


@pytest.mark.parametrize(
    (
        "submission_result",
        "existing_flag",
        "existing_status",
        "expected_flag",
        "expected_status",
    ),
    [
        ("correct", None, "unsolved", "flag{candidate}", "solved"),
        ("incorrect", None, "unsolved", None, "unsolved"),
        (
            CTFdError("CTFd server is unavailable"),
            None,
            "unsolved",
            None,
            "unsolved",
        ),
        (
            "correct",
            "flag{candidate}",
            "in_progress",
            "flag{candidate}",
            "solved",
        ),
    ],
)
def test_save_and_submit_persists_only_when_ctfd_verifies_flag(
    tmp_path,
    monkeypatch,
    submission_result: str | Exception,
    existing_flag: str | None,
    existing_status: str,
    expected_flag: str | None,
    expected_status: str,
) -> None:
    async def exercise() -> None:
        store, ctf_id, seeded = _seed_store(tmp_path)
        platform_url = "https://ctfd.example"
        ctfs = store.load_ctfs()
        ctfs[0]["platform_url"] = platform_url
        store.save_ctfs(ctfs)
        seeded[0]["remote_id"] = "41"
        seeded[0]["flag"] = existing_flag
        seeded[0]["status"] = existing_status
        store.save_challenges(ctf_id, seeded)
        store.save_ctfd_token(ctf_id, platform_url, "test-api-token")
        submissions = []

        def submit(url, token, remote_id, flag):
            submissions.append((url, token, remote_id, flag))
            if isinstance(submission_result, Exception):
                raise submission_result
            return submission_result

        monkeypatch.setattr("ctfwb.ui.screens.challenges.submit_ctfd_flag", submit)
        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await _open_challenges(app, pilot)
            await pilot.press("f")
            assert app.screen.query_one("#save-flag")
            assert app.screen.query_one("#save-and-submit-flag")
            assert not app.screen.query("#edit-flag-help")
            flag_input = app.screen.query_one("#edit-flag-input", Input)
            assert flag_input.has_focus
            flag_input.value = "flag{candidate}"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            saved = store.load_challenges(ctf_id)[0]
            assert saved["flag"] == expected_flag
            assert saved["status"] == expected_status
            assert submissions == [
                (platform_url, "test-api-token", "41", "flag{candidate}")
            ]
            log = str(app.screen.query_one("#log-message", Static).render())
            if expected_flag is None:
                assert "flag{candidate}" not in log
                if isinstance(submission_result, Exception):
                    assert "CTFd flag submission failed" in log
                else:
                    assert "no local changes were made" in log
            else:
                assert "CTFd verified flag" in log

    asyncio.run(exercise())


def test_save_remains_local_when_ctfd_submission_is_available(
    tmp_path, monkeypatch
) -> None:
    async def exercise() -> None:
        store, ctf_id, seeded = _seed_store(tmp_path)
        platform_url = "https://ctfd.example"
        ctfs = store.load_ctfs()
        ctfs[0]["platform_url"] = platform_url
        store.save_ctfs(ctfs)
        seeded[0]["remote_id"] = "41"
        store.save_challenges(ctf_id, seeded)
        store.save_ctfd_token(ctf_id, platform_url, "test-api-token")
        monkeypatch.setattr(
            "ctfwb.ui.screens.challenges.submit_ctfd_flag",
            lambda *_args: pytest.fail("Save must not submit the flag"),
        )
        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await _open_challenges(app, pilot)
            await pilot.press("f")
            assert app.screen.query_one("#save-and-submit-flag")
            app.screen.query_one("#edit-flag-input", Input).value = "flag{local}"
            await pilot.click("#save-flag")
            await pilot.pause()

            saved = store.load_challenges(ctf_id)[0]
            assert saved["flag"] == "flag{local}"
            assert saved["status"] == "solved"

    asyncio.run(exercise())


def test_delete_challenge_cancel_preserves_data_and_confirm_keeps_sibling(
    tmp_path,
) -> None:
    async def exercise() -> None:
        store, ctf_id, seeded = _seed_store(
            tmp_path, ("Remove this challenge", "Keep this challenge")
        )
        challenge_root = store.data_dir / "ctfs" / ctf_id / "challenges"
        selected_dir = challenge_root / seeded[0]["id"]
        sibling_dir = challenge_root / seeded[1]["id"]
        selected_solver = selected_dir / seeded[0]["solver"]["relative_path"]
        selected_artifact = selected_dir / "artifacts" / "payload-0.zip"
        sibling_solver = sibling_dir / seeded[1]["solver"]["relative_path"]
        app = CTFWorkbenchApp(data_store=store)

        async with app.run_test() as pilot:
            await _open_challenges(app, pilot)
            await pilot.press("d")
            assert "Remove this challenge" in str(
                app.screen.query_one("#delete-challenge-message", Static).render()
            )
            await pilot.press("escape")
            await pilot.pause()
            assert [record["id"] for record in store.load_challenges(ctf_id)] == [
                item["id"] for item in seeded
            ]
            assert selected_solver.exists()
            assert selected_artifact.exists()

            await pilot.press("d")
            await pilot.click("#confirm-delete-challenge")
            await pilot.pause()
            remaining = store.load_challenges(ctf_id)
            assert [record["id"] for record in remaining] == [seeded[1]["id"]]
            assert not selected_dir.exists()
            assert sibling_solver.exists()
            assert sibling_dir.exists()
            challenge_list = app.screen.query_one("#challenge-list", ListView)
            assert len(challenge_list.children) == 1
            assert "Keep this challenge" in str(
                app.screen.query_one("#challenge-details-content", Static).render()
            )

    asyncio.run(exercise())


def test_challenge_details_show_artifact_filenames_and_download_status(
    tmp_path,
) -> None:
    async def exercise() -> None:
        store, ctf_id, seeded = _seed_store(tmp_path)
        record = seeded[0]
        record.update(
            {
                "name": "[bold]Literal challenge[/bold]",
                "artifacts": [
                    {
                        "filename": "payload.zip",
                        "original_filename": "[italic]download.zip[/italic]",
                        "source_url": "https://files.example/payload.zip",
                    },
                    {
                        "filename": "not-present.bin",
                        "source_url": "https://files.example/not-present.bin",
                    },
                ],
                "status": "in_progress",
                "flag": "flag{private_details}",
                "solver": {"file_type": "python", "relative_path": "solve.py"},
            }
        )
        store.save_challenges(ctf_id, [record])
        downloaded_path = (
            store.data_dir
            / "ctfs"
            / ctf_id
            / "challenges"
            / record["id"]
            / "artifacts"
            / "payload.zip"
        )
        downloaded_path.parent.mkdir(parents=True, exist_ok=True)
        downloaded_path.write_bytes(b"artifact bytes")
        restarted = CTFWorkbenchApp(data_store=store)
        async with restarted.run_test() as pilot:
            await _open_challenges(restarted, pilot)
            rendered = str(
                restarted.screen.query_one(
                    "#challenge-details-content", Static
                ).render()
            )
            assert "Status: IN PROG" in rendered
            assert "payload.zip: downloaded" in rendered
            assert "not-present.bin: not downloaded" in rendered
            assert "[italic]download.zip[/italic]" not in rendered
            assert "solve.py" in rendered
            assert "SOLVER" in rendered
            assert "Flag: flag{private_details}" in rendered

    asyncio.run(exercise())


def test_challenge_bindings_include_management_and_navigation_keys(tmp_path) -> None:
    async def exercise() -> None:
        store, _ctf_id, _seeded = _seed_store(tmp_path, ("First", "Second"))
        records = store.load_challenges(_ctf_id)
        records[0]["source"] = "manual"
        store.save_challenges(_ctf_id, records)
        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await _open_challenges(app, pilot)
            assert app.screen.check_action("download_artifacts", ()) is False
            assert app.screen.check_action("refresh_ctfd_challenges", ()) is True
            bindings = {
                binding.key: binding.action for binding in CTFChallengeScreen.BINDINGS
            }
            assert {
                "a": "add_challenge",
                "m": "import_challenges",
                "x": "download_artifacts",
                "o": "open_artifacts_directory",
                "r": "refresh_ctfd_challenges",
                "e": "edit_challenge",
                "d": "delete_challenge",
                "t": "set_challenge_status",
                "f": "edit_flag",
                "s": "create_solver",
                "v": "edit_solver",
                "g": "run_solver",
                "c": "cancel_solver",
                "b": "export_backup",
                "j": "challenge_down",
                "k": "challenge_up",
            }.items() <= bindings.items()
            labels = {
                binding.key: binding.description
                for binding in CTFChallengeScreen.BINDINGS
            }
            assert labels["a"] == "Add"
            assert labels["m"] == "Import"
            assert labels["x"] == "Download"
            assert labels["o"] == "Folder"
            assert labels["r"] == "Refresh"
            assert labels["e"] == "Edit"
            assert labels["d"] == "Delete"
            assert labels["t"] == "Status"
            assert labels["f"] == "Flag"
            assert labels["s"] == "Solver"
            assert labels["v"] == "Edit Solver"
            assert labels["g"] == "Run"
            assert labels["c"] == "Cancel Solver"
            assert labels["b"] == "Backup"
            assert labels["j"] == "Next"
            assert labels["k"] == "Prev"
            assert labels["up"] == "Prev"
            assert labels["down"] == "Next"

            await pilot.press("j")
            assert app.screen.query_one("#challenge-list", ListView).index == 1
            assert app.screen.check_action("download_artifacts", ()) is True
            await pilot.press("k")
            assert app.screen.query_one("#challenge-list", ListView).index == 0
            assert app.screen.check_action("download_artifacts", ()) is False
            await pilot.press("a")
            assert app.screen.query_one("#challenge-name", Input)

    asyncio.run(exercise())


def test_selected_ctfd_artifact_download_confirms_overwrite_in_place(
    tmp_path, monkeypatch
) -> None:
    async def exercise() -> None:
        store, ctf_id, seeded = _seed_store(tmp_path)
        platform_url = "https://ctfd.example"
        ctfs = store.load_ctfs()
        ctfs[0]["platform_url"] = platform_url
        store.save_ctfs(ctfs)
        store.save_ctfd_token(ctf_id, platform_url, "test-api-token")
        artifact_path = (
            store.data_dir
            / "ctfs"
            / ctf_id
            / "challenges"
            / seeded[0]["id"]
            / "artifacts"
            / "payload-0.zip"
        )
        assert artifact_path.read_bytes() == b"challenge artifact"
        monkeypatch.setattr(
            "ctfwb.ui.screens.challenges.download_ctfd_artifact",
            lambda *_args, **_kwargs: iter([b"replacement artifact"]),
        )

        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await _open_challenges(app, pilot)
            assert app.screen.check_action("download_artifacts", ()) is True
            assert app.screen.check_action("refresh_ctfd_challenges", ()) is True
            await pilot.press("x")
            await pilot.pause()
            preview = str(
                app.screen.query_one("#artifact-download-content", Static).render()
            )
            assert "OVERWRITE existing file" in preview
            assert "No extra versions will be kept" in preview
            await pilot.click("#cancel-artifact-download")
            await pilot.pause()
            assert artifact_path.read_bytes() == b"challenge artifact"

            await pilot.press("x")
            await pilot.pause()
            await pilot.click("#confirm-artifact-download")
            await pilot.pause()
            await pilot.pause()
            assert artifact_path.read_bytes() == b"replacement artifact"
            assert list(artifact_path.parent.iterdir()) == [artifact_path]
            rendered = str(
                app.screen.query_one("#challenge-details-content", Static).render()
            )
            assert "payload-0.zip: downloaded" in rendered

    asyncio.run(exercise())


def test_selected_ctfd_artifact_download_skips_confirmation_for_new_file(
    tmp_path, monkeypatch
) -> None:
    async def exercise() -> None:
        store, ctf_id, seeded = _seed_store(tmp_path)
        platform_url = "https://ctfd.example"
        ctfs = store.load_ctfs()
        ctfs[0]["platform_url"] = platform_url
        store.save_ctfs(ctfs)
        store.save_ctfd_token(ctf_id, platform_url, "test-api-token")
        artifact_path = (
            store.data_dir
            / "ctfs"
            / ctf_id
            / "challenges"
            / seeded[0]["id"]
            / "artifacts"
            / "payload-0.zip"
        )
        artifact_path.unlink()
        monkeypatch.setattr(
            "ctfwb.ui.screens.challenges.download_ctfd_artifact",
            lambda *_args, **_kwargs: iter([b"new artifact"]),
        )

        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await _open_challenges(app, pilot)
            await pilot.press("x")
            await pilot.pause()
            await pilot.pause()

            assert not app.screen.query("#artifact-download-content")
            assert artifact_path.read_bytes() == b"new artifact"

    asyncio.run(exercise())


def test_artifact_download_cannot_be_started_twice(tmp_path, monkeypatch) -> None:
    async def exercise() -> None:
        store, ctf_id, seeded = _seed_store(tmp_path)
        platform_url = "https://ctfd.example"
        ctfs = store.load_ctfs()
        ctfs[0]["platform_url"] = platform_url
        store.save_ctfs(ctfs)
        store.save_ctfd_token(ctf_id, platform_url, "test-api-token")
        artifact_path = (
            store.data_dir
            / "ctfs"
            / ctf_id
            / "challenges"
            / seeded[0]["id"]
            / "artifacts"
            / "payload-0.zip"
        )
        artifact_path.unlink()
        download_started = threading.Event()
        release_download = threading.Event()
        download_calls = []

        def blocked_download(*_args, **_kwargs):
            download_calls.append(True)
            download_started.set()
            if not release_download.wait(timeout=5):
                raise AssertionError("test did not release the download")
            return iter([b"artifact bytes"])

        monkeypatch.setattr(
            "ctfwb.ui.screens.challenges.download_ctfd_artifact",
            blocked_download,
        )
        app = CTFWorkbenchApp(data_store=store)

        async with app.run_test() as pilot:
            await _open_challenges(app, pilot)
            try:
                await pilot.press("x")
                assert await asyncio.to_thread(download_started.wait, 2)
                assert app.screen.check_action("download_artifacts", ()) is False
                await pilot.press("x")
                assert download_calls == [True]
            finally:
                release_download.set()
            await pilot.pause()
            await pilot.pause()

        assert artifact_path.read_bytes() == b"artifact bytes"

    asyncio.run(exercise())


def test_ctfd_download_without_artifacts_reports_empty_state(tmp_path) -> None:
    async def exercise() -> None:
        store, ctf_id, seeded = _seed_store(tmp_path)
        challenge = dict(seeded[0])
        challenge["artifacts"] = []
        store.save_challenges(ctf_id, [challenge])
        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await _open_challenges(app, pilot)
            await pilot.press("x")
            log = str(app.screen.query_one("#log-message", Static).render())
            assert "No artifacts are attached" in log

    asyncio.run(exercise())


def test_challenge_command_bar_grows_when_narrow_and_shrinks_when_wide(
    tmp_path,
) -> None:
    async def exercise() -> None:
        store, _ctf_id, _seeded = _seed_store(tmp_path)
        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test(size=(60, 24)) as pilot:
            await _open_challenges(app, pilot)
            footer = app.screen.query_one("#challenge-command-bar")
            await pilot.pause()
            assert footer.size.height > 1

            footer_keys = footer.query("FooterKey")
            rendered_labels = [str(key.render()) for key in footer_keys]
            assert any("CTFs" in label for label in rendered_labels)
            assert any("Import" in label for label in rendered_labels)
            assert any("Download" in label for label in rendered_labels)
            assert any("Refresh" in label for label in rendered_labels)
            assert any("Delete" in label for label in rendered_labels)
            assert all(key.render().cell_len <= key.size.width for key in footer_keys)
            assert any(
                right.region.x > left.region.right
                for left, right in zip(footer_keys, footer_keys[1:])
                if left.region.y == right.region.y
            )

            await pilot.resize_terminal(200, 24)
            await pilot.pause()
            assert footer.size.height == 1
            footer_keys = footer.query("FooterKey")
            assert all(key.render().cell_len <= key.size.width for key in footer_keys)
            assert any(
                right.region.x > left.region.right
                for left, right in zip(footer_keys, footer_keys[1:])
            )

    asyncio.run(exercise())
