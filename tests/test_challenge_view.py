"""Tests for manually adding and navigating challenges."""

import asyncio

from textual.color import Color
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, ListView, Static, TextArea

from ctfwb import CTF, Challenge, CTFWorkbenchApp


def _has_colored_text(rendered, text: str, color: str) -> bool:
    expected_color = Color.parse(color)
    return any(
        text in rendered.plain[span.start : span.end]
        and (
            span.style == color
            or getattr(span.style, "foreground", None) == expected_color
        )
        for span in rendered.spans
    )


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
            rendered_details = app.screen.query_one(
                "#challenge-details-content", Static
            ).render()
            details = str(rendered_details)
            assert "Web Warmup" in details
            assert _has_colored_text(rendered_details, "Web Warmup", "#71d6bc")
            assert "Category: web" in details
            assert _has_colored_text(rendered_details, "Category: ", "#d7e4df")
            assert "Points: 100" in details
            assert _has_colored_text(rendered_details, "Points: ", "#d7e4df")
            assert "Status: UNSOLVED" in details
            assert _has_colored_text(rendered_details, "Status: ", "#d7e4df")
            assert _has_colored_text(rendered_details, "UNSOLVED", "#9cb8b2")
            assert "Inspect the page." in details
            assert "Flag: —\n\nInspect the page." in details
            assert _has_colored_text(rendered_details, "Flag: ", "#d7e4df")
            assert _has_colored_text(rendered_details, "Inspect the page.", "#7dcfff")
            assert "\nNOTES\n  None" in details
            assert not _has_colored_text(rendered_details, "  None", "#e7c66a")
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
            await pilot.press("l")
            assert details.has_focus
            assert not challenge_panel.has_focus_within
            assert details_panel.has_focus_within
            assert details_panel.styles.border_top[1] == Color(86, 169, 163)
            await pilot.press("tab")
            assert challenge_list.has_focus
            await pilot.press("tab")
            assert details.has_focus

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

            await pilot.press("h")
            assert challenge_list.has_focus
            await pilot.press("down")
            assert challenge_list.index == 1
            await pilot.press("ctrl+d")
            await pilot.pause()
            assert challenge_list.index == 16
            await pilot.press("ctrl+u")
            assert challenge_list.index == 1
            assert all(
                not binding.show
                for binding in screen.BINDINGS
                if binding.key in {"ctrl+d", "ctrl+u"}
            )

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


def test_challenge_filter_matches_name_and_category_case_insensitively() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp([CTF("Spring CTF")])
        app._challenges[0] = [
            Challenge("Root Me", category="WeB"),
            Challenge("Web Riddle", category="misc"),
            Challenge("Crypto", category="crypto"),
        ]
        async with app.run_test() as pilot:
            await pilot.press("enter")
            screen = app.screen
            challenge_list = screen.query_one("#challenge-list", ListView)
            assert len(challenge_list.children) == 3
            assert any(
                binding.key == "/" and binding.description == "Filter"
                for binding in screen.BINDINGS
            )

            await pilot.press("/")
            await pilot.pause()
            query = screen.query_one("#challenge-filter-query", Input)
            assert query.has_focus
            assert "FILTER:" in str(
                screen.query_one("#challenge-filter-label", Static).render()
            )
            query.value = "wEb"
            await pilot.pause()

            challenge_list = screen.query_one("#challenge-list", ListView)
            assert len(challenge_list.children) == 2
            assert "Root Me" in str(
                screen.query_one("#challenge-details-content", Static).render()
            )
            await pilot.press("enter")
            assert challenge_list.has_focus
            await pilot.press("down")
            assert "Web Riddle" in str(
                screen.query_one("#challenge-details-content", Static).render()
            )
            assert len(screen.challenges) == 3

            query.value = "missing"
            await pilot.pause()
            assert len(screen.query_one("#challenge-list", ListView).children) == 0
            assert "No challenges match the filter." in str(
                screen.query_one("#challenge-details-content", Static).render()
            )

            await pilot.press("escape")
            await pilot.pause()
            assert len(screen.query_one("#challenge-list", ListView).children) == 3
            assert not screen.query_one("#challenge-filter-row").display
            assert screen.query_one("#challenge-filter-query", Input).value == ""

    asyncio.run(exercise())
