"""Tests for the initial CTF listing screen."""

import asyncio

from textual.widgets import ListView, Static

from ctfwb import CTF, CTFWorkbenchApp


def test_empty_app_shows_empty_ctf_list_and_log() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp()
        async with app.run_test() as _pilot:
            assert "No CTFs yet." in str(app.query_one("#ctf-list", Static).render())
            assert "CTF Workbench ready." in str(
                app.query_one("#log-message", Static).render()
            )

    asyncio.run(exercise())


def test_keyboard_selection_updates_ctf_details() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp(
            [
                CTF("Autumn CTF", 2025, "https://ctf.example", "Warm-up event"),
                CTF("Winter CTF", 2024),
            ]
        )
        async with app.run_test() as pilot:
            details = app.query_one("#ctf-details", Static)
            assert "Autumn CTF" in str(details.render())

            await pilot.press("j")
            assert "Winter CTF" in str(details.render())
            assert app.query_one("#ctf-list", ListView).index == 1

            await pilot.press("k")
            assert "Autumn CTF" in str(details.render())

            await pilot.press("down")
            assert "Winter CTF" in str(details.render())
            await pilot.press("up")
            assert "Autumn CTF" in str(details.render())

    asyncio.run(exercise())


def test_ctf_text_is_rendered_as_plain_text() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp(
            [CTF("[bold]Not markup[/bold]", description="<b>plain text</b>")]
        )
        async with app.run_test() as pilot:
            await pilot.press("j")
            rendered = app.query_one("#ctf-details", Static).render()
            assert "[bold]Not markup[/bold]" in str(rendered)
            assert "<b>plain text</b>" in str(rendered)

    asyncio.run(exercise())
