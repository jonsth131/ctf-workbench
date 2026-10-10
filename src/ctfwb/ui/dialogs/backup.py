"""User-invoked data export dialog."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static


class ExportArchiveDialog(ModalScreen[tuple[Path, bool] | None]):
    """Collect a destination and explicit registered-flag export choice."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    ExportArchiveDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #export-archive-dialog {
        width: 76;
        max-width: 95%;
        height: auto;
        border: round #71d6bc;
        background: #0b202b;
        padding: 1 2;
    }

    #export-archive-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    #export-archive-help {
        height: auto;
        margin-bottom: 1;
    }

    #export-archive-destination {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
    }

    #export-archive-flags {
        height: auto;
        margin-top: 1;
    }

    #export-archive-error {
        height: auto;
        min-height: 1;
        color: #ff9c83;
        margin-top: 1;
    }

    #export-archive-actions {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }

    #cancel-export-archive, #confirm-export-archive {
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="export-archive-dialog"):
            yield Label("BACKUP / EXPORT", id="export-archive-title")
            yield Static(
                "Choose a destination archive. CTFd tokens are always excluded. "
                "Flags are excluded unless you explicitly opt in.",
                id="export-archive-help",
                markup=False,
            )
            yield Input(
                placeholder="Destination archive path",
                id="export-archive-destination",
            )
            yield Checkbox(
                "Include registered challenge flags",
                value=False,
                id="export-archive-flags",
            )
            yield Static("", id="export-archive-error", markup=False)
            with Horizontal(id="export-archive-actions"):
                yield Button("Cancel", id="cancel-export-archive")
                yield Button(
                    "Export",
                    id="confirm-export-archive",
                    variant="primary",
                )

    def on_mount(self) -> None:
        self.query_one("#export-archive-destination", Input).focus()

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-export-archive":
            self.confirm_export()
        elif event.button.id == "cancel-export-archive":
            self.dismiss(None)

    def confirm_export(self) -> None:
        destination_text = self.query_one("#export-archive-destination", Input).value
        if not destination_text.strip():
            self.query_one("#export-archive-error", Static).update(
                "Enter a destination path."
            )
            self.query_one("#export-archive-destination", Input).focus()
            return
        destination = Path(destination_text.strip()).expanduser()
        include_flags = self.query_one("#export-archive-flags", Checkbox).value
        self.dismiss((destination, include_flags))

    def action_cancel(self) -> None:
        self.dismiss(None)
