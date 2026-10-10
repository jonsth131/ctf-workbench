"""Regression tests for safely creating and editing challenge notes."""

import asyncio
from contextlib import nullcontext

import pytest
from textual.widgets import Static

from ctfwb import AppConfig, CTFWorkbenchApp, DataStore, generate_id
from ctfwb.editor import run_editor
from ctfwb.storage import (
    DataFileError,
    DataValidationError,
    utc_timestamp,
)


def _ctf_record(**overrides):
    now = utc_timestamp()
    return {
        "id": generate_id(),
        "name": "Spring CTF",
        "year": 2026,
        "platform_url": None,
        "description": "",
        "source": "manual",
        "created_at": now,
        "updated_at": now,
        **overrides,
    }


def _challenge_record(**overrides):
    now = utc_timestamp()
    return {
        "id": generate_id(),
        "name": "Web Warmup",
        "category": "web",
        "points": 100,
        "description": "",
        "artifacts": [],
        "status": "unsolved",
        "flag": None,
        "source": "manual",
        "remote_id": None,
        "solver": None,
        "created_at": now,
        "updated_at": now,
        **overrides,
    }


def _store_with_challenge(tmp_path):
    store = DataStore(tmp_path / "user data")
    ctf = _ctf_record()
    challenge = _challenge_record()
    store.save_ctfs([ctf])
    store.save_challenges(ctf["id"], [challenge])
    return store, ctf, challenge


def test_ensure_notes_creates_empty_file_for_existing_challenge(tmp_path):
    store, ctf, challenge = _store_with_challenge(tmp_path)

    notes_path = store.ensure_challenge_notes_file(ctf["id"], challenge["id"])

    assert notes_path == (
        store.data_dir
        / "ctfs"
        / ctf["id"]
        / "challenges"
        / challenge["id"]
        / "notes.md"
    )
    assert notes_path.is_file()
    assert notes_path.read_bytes() == b""


def test_ensure_notes_preserves_existing_file_contents(tmp_path):
    store, ctf, challenge = _store_with_challenge(tmp_path)
    challenge_directory = (
        store.data_dir / "ctfs" / ctf["id"] / "challenges" / challenge["id"]
    )
    challenge_directory.mkdir(parents=True)
    notes_path = challenge_directory / "notes.md"
    original = b"# Existing notes\n\nflag format: CTF{...}\n"
    notes_path.write_bytes(original)

    result = store.ensure_challenge_notes_file(ctf["id"], challenge["id"])

    assert result == notes_path
    assert notes_path.read_bytes() == original


def test_read_notes_returns_content_without_creating_a_missing_file(tmp_path):
    store, ctf, challenge = _store_with_challenge(tmp_path)
    notes_path = (
        store.data_dir
        / "ctfs"
        / ctf["id"]
        / "challenges"
        / challenge["id"]
        / "notes.md"
    )

    assert store.read_challenge_notes(ctf["id"], challenge["id"]) == ""
    assert not notes_path.exists()

    notes_path.parent.mkdir(parents=True)
    notes_path.write_text("# Existing notes\n", encoding="utf-8")
    assert store.read_challenge_notes(ctf["id"], challenge["id"]) == (
        "# Existing notes\n"
    )


def test_read_notes_refuses_symlinked_notes_file(tmp_path):
    store, ctf, challenge = _store_with_challenge(tmp_path)
    challenge_directory = (
        store.data_dir / "ctfs" / ctf["id"] / "challenges" / challenge["id"]
    )
    challenge_directory.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("do not display", encoding="utf-8")
    (challenge_directory / "notes.md").symlink_to(outside)

    with pytest.raises(DataFileError):
        store.read_challenge_notes(ctf["id"], challenge["id"])

    assert outside.read_text(encoding="utf-8") == "do not display"


@pytest.mark.parametrize("challenge_id", ["../outside", "A" * 32, "not-an-id", None])
def test_ensure_notes_rejects_invalid_challenge_ids(tmp_path, challenge_id):
    store, ctf, _challenge = _store_with_challenge(tmp_path)

    with pytest.raises(DataFileError, match="challenge ID"):
        store.ensure_challenge_notes_file(ctf["id"], challenge_id)

    assert not (store.data_dir.parent / "outside").exists()


def test_ensure_notes_requires_challenge_to_exist(tmp_path):
    store, ctf, _challenge = _store_with_challenge(tmp_path)
    missing_id = generate_id()

    with pytest.raises(DataValidationError, match="does not exist"):
        store.ensure_challenge_notes_file(ctf["id"], missing_id)

    assert not (
        store.data_dir / "ctfs" / ctf["id"] / "challenges" / missing_id
    ).exists()


def test_ensure_notes_refuses_symlinked_notes_file(tmp_path):
    store, ctf, challenge = _store_with_challenge(tmp_path)
    challenge_directory = (
        store.data_dir / "ctfs" / ctf["id"] / "challenges" / challenge["id"]
    )
    challenge_directory.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("do not alter", encoding="utf-8")
    (challenge_directory / "notes.md").symlink_to(outside)

    with pytest.raises(DataFileError):
        store.ensure_challenge_notes_file(ctf["id"], challenge["id"])

    assert outside.read_text(encoding="utf-8") == "do not alter"


def test_ensure_notes_refuses_non_file_notes_path(tmp_path):
    store, ctf, challenge = _store_with_challenge(tmp_path)
    notes_path = (
        store.data_dir
        / "ctfs"
        / ctf["id"]
        / "challenges"
        / challenge["id"]
        / "notes.md"
    )
    notes_path.mkdir(parents=True)

    with pytest.raises(DataFileError, match="not a regular file"):
        store.ensure_challenge_notes_file(ctf["id"], challenge["id"])

    assert notes_path.is_dir()


