"""Keyboard coverage for solver and backup/export workflows."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from contextlib import nullcontext
from zipfile import ZipFile

from textual.color import Color
from textual.containers import VerticalScroll
from textual.widgets import Button, Checkbox, Input, Static

from ctfwb import AppConfig, CTFWorkbenchApp, DataStore, generate_id
from ctfwb.storage import utc_timestamp


def _seed_store(tmp_path, *, flag: str | None = None, artifacts=()):
    store = DataStore(tmp_path / "managed-data")
    ctf_id = generate_id()
    challenge_id = generate_id()
    timestamp = utc_timestamp()
    platform_url = "https://ctfd.example"
    store.save_ctfs(
        [
            {
                "id": ctf_id,
                "name": "Keyboard CTF",
                "year": 2026,
                "platform_url": platform_url,
                "description": "",
                "source": "manual",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        ]
    )
    store.save_challenges(
        ctf_id,
        [
            {
                "id": challenge_id,
                "name": "Warmup",
                "category": "misc",
                "points": 50,
                "description": "",
                "artifacts": list(artifacts),
                "status": "unsolved",
                "flag": flag,
                "source": "manual",
                "remote_id": None,
                "solver": None,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        ],
    )
    return store, ctf_id, challenge_id, platform_url


def _config(store, tmp_path, *, timeout: float = 5) -> AppConfig:
    return AppConfig(
        data_dir=store.data_dir,
        config_path=tmp_path / "config.toml",
        python_interpreter=sys.executable,
        solver_timeout_seconds=timeout,
    )


def test_solver_keyboard_create_and_edit_actions(tmp_path, monkeypatch):
    async def exercise() -> None:
        store, ctf_id, challenge_id, _ = _seed_store(tmp_path)
        app = CTFWorkbenchApp(
            data_store=store,
            config=_config(store, tmp_path),
        )
        edited = []

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.press("s")
            await pilot.pause()
            assert app.screen.query_one("#solver-template-list")
            await pilot.press("enter")
            await pilot.pause()

            solver_path = store.challenge_directory(ctf_id, challenge_id) / "solve.py"
            assert solver_path.is_file()
            original = solver_path.read_bytes()
            assert store.load_challenges(ctf_id)[0]["solver"] == {
                "file_type": "python",
                "relative_path": "solve.py",
            }

            await pilot.press("s")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen.query_one("#overwrite-solver-message", Static)
            await pilot.click("#cancel-overwrite-solver")
            await pilot.pause()
            assert solver_path.read_bytes() == original

            monkeypatch.setattr(
                app._solver_service,
                "edit_solver",
                lambda selected_ctf, selected_challenge: edited.append(
                    (selected_ctf, selected_challenge)
                ),
            )
            monkeypatch.setattr(app, "suspend", nullcontext)
            await pilot.press("v")
            await pilot.pause(0.2)
            assert edited == [(ctf_id, challenge_id)]
            assert "Editor session finished." in str(
                app.screen.query_one("#log-message", Static).render()
            )

    asyncio.run(exercise())


def test_solver_run_logs_separate_output_and_never_registers_output_as_flag(
    tmp_path,
):
    async def exercise() -> None:
        artifact_metadata = {"filename": "sample.bin"}
        store, ctf_id, challenge_id, _ = _seed_store(
            tmp_path, artifacts=(artifact_metadata,)
        )
        artifact_path = store.save_artifact(
            ctf_id, challenge_id, "sample.bin", [b"fixture"]
        )
        store.create_solver_file(
            ctf_id,
            challenge_id,
            "solve.py",
            "python",
            "import sys\n"
            "from pathlib import Path\n"
            "print('artifact:' + Path(sys.argv[1]).name)\n"
            "print('FLAG{output-only}', file=sys.stderr)\n",
        )
        app = CTFWorkbenchApp(
            data_store=store,
            config=_config(store, tmp_path),
        )

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.press("g")
            await pilot.pause(0.5)
            output = app.screen
            close_button = output.query_one("#close-solver-output", Button)
            scroll = output.query_one("#solver-output-scroll", VerticalScroll)
            assert close_button.has_focus
            assert not scroll.has_focus
            assert output.query_one("#solver-output-stdout", Static)
            assert output.query_one("#solver-output-stderr", Static)
            assert len(list(output.query(Button))) == 1
            assert f"artifact:{artifact_path.name}" in str(
                output.query_one("#solver-output-stdout", Static).render()
            )
            assert "FLAG{output-only}" in str(
                output.query_one("#solver-output-stderr", Static).render()
            )
            assert output.query_one(
                "#solver-output-stderr", Static
            ).styles.color == Color(255, 119, 119)
            await pilot.click("#close-solver-output")
            await pilot.pause()
            log = str(app.screen.query_one("#log-message", Static).render())
            assert "WARNING: Solver output may contain flags" in log
            assert "artifact:" not in log
            assert "FLAG{output-only}" not in log
            assert "output is never parsed or registered as a flag" in log

        record = store.load_challenges(ctf_id)[0]
        assert record["flag"] is None
        assert record["status"] == "unsolved"

    asyncio.run(exercise())


def test_solver_output_dialog_scrolls_both_streams(tmp_path):
    async def exercise() -> None:
        store, ctf_id, challenge_id, _ = _seed_store(tmp_path)
        output = "\n".join(f"output line {index}" for index in range(80))
        store.create_solver_file(
            ctf_id,
            challenge_id,
            "solve.py",
            "python",
            f"print({output.splitlines()!r}[0])\n"
            f"print({output!r})\n"
            "import sys\n"
            f"print({output!r}, file=sys.stderr)\n",
        )
        app = CTFWorkbenchApp(
            data_store=store,
            config=_config(store, tmp_path),
        )

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("enter")
            await pilot.press("g")
            await pilot.pause(0.5)
            scroll = app.screen.query_one("#solver-output-scroll", VerticalScroll)
            close_button = app.screen.query_one("#close-solver-output", Button)
            assert close_button.has_focus
            assert scroll.scroll_y == 0
            await pilot.press("tab")
            assert scroll.has_focus
            assert scroll.styles.border_top[1] == Color(86, 169, 163)
            await pilot.press("ctrl+d")
            await pilot.pause()
            assert scroll.scroll_y > 0
            page_offset = scroll.scroll_y
            await pilot.press("down")
            await pilot.pause()
            assert scroll.scroll_y > page_offset
            await pilot.press("escape")

    asyncio.run(exercise())


def test_solver_cancel_keyboard_action_stops_running_process(tmp_path):
    async def exercise() -> None:
        store, ctf_id, challenge_id, _ = _seed_store(tmp_path)
        marker = tmp_path / "solver-started"
        store.create_solver_file(
            ctf_id,
            challenge_id,
            "solve.py",
            "python",
            "from pathlib import Path\n"
            "import time\n"
            f"Path({str(marker)!r}).write_text('started')\n"
            "time.sleep(10)\n",
        )
        app = CTFWorkbenchApp(
            data_store=store,
            config=_config(store, tmp_path, timeout=15),
        )

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.press("g")
            deadline = time.monotonic() + 3
            while not marker.exists() and time.monotonic() < deadline:
                await pilot.pause(0.05)
            assert marker.exists()
            await pilot.press("c")
            await pilot.pause(0.3)
            assert app.screen.query_one("#solver-output-stdout", Static)
            await pilot.press("escape")
            await pilot.pause()
            log = str(app.screen.query_one("#log-message", Static).render())
            assert "Solver cancellation requested." in log
            assert "Solver cancelled." in log

    asyncio.run(exercise())


def test_backup_keyboard_workflow_excludes_tokens_and_opt_in_controls_flags(
    tmp_path,
):
    async def exercise() -> None:
        store, ctf_id, _, platform_url = _seed_store(tmp_path, flag="flag{registered}")
        store.save_ctfd_token(ctf_id, platform_url, "secret-token")
        app = CTFWorkbenchApp(data_store=store)
        default_export = tmp_path / "default-export.zip"
        sensitive_export = tmp_path / "sensitive-export.zip"

        async with app.run_test() as pilot:
            await pilot.press("b")
            app.screen.query_one("#export-archive-destination", Input).value = str(
                default_export
            )
            await pilot.click("#confirm-export-archive")
            await pilot.pause(0.3)
            assert default_export.exists()

            await pilot.press("enter")
            await pilot.press("b")
            checkbox = app.screen.query_one("#export-archive-flags", Checkbox)
            assert not checkbox.value
            checkbox.value = True
            app.screen.query_one("#export-archive-destination", Input).value = str(
                sensitive_export
            )
            await pilot.click("#confirm-export-archive")
            await pilot.pause(0.3)
            assert sensitive_export.exists()

        ctf_prefix = f"ctfs/{ctf_id}/"
        with ZipFile(default_export) as archive:
            assert not any(name.endswith("token.json") for name in archive.namelist())
            information_name = next(
                name
                for name in archive.namelist()
                if name.endswith("/challenges/information.json")
            )
            default_document = json.loads(archive.read(information_name))
        with ZipFile(sensitive_export) as archive:
            assert not any(name.endswith("token.json") for name in archive.namelist())
            sensitive_document = json.loads(archive.read(information_name))

        assert ctf_prefix in information_name
        assert "flag" not in default_document["challenges"][0]
        assert sensitive_document["challenges"][0]["flag"] == "flag{registered}"

    asyncio.run(exercise())
