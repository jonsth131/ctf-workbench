"""Modal dialogs for imports, CTF management, and challenge actions."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    Static,
    TextArea,
)

from ctfwb.logging_setup import (
    log_debug_exception,
)
from ctfwb.ui.models import CTF, CTFTimeLookup


class AddCTFDialog(ModalScreen[CTF | None]):
    """Add or edit a CTF manually or populate its form from CTFtime."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    AddCTFDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #add-ctf-dialog {
        width: 80;
        max-width: 95%;
        height: auto;
        max-height: 90%;
        border: round #71d6bc;
        background: #0b202b;
        padding: 1 2;
    }

    #dialog-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    .field-label {
        width: 20;
        height: auto;
        color: #9cb8b2;
        content-align: left middle;
    }

    #ctf-name, #ctf-year, #ctf-platform, #ctftime-url, #ctf-description {
        width: 1fr;
    }

    #ctf-name, #ctf-year, #ctf-platform, #ctftime-url {
        height: 1;
        border: none;
        padding: 0 1;
    }

    #ctf-description {
        height: 3;
        border: round #397a78;
    }

    #parse-row, #name-row, #year-row, #platform-row, #description-row,
    #dialog-actions {
        height: auto;
        margin-top: 0;
        align-horizontal: right;
    }

    #parse-url, #cancel-add, #confirm-add {
        height: 1;
        border: none;
        padding: 0 1;
    }

    #ctftime-url {
        width: 1fr;
    }

    #dialog-error {
        height: auto;
        min-height: 1;
        color: #ff9c83;
        margin-top: 1;
    }
    """

    def __init__(self, lookup: CTFTimeLookup, ctf: CTF | None = None) -> None:
        super().__init__()
        self._lookup = lookup
        self._ctf = ctf
        self._lookup_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="add-ctf-dialog"):
            title = (
                "UPDATE CTF // EVENT SETUP"
                if self._ctf is not None
                else "ADD CTF // EVENT SETUP"
            )
            yield Label(title, id="dialog-title")
            with Horizontal(id="parse-row"):
                yield Label("CTFtime URL", classes="field-label")
                yield Input(
                    placeholder="https://ctftime.org/event/123",
                    id="ctftime-url",
                )
                yield Button("Parse URL", id="parse-url", variant="default")
            with Horizontal(id="name-row"):
                yield Label("Name *", classes="field-label")
                yield Input(
                    value=self._ctf.name if self._ctf else "",
                    placeholder="Event name",
                    id="ctf-name",
                )
            with Horizontal(id="year-row"):
                yield Label("Year (optional)", classes="field-label")
                yield Input(
                    value=(
                        str(self._ctf.year)
                        if self._ctf and self._ctf.year is not None
                        else ""
                    ),
                    placeholder="e.g. 2025",
                    id="ctf-year",
                )
            with Horizontal(id="platform-row"):
                yield Label("Platform URL", classes="field-label")
                yield Input(
                    value=(
                        self._ctf.platform_url or "" if self._ctf is not None else ""
                    ),
                    placeholder="https://...",
                    id="ctf-platform",
                )
            with Horizontal(id="description-row"):
                yield Label("Description", classes="field-label")
                yield TextArea(
                    self._ctf.description if self._ctf else "",
                    id="ctf-description",
                )
            yield Static("", id="dialog-error", markup=False)
            with Horizontal(id="dialog-actions"):
                yield Button("Cancel", id="cancel-add")
                yield Button(
                    "Update CTF" if self._ctf else "Add CTF",
                    id="confirm-add",
                    variant="primary",
                )

    @on(Button.Pressed)
    async def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "parse-url":
            self.start_lookup()
        elif event.button.id == "confirm-add":
            self.confirm_add()
        elif event.button.id == "cancel-add":
            self.dismiss(None)

    def start_lookup(self) -> None:
        if self._lookup_task is not None:
            return

        url = self.query_one("#ctftime-url", Input).value.strip()
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            self.report_error(
                "Enter a valid ctftime.org event URL (for example, /event/123)."
            )
            return
        if (
            parsed.scheme.lower() != "https"
            or hostname not in {"ctftime.org", "www.ctftime.org"}
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or re.fullmatch(r"/event/[0-9]+/?", parsed.path) is None
        ):
            self.report_error(
                "Enter a valid ctftime.org event URL (for example, /event/123)."
            )
            return

        self.show_error("Looking up CTFtime event…")
        self.query_one("#parse-url", Button).disabled = True
        self.query_one("#confirm-add", Button).disabled = True
        self._lookup_task = asyncio.create_task(self._populate_from_lookup(url))

    async def _populate_from_lookup(self, url: str) -> None:
        try:
            details = await self._lookup(url)
            self.query_one("#ctf-name", Input).value = str(details.get("name") or "")
            year = details.get("year")
            self.query_one("#ctf-year", Input).value = "" if year is None else str(year)
            self.query_one("#ctf-platform", Input).value = str(
                details.get("platform_url") or ""
            )
            self.query_one("#ctf-description", TextArea).text = str(
                details.get("description") or ""
            )
            self.show_error("Event details loaded. Review them, then choose Add CTF.")
            self.write_log("CTFtime event details loaded; review before adding.")
        except asyncio.CancelledError:
            # Cancellation is initiated by the user through the modal's Escape
            # binding or by dismissing the dialog.
            return
        except Exception as error:
            log_debug_exception("CTFtime lookup failed", error)
            message = str(error).strip() or "Unknown lookup error."
            self.show_error(f"CTFtime lookup failed: {message}")
            self.app.log_error(f"CTFtime lookup failed: {message}")
        finally:
            if self._lookup_task is asyncio.current_task():
                self._lookup_task = None
            if self.is_mounted:
                self.query_one("#parse-url", Button).disabled = False
                self.query_one("#confirm-add", Button).disabled = False

    def confirm_add(self) -> None:
        name = self.query_one("#ctf-name", Input).value.strip()
        year_text = self.query_one("#ctf-year", Input).value.strip()
        if not name:
            self.report_error("Name is required.")
            self.query_one("#ctf-name", Input).focus()
            return

        year: int | None = None
        if year_text:
            try:
                year = int(year_text)
            except ValueError:
                self.report_error("Year must be a whole number between 1900 and 2100.")
                self.query_one("#ctf-year", Input).focus()
                return
            if not 1900 <= year <= 2100:
                self.report_error("Year must be between 1900 and 2100.")
                self.query_one("#ctf-year", Input).focus()
                return

        platform_url = self.query_one("#ctf-platform", Input).value.strip() or None
        description = self.query_one("#ctf-description", TextArea).text
        self.dismiss(CTF(name, year, platform_url, description))

    def show_error(self, message: str) -> None:
        self.query_one("#dialog-error", Static).update(message)

    def report_error(self, message: str) -> None:
        self.show_error(message)
        self.app.log_error(message)

    def write_log(self, message: str) -> None:
        self.app.log_message(message)

    def action_cancel(self) -> None:
        if self._lookup_task is not None:
            self._lookup_task.cancel()
            self.show_error("Lookup cancelled.")
            self.write_log("CTFtime lookup cancelled.")
            return
        self.dismiss(None)

    def on_unmount(self) -> None:
        if self._lookup_task is not None:
            self._lookup_task.cancel()
            self._lookup_task = None


class ConfirmDeleteCTFDialog(ModalScreen[bool]):
    """Require explicit confirmation before removing a CTF and its data."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    ConfirmDeleteCTFDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #confirm-delete-ctf-dialog {
        width: 72;
        max-width: 95%;
        height: auto;
        border: round #ff9c83;
        background: #0b202b;
        padding: 1 2;
    }

    #delete-ctf-title {
        height: 1;
        color: #ff9c83;
        text-style: bold;
        margin-bottom: 1;
    }

    #delete-ctf-message {
        height: auto;
        margin-bottom: 1;
    }

    #delete-ctf-actions {
        height: auto;
        align-horizontal: right;
    }

    #cancel-delete-ctf, #confirm-delete-ctf {
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    def __init__(self, ctf: CTF) -> None:
        super().__init__()
        self.ctf = ctf

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-delete-ctf-dialog"):
            yield Label("REMOVE CTF // CONFIRM", id="delete-ctf-title")
            yield Static(
                f"Remove {self.ctf.name!r} and all its saved challenges and files?",
                id="delete-ctf-message",
                markup=False,
            )
            with Horizontal(id="delete-ctf-actions"):
                yield Button("Cancel", id="cancel-delete-ctf")
                yield Button(
                    "Remove CTF",
                    id="confirm-delete-ctf",
                    variant="error",
                )

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-delete-ctf":
            self.dismiss(True)
        elif event.button.id == "cancel-delete-ctf":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)
