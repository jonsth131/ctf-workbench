"""Tests for selecting a CTF and entering its empty challenge view."""

import asyncio

from textual.color import Color
from textual.containers import Vertical
from textual.widgets import ListView, Static

from ctfwb import CTF, CTFWorkbenchApp
from ctfwb.app import CTFChallengeScreen


def test_enter_opens_selected_ctf_challenge_screen_and_escape_returns() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp(
            [
                CTF("Autumn CTF", 2025),
                CTF("[bold]Winter CTF[/bold]", 2026),
            ]
        )
        async with app.run_test() as pilot:
            ctf_list = app.query_one("#ctf-list", ListView)
            main_screen = app.screen
            ctf_list.focus()
            await pilot.press("j")
            assert ctf_list.index == 1

            await pilot.press("enter")
            await pilot.pause()

            challenge_screen = app.screen
            assert isinstance(challenge_screen, CTFChallengeScreen)
            assert "[bold]Winter CTF[/bold]" in str(
                challenge_screen.query_one("#selected-ctf-name", Static).render()
            )
            assert "No challenges yet." in str(
                challenge_screen.query_one("#challenge-list", Static).render()
            )
            assert "Press A to add a challenge." in str(
                challenge_screen.query_one("#challenge-list", Static).render()
            )
            assert "No challenge selected." in str(
                challenge_screen.query_one(
                    "#challenge-details-content", Static
                ).render()
            )
            assert "CTF Workbench ready." in str(
                challenge_screen.query_one("#log-message", Static).render()
            )

            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is main_screen
            assert app.query_one("#ctf-list", ListView).index == 1

    asyncio.run(exercise())


def test_ctf_selection_panels_render_borders_and_focus_highlight() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp([CTF("Winter CTF", 2026)])
        async with app.run_test():
            ctf_panel = app.query_one("#ctf-panel", Vertical)
            details_panel = app.query_one("#detail-panel", Vertical)

            assert ctf_panel.styles.border_top == (
                "round",
                Color(86, 169, 163),
            )
            assert details_panel.styles.border_top == (
                "round",
                Color(57, 122, 120),
            )

    asyncio.run(exercise())


def test_log_remains_visible_and_synchronized_across_ctf_screens() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp([CTF("Winter CTF", 2026)])
        async with app.run_test() as pilot:
            main_screen = app.screen
            app.query_one("#ctf-list", ListView).focus()
            await pilot.press("enter")
            await pilot.pause()

            challenge_screen = app.screen
            app.log_message("Selection remains in memory.")
            assert "Selection remains in memory." in str(
                challenge_screen.query_one("#log-message", Static).render()
            )

            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is main_screen
            assert "Selection remains in memory." in str(
                main_screen.query_one("#log-message", Static).render()
            )

    asyncio.run(exercise())


def test_log_shows_only_the_latest_five_messages_across_screens() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp([CTF("Winter CTF", 2026)])
        async with app.run_test() as pilot:
            main_screen = app.screen
            for index in range(7):
                app.log_message(f"Log {index}")

            expected = [f"Log {index}" for index in range(2, 7)]
            assert (
                str(main_screen.query_one("#log-message", Static).render()).splitlines()
                == expected
            )

            app.query_one("#ctf-list", ListView).focus()
            await pilot.press("enter")
            await pilot.pause()
            challenge_screen = app.screen
            assert (
                str(
                    challenge_screen.query_one("#log-message", Static).render()
                ).splitlines()
                == expected
            )

            app.log_message("Log 7")
            expected = [f"Log {index}" for index in range(3, 8)]
            assert (
                str(
                    challenge_screen.query_one("#log-message", Static).render()
                ).splitlines()
                == expected
            )
            assert (
                str(main_screen.query_one("#log-message", Static).render()).splitlines()
                == expected
            )

    asyncio.run(exercise())
