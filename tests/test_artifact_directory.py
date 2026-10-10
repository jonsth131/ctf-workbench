"""Tests for opening a challenge's managed artifacts directory."""

import asyncio
import subprocess

from textual.widgets import ListView

from ctfwb import CTF, CTFWorkbenchApp, DataStore
from ctfwb.storage import generate_id, utc_timestamp
from ctfwb.ui.artifact_directory import (
    open_directory_in_file_explorer,
    open_directory_in_terminal,
)
from ctfwb.ui.dialogs import OpenArtifactsDirectoryDialog
from ctfwb.ui.models import Challenge
from ctfwb.ui.screens import challenges as challenge_screen_module


def _app_with_stored_challenge(tmp_path):
    store = DataStore(tmp_path / "user-data")
    ctf_id = generate_id()
    challenge_id = generate_id()
    now = utc_timestamp()
    store.save_challenges(
        ctf_id,
        [
            {
                "id": challenge_id,
                "name": "Artifact challenge",
                "category": None,
                "points": None,
                "description": "",
                "artifacts": [],
                "status": "unsolved",
                "flag": None,
                "source": "manual",
                "remote_id": None,
                "solver": None,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    app = CTFWorkbenchApp([CTF("Artifacts CTF", id=ctf_id)])
    app._data_store = store
    app._challenges[0] = [Challenge("Artifact challenge", id=challenge_id)]
    return app, store, ctf_id, challenge_id


def test_artifacts_dialog_defaults_to_terminal_and_escape_cancels(tmp_path):
    async def exercise() -> None:
        app, store, ctf_id, challenge_id = _app_with_stored_challenge(tmp_path)
        artifacts_directory = (
            store.data_dir / "ctfs" / ctf_id / "challenges" / challenge_id / "artifacts"
        )
        async with app.run_test() as pilot:
            await pilot.press("enter")
            challenge_screen = app.screen
            await pilot.press("o")
            dialog = app.screen
            assert isinstance(dialog, OpenArtifactsDirectoryDialog)
            options = dialog.query_one("#open-artifacts-options", ListView)
            assert options.has_focus
            assert options.index == 0
            assert not artifacts_directory.exists()

            await pilot.press("tab")
            assert options.index == 1
            await pilot.press("j")
            assert options.index == 2
            await pilot.press("k")
            assert options.index == 1
            await pilot.press("shift+tab")
            assert options.index == 0
            await pilot.press("down")
            assert options.index == 1
            await pilot.press("up")
            assert options.index == 0
            assert challenge_screen.query_one("#challenge-list", ListView).index == 0

            await pilot.press("escape")
            await pilot.pause()

            assert app.screen is not dialog
            assert not artifacts_directory.exists()

    asyncio.run(exercise())


def test_artifacts_dialog_opens_directory_in_terminal_by_default(tmp_path, monkeypatch):
    async def exercise() -> None:
        app, store, ctf_id, challenge_id = _app_with_stored_challenge(tmp_path)
        opened = []
        monkeypatch.setattr(
            challenge_screen_module,
            "open_directory_in_terminal",
            opened.append,
        )
        async with app.run_test() as pilot:
            await pilot.press("enter", "o", "enter")
            await pilot.pause()

            assert opened == [
                store.data_dir
                / "ctfs"
                / ctf_id
                / "challenges"
                / challenge_id
                / "artifacts"
            ]
            assert "Artifacts directory opened in terminal." in str(
                app.screen.query_one("#log-message").render()
            )

    asyncio.run(exercise())


def test_artifacts_dialog_opens_directory_in_file_explorer(tmp_path, monkeypatch):
    async def exercise() -> None:
        app, store, ctf_id, challenge_id = _app_with_stored_challenge(tmp_path)
        opened = []
        monkeypatch.setattr(
            challenge_screen_module,
            "open_directory_in_file_explorer",
            opened.append,
        )
        async with app.run_test() as pilot:
            await pilot.press("enter", "o")
            await pilot.pause()
            options = app.screen.query_one("#open-artifacts-options", ListView)
            assert options.index == 0
            await pilot.press("down", "enter")
            await pilot.pause()

            assert opened == [
                store.data_dir
                / "ctfs"
                / ctf_id
                / "challenges"
                / challenge_id
                / "artifacts"
            ]
            assert "file explorer" in str(app.screen.query_one("#log-message").render())

    asyncio.run(exercise())


def test_file_explorer_launch_failure_is_logged(tmp_path, monkeypatch):
    async def exercise() -> None:
        app, _store, _ctf_id, _challenge_id = _app_with_stored_challenge(tmp_path)

        def fail_open(_directory):
            raise OSError("file manager unavailable")

        monkeypatch.setattr(
            challenge_screen_module,
            "open_directory_in_file_explorer",
            fail_open,
        )
        async with app.run_test() as pilot:
            await pilot.press("enter", "o")
            await pilot.pause()
            await pilot.press("down", "enter")
            await pilot.pause()

            assert "Cannot open file explorer: file manager unavailable" in str(
                app.screen.query_one("#log-message").render()
            )

    asyncio.run(exercise())


def test_terminal_opener_launches_a_new_terminal_with_safe_arguments(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TERMINAL", "custom-terminal --flag")
    shell = "custom shell"
    monkeypatch.setenv("SHELL", shell)
    monkeypatch.setattr(
        "ctfwb.ui.artifact_directory.shutil.which",
        lambda command: (
            "/usr/bin/custom-terminal" if command == "custom-terminal" else None
        ),
    )
    calls = []
    monkeypatch.setattr(
        subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs))
    )

    open_directory_in_terminal(tmp_path)

    args, kwargs = calls[0]
    assert args == (["/usr/bin/custom-terminal", "--flag", "-e", shell],)
    assert kwargs["cwd"] == tmp_path
    assert kwargs["start_new_session"] is True


def test_file_explorer_opener_uses_an_argument_list(monkeypatch, tmp_path):
    monkeypatch.setattr("ctfwb.ui.artifact_directory.sys.platform", "linux")
    monkeypatch.setattr(
        "ctfwb.ui.artifact_directory.shutil.which", lambda _command: "/usr/bin/xdg-open"
    )
    calls = []
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    directory = tmp_path / "artifacts with spaces"

    open_directory_in_file_explorer(directory)

    args, kwargs = calls[0]
    assert args == (["/usr/bin/xdg-open", str(directory)],)
    assert kwargs["cwd"] == directory
    assert kwargs["stdin"] is subprocess.DEVNULL
