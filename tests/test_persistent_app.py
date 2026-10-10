"""Tests for the app's integration with file-backed storage."""

import asyncio
from pathlib import Path

from textual.widgets import Input, ListView, Static

from ctfwb import AppConfig, CTFWorkbenchApp, DataStore
from ctfwb.app import CTFChallengeScreen, main


def test_manual_ctfs_and_challenges_survive_app_restart(tmp_path) -> None:
    async def exercise() -> None:
        store = DataStore(tmp_path / "user-data")
        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await pilot.press("a")
            app.screen.query_one("#ctf-name", Input).value = "Persisted CTF"
            app.screen.query_one("#ctf-year", Input).value = "2026"
            await pilot.click("#confirm-add")
            await pilot.pause()

            await pilot.press("enter")
            await pilot.press("a")
            app.screen.query_one("#challenge-name", Input).value = "Persisted challenge"
            app.screen.query_one("#challenge-points", Input).value = "250"
            await pilot.click("#confirm-challenge")
            await pilot.pause()

        restarted = CTFWorkbenchApp(data_store=store)
        async with restarted.run_test() as pilot:
            assert isinstance(restarted.screen, CTFChallengeScreen)
            challenge_list = restarted.screen.query_one("#challenge-list", ListView)
            assert len(challenge_list.children) == 1
            details = str(
                restarted.screen.query_one(
                    "#challenge-details-content", Static
                ).render()
            )
            assert "Persisted challenge" in details
            assert "Points: 250" in details

    asyncio.run(exercise())


def test_corrupt_storage_is_reported_and_not_overwritten(tmp_path) -> None:
    async def exercise() -> None:
        store = DataStore(tmp_path / "user-data")
        store.data_dir.mkdir(parents=True)
        path = store.data_dir / "ctfs.json"
        original = '{"schema_version": 1, "ctfs": [}'
        path.write_text(original, encoding="utf-8")

        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            assert str(path) in str(app.query_one("#log-message", Static).render())
            await pilot.press("a")
            app.screen.query_one("#ctf-name", Input).value = "Should not save"
            await pilot.click("#confirm-add")
            await pilot.pause()

        assert path.read_text(encoding="utf-8") == original

    asyncio.run(exercise())


def test_main_holds_and_releases_data_directory_lock(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "configured-data"
    config = AppConfig(data_dir=data_dir, config_path=tmp_path / "config.toml")
    monkeypatch.setattr("ctfwb.app.AppConfig.load", lambda _path=None: config)

    class AppStub:
        def __init__(self, *, data_store, config) -> None:
            self.data_store = data_store
            assert config.editor == "nvim"
            assert config.editor_args == ()

        def run(self) -> None:
            assert (data_dir / ".ctf-workbench.lock").exists()

    monkeypatch.setattr("ctfwb.app.CTFWorkbenchApp", AppStub)

    assert main(Path("ignored.toml")) == 0
    assert not (data_dir / ".ctf-workbench.lock").exists()
