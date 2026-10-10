"""Tests for manually adding and navigating challenges."""

import asyncio

from textual.color import Color
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, ListView, Static, TextArea

from ctfwb import CTF, Challenge, CTFWorkbenchApp


def test_add_challenge_manually_and_display_details() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp([CTF("Spring CTF")])
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.press("a")
            dialog = app.screen
            dialog.query_one("#challenge-name", Input).value = "  Web Warmup  "
            dialog.query_one("#challenge-category", Input).value = " web "
            dialog.query_one("#challenge-points", Input).value = "100"
            dialog.query_one(
                "#challenge-description", TextArea
            ).text = "Inspect the page."
            await pilot.click("#confirm-challenge")
            await pilot.pause()

            challenge_list = app.screen.query_one("#challenge-list", ListView)
            assert len(challenge_list.children) == 1
            assert challenge_list.index == 0
            details = str(
                app.screen.query_one("#challenge-details-content", Static).render()
            )
            assert "Web Warmup" in details
            assert "Category: web" in details
            assert "Points: 100" in details
            assert "Inspect the page." in details
            assert "\nNOTES\n  None" in details
            assert "[Web Warmup] Challenge added." in str(
                app.screen.query_one("#log-message", Static).render()
            )

    asyncio.run(exercise())


def test_challenge_commands_navigate_and_added_challenges_survive_back_navigation() -> (
    None
):
    async def exercise() -> None:
        app = CTFWorkbenchApp(
            [
                CTF("Spring CTF"),
                CTF("Winter CTF"),
            ]
        )
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.press("a")
            app.screen.query_one("#challenge-name", Input).value = "First"
            await pilot.click("#confirm-challenge")
            await pilot.pause()

            await pilot.press("a")
            app.screen.query_one("#challenge-name", Input).value = "Second"
            await pilot.click("#confirm-challenge")
            await pilot.pause()

            await pilot.press("k")
            assert "First" in str(
                app.screen.query_one("#challenge-details-content", Static).render()
            )
            await pilot.press("down")
            assert "Second" in str(
                app.screen.query_one("#challenge-details-content", Static).render()
            )
            await pilot.press("escape")
            await pilot.pause()

            await pilot.press("j")
            await pilot.press("enter")
            await pilot.pause()
            assert "No challenges yet." in str(
                app.screen.query_one("#challenge-list", Static).render()
            )

            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("k")
            await pilot.press("enter")
            await pilot.pause()
            assert len(app.screen.query_one("#challenge-list", ListView).children) == 2
            await pilot.press("down")
            assert "Second" in str(
                app.screen.query_one("#challenge-details-content", Static).render()
            )

    asyncio.run(exercise())


def test_challenge_panels_switch_focus_and_support_line_and_page_scrolling() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp([CTF("Spring CTF")])
        app._challenges[0] = [
            Challenge(
                f"Challenge {index}",
                description="\n".join(f"Description line {line}" for line in range(60)),
            )
            for index in range(40)
        ]
        async with app.run_test() as pilot:
            await pilot.press("enter")
            screen = app.screen
            challenge_list = screen.query_one("#challenge-list", ListView)
            details = screen.query_one("#challenge-details", VerticalScroll)
            challenge_panel = screen.query_one("#challenge-panel", Vertical)
            details_panel = screen.query_one("#challenge-detail-panel", Vertical)

            assert challenge_list.has_focus
            assert challenge_panel.has_focus_within
            assert challenge_panel.styles.border_top[1] == Color(86, 169, 163)
            assert not details_panel.has_focus_within
            await pilot.press("tab")
            assert details.has_focus
            assert not challenge_panel.has_focus_within
            assert details_panel.has_focus_within
            assert details_panel.styles.border_top[1] == Color(86, 169, 163)

            await pilot.press("j")
            await pilot.pause()
            assert details.scroll_y > 0
            assert challenge_list.index == 0
            previous_offset = details.scroll_y

            await pilot.press("ctrl+d")
            await pilot.pause()
            assert details.scroll_y > previous_offset
            page_down_offset = details.scroll_y

            await pilot.press("ctrl+u")
            await pilot.pause()
            assert details.scroll_y < page_down_offset

            line_offset = details.scroll_y
            await pilot.press("down")
            await pilot.pause()
            assert details.scroll_y > line_offset
            await pilot.press("up")
            await pilot.pause()
            assert details.scroll_y == line_offset
            await pilot.press("k")
            await pilot.pause()
            assert details.scroll_y < line_offset

            await pilot.press("tab")
            assert challenge_list.has_focus
            await pilot.press("down")
            assert challenge_list.index == 1
            await pilot.press("ctrl+d")
            await pilot.pause()
            assert challenge_list.scroll_y > 0
            page_down_offset = challenge_list.scroll_y
            await pilot.press("ctrl+u")
            await pilot.pause()
            assert challenge_list.scroll_y < page_down_offset

    asyncio.run(exercise())


def test_challenge_form_validates_required_name_and_integer_points() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp([CTF("Spring CTF")])
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.press("a")
            dialog = app.screen
            dialog.query_one("#challenge-points", Input).value = "many"
            await pilot.click("#confirm-challenge")
            await pilot.pause()
            assert "Name is required." in str(
                dialog.query_one("#challenge-dialog-error", Static).render()
            )

            await pilot.press("escape")
            await pilot.press("a")
            dialog = app.screen
            dialog.query_one("#challenge-name", Input).value = "Named"
            dialog.query_one("#challenge-points", Input).value = "many"
            await pilot.click("#confirm-challenge")
            await pilot.pause()
            assert "Points must be a whole number." in str(
                dialog.query_one("#challenge-dialog-error", Static).render()
            )
            assert dialog.is_mounted

    asyncio.run(exercise())


def test_challenge_defaults_allow_missing_optional_fields() -> None:
    challenge = Challenge("No Extras")

    assert challenge.category is None
    assert challenge.points is None
    assert challenge.description == ""


def test_challenge_details_use_the_full_scroll_viewport_width() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp([CTF("Spring CTF")])
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.press("enter")
            details = app.screen.query_one("#challenge-details", VerticalScroll)
            content = app.screen.query_one("#challenge-details-content", Static)

            assert content.size.width == details.size.width

    asyncio.run(exercise())
