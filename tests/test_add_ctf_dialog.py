"""Tests for the in-memory add-CTF modal workflow."""

import asyncio

import pytest
from textual.widgets import Button, Input, ListView, Static, TextArea

from ctfwb import CTF, CTFWorkbenchApp


def test_keyboard_add_manually_adds_ctf_to_list_and_details() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp()
        async with app.run_test() as pilot:
            await pilot.press("a")
            dialog = app.screen
            dialog.query_one("#ctf-name", Input).value = "  Spring CTF  "
            dialog.query_one("#ctf-year", Input).value = "2026"
            dialog.query_one("#ctf-platform", Input).value = " https://ctf.example "
            dialog.query_one("#ctf-description", TextArea).text = "A practice event."
            await pilot.click("#confirm-add")
            await pilot.pause()

            assert app.query_one("#ctf-details", Static).render()
            details = str(app.query_one("#ctf-details", Static).render())
            assert "Spring CTF" in details
            assert "2026" in details
            assert "https://ctf.example" in details
            assert "A practice event." in details
            assert app.query_one("#ctf-list", ListView).index == 0
            assert "Added CTF: Spring CTF" in str(
                app.query_one("#log-message", Static).render()
            )

    asyncio.run(exercise())


def test_name_is_the_only_required_ctf_field() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp()
        async with app.run_test() as pilot:
            await pilot.press("a")
            app.screen.query_one("#ctf-name", Input).value = "Name Only CTF"
            await pilot.click("#confirm-add")
            await pilot.pause()

            details = str(app.query_one("#ctf-details", Static).render())
            assert "Name Only CTF" in details
            assert "Year: —" in details
            assert "Platform: —" in details
            assert "No description." in details
            assert len(app.query_one("#ctf-list", ListView).children) == 1

    asyncio.run(exercise())


def test_ctftime_parse_populates_form_but_waits_for_confirmation() -> None:
    async def exercise() -> None:
        requested: list[str] = []

        async def lookup(url: str) -> dict[str, object]:
            requested.append(url)
            return {
                "name": "Parsed CTF",
                "year": 2025,
                "platform_url": "https://play.example",
                "description": "Imported as plain text.",
            }

        app = CTFWorkbenchApp(ctftime_lookup=lookup)
        async with app.run_test() as pilot:
            await pilot.press("a")
            dialog = app.screen
            dialog.query_one(
                "#ctftime-url", Input
            ).value = "https://www.ctftime.org/event/123"
            await pilot.click("#parse-url")
            await pilot.pause()

            assert requested == ["https://www.ctftime.org/event/123"]
            assert dialog.query_one("#ctf-name", Input).value == "Parsed CTF"
            assert dialog.query_one("#ctf-year", Input).value == "2025"
            assert (
                dialog.query_one("#ctf-platform", Input).value == "https://play.example"
            )
            assert (
                dialog.query_one("#ctf-description", TextArea).text
                == "Imported as plain text."
            )
            assert (
                "review them, then choose add ctf"
                in str(dialog.query_one("#dialog-error", Static).render()).lower()
            )
            assert "No CTFs yet." in str(app.query_one("#ctf-list", Static).render())

            await pilot.click("#confirm-add")
            await pilot.pause()
            assert app.query_one("#ctf-list", ListView).index == 0
            assert "Parsed CTF" in str(app.query_one("#ctf-details", Static).render())

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("name", "year", "expected_error"),
    [
        ("", "", "Name is required."),
        ("Named CTF", "20xx", "Year must be a whole number"),
        ("Named CTF", "1899", "Year must be between"),
        ("Named CTF", "2101", "Year must be between"),
    ],
)
def test_manual_validation_keeps_dialog_open(
    name: str, year: str, expected_error: str
) -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp()
        async with app.run_test() as pilot:
            await pilot.press("a")
            dialog = app.screen
            dialog.query_one("#ctf-name", Input).value = name
            dialog.query_one("#ctf-year", Input).value = year
            await pilot.click("#confirm-add")
            await pilot.pause()

            assert dialog.is_mounted
            assert expected_error in str(
                dialog.query_one("#dialog-error", Static).render()
            )
            assert expected_error in str(app.query_one("#log-message", Static).render())

    asyncio.run(exercise())