def test_ensure_notes_refuses_symlinked_challenge_directory(tmp_path):
    store, ctf, challenge = _store_with_challenge(tmp_path)
    challenge_directory = (
        store.data_dir / "ctfs" / ctf["id"] / "challenges" / challenge["id"]
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (challenge_directory.parent / challenge["id"]).symlink_to(
        outside, target_is_directory=True
    )

    with pytest.raises(DataFileError):
        store.ensure_challenge_notes_file(ctf["id"], challenge["id"])

    assert list(outside.iterdir()) == []


def test_run_editor_passes_unmodified_argv_without_shell(monkeypatch, tmp_path):
    calls = []
    note_path = tmp_path / "challenge notes" / "notes.md"

    class Result:
        returncode = 0

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return Result()

    monkeypatch.setattr("ctfwb.editor.subprocess.run", fake_run)

    assert (
        run_editor("editor with spaces", ("--wait", "two words", "--"), note_path) == 0
    )

    assert calls == [
        (
            ["editor with spaces", "--wait", "two words", "--", str(note_path)],
            {"check": False},
        )
    ]


def test_config_defaults_editor_to_nvim(tmp_path):
    config = AppConfig.load(tmp_path / "missing.toml")

    assert config.editor == "nvim"
    assert config.editor_args == ()


def test_config_reads_editor_executable_and_arguments(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[editor]\nexecutable = "my-editor"\nargs = ["--wait", "two words"]\n',
        encoding="utf-8",
    )

    config = AppConfig.load(config_path)

    assert config.editor == "my-editor"
    assert config.editor_args == ("--wait", "two words")


def test_note_binding_opens_selected_challenge_notes_with_configured_editor(
    tmp_path, monkeypatch
):
    async def exercise():
        store, ctf_record, challenge_record = _store_with_challenge(tmp_path)
        app = CTFWorkbenchApp(
            data_store=store,
            editor="editor with spaces",
            editor_args=("--wait", "two words"),
        )
        calls = []

        def fake_editor(executable, arguments, file_path):
            calls.append((executable, arguments, file_path))
            assert file_path.is_file()
            file_path.write_text("# Solving notes\n", encoding="utf-8")
            return 0

        monkeypatch.setattr("ctfwb.app.run_editor", fake_editor)
        monkeypatch.setattr(app, "suspend", lambda: nullcontext())

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.press("n")
            await pilot.pause()

            expected = (
                store.data_dir
                / "ctfs"
                / ctf_record["id"]
                / "challenges"
                / challenge_record["id"]
                / "notes.md"
            )
            assert calls == [("editor with spaces", ("--wait", "two words"), expected)]
            assert expected.read_text(encoding="utf-8") == "# Solving notes\n"
            details = str(
                app.screen.query_one("#challenge-details-content", Static).render()
            )
            assert "NOTES" in details
            assert "# Solving notes" in details
            assert "[Web Warmup] Note edited." in str(
                app.query_one("#log-message", Static).render()
            )

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("editor_result", "expected_message"),
    [
        (OSError("editor unavailable"), "Cannot edit note: editor unavailable"),
        (7, "Note editor exited with non-zero status 7"),
    ],
)
def test_note_binding_reports_editor_failures(
    tmp_path, monkeypatch, editor_result, expected_message
):
    async def exercise():
        store, _ctf, _challenge = _store_with_challenge(tmp_path)
        app = CTFWorkbenchApp(data_store=store)

        def fail_editor(*_args):
            if isinstance(editor_result, Exception):
                raise editor_result
            return editor_result

        monkeypatch.setattr("ctfwb.app.run_editor", fail_editor)
        monkeypatch.setattr(app, "suspend", lambda: nullcontext())

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.press("n")
            await pilot.pause()
            log = str(app.query_one("#log-message", Static).render())
            assert "[Web Warmup]" in log
            assert expected_message in log

    asyncio.run(exercise())


def test_note_binding_without_selected_challenge_logs_and_does_not_launch_editor(
    tmp_path, monkeypatch
):
    async def exercise():
        store, _ctf, _challenge = _store_with_challenge(tmp_path)
        store.save_challenges(
            _ctf["id"],
            [],
        )
        app = CTFWorkbenchApp(data_store=store)
        monkeypatch.setattr(
            "ctfwb.app.run_editor",
            lambda *_args: pytest.fail("editor must not run without selection"),
        )

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.press("n")
            await pilot.pause()
            assert "No challenge selected to edit a note" in str(
                app.query_one("#log-message", Static).render()
            )

    asyncio.run(exercise())


def test_note_binding_without_persistent_storage_logs_and_does_not_launch_editor(
    tmp_path, monkeypatch
):
    async def exercise():
        store, _ctf, _challenge = _store_with_challenge(tmp_path)
        app = CTFWorkbenchApp(data_store=store)
        monkeypatch.setattr(
            "ctfwb.app.run_editor",
            lambda *_args: pytest.fail(
                "editor must not run without persistent storage"
            ),
        )

        async with app.run_test() as pilot:
            await pilot.press("enter")
            app._data_store = None
            await pilot.press("n")
            await pilot.pause()
            log = str(app.query_one("#log-message", Static).render())
            assert "[Web Warmup] Cannot edit note" in log
            assert "persistent storage is not configured" in log

    asyncio.run(exercise())