def test_lookup_failure_is_reported_without_adding() -> None:
    async def exercise() -> None:
        async def lookup(_url: str) -> dict[str, object]:
            raise RuntimeError("event service unavailable")

        app = CTFWorkbenchApp(ctftime_lookup=lookup)
        async with app.run_test() as pilot:
            await pilot.press("a")
            dialog = app.screen
            dialog.query_one(
                "#ctftime-url", Input
            ).value = "https://ctftime.org/event/2"
            await pilot.click("#parse-url")
            await pilot.pause()
            assert "event service unavailable" in str(
                dialog.query_one("#dialog-error", Static).render()
            )
            assert "CTFtime lookup failed" in str(
                app.query_one("#log-message", Static).render()
            )
            assert "No CTFs yet." in str(app.query_one("#ctf-list", Static).render())

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/event/2",
        "http://ctftime.org/event/2",
        "https://ctftime.org/event/2?next=1",
    ],
)
def test_invalid_event_url_does_not_call_lookup(url: str) -> None:
    async def exercise() -> None:
        requested: list[str] = []

        async def lookup(url: str) -> dict[str, object]:
            requested.append(url)
            return {}

        app = CTFWorkbenchApp(ctftime_lookup=lookup)
        async with app.run_test() as pilot:
            await pilot.press("a")
            dialog = app.screen
            dialog.query_one("#ctftime-url", Input).value = url
            await pilot.click("#parse-url")
            assert "valid ctftime.org event URL" in str(
                dialog.query_one("#dialog-error", Static).render()
            )
            assert requested == []

    asyncio.run(exercise())


def test_escape_cancels_running_lookup_then_closes_dialog() -> None:
    async def exercise() -> None:
        started = asyncio.Event()

        async def lookup(_url: str) -> dict[str, object]:
            started.set()
            await asyncio.Future()
            return {}

        app = CTFWorkbenchApp(ctftime_lookup=lookup)
        async with app.run_test() as pilot:
            await pilot.press("a")
            dialog = app.screen
            dialog.query_one(
                "#ctftime-url", Input
            ).value = "https://ctftime.org/event/42"
            await pilot.click("#parse-url")
            await asyncio.wait_for(started.wait(), timeout=2)
            assert "Looking up CTFtime event" in str(
                dialog.query_one("#dialog-error", Static).render()
            )
            assert dialog.query_one("#confirm-add", Button).is_disabled
            await pilot.press("escape")
            await pilot.pause()

            assert not dialog.query_one("#confirm-add", Button).is_disabled
            assert "Lookup cancelled." in str(
                dialog.query_one("#dialog-error", Static).render()
            )
            assert (
                "lookup cancelled"
                in str(app.query_one("#log-message", Static).render()).lower()
            )
            assert "No CTFs yet." in str(app.query_one("#ctf-list", Static).render())

            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is not dialog

    asyncio.run(exercise())


def test_new_ctf_list_keeps_keyboard_navigation_working() -> None:
    async def exercise() -> None:
        app = CTFWorkbenchApp([CTF("First"), CTF("Second")])
        async with app.run_test() as pilot:
            await pilot.press("a")
            app.screen.query_one("#ctf-name", Input).value = "Third"
            await pilot.click("#confirm-add")
            await pilot.pause()

            ctf_list = app.query_one("#ctf-list", ListView)
            assert ctf_list.index == 2
            await pilot.press("k")
            assert ctf_list.index == 1
            assert "Second" in str(app.query_one("#ctf-details", Static).render())

    asyncio.run(exercise())
