"""Reusable modal for showing progress during a background operation."""

from __future__ import annotations

from collections.abc import Callable

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, ProgressBar, Static


class LoadingDialog(ModalScreen[None]):
    """Show caller-provided status text and optional cooperative cancellation."""

    BINDINGS = [Binding("escape", "cancel_loading", show=False, priority=True)]

    CSS = """
    LoadingDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #loading-dialog {
        width: 60;
        height: auto;
        border: round #e7c66a;
        background: #0b202b;
        padding: 1 2;
    }

    #loading-title {
        height: 1;
        color: #e7c66a;
        text-style: bold;
        margin-bottom: 1;
    }

    #loading-message {
        height: auto;
    }

    #loading-progress {
        width: 1fr;
        margin-top: 1;
    }

    #loading-actions {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }

    #cancel-loading {
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        message: str,
        *,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.message = message
        self._on_cancel = on_cancel
        self._cancel_requested = False

    def compose(self) -> ComposeResult:
        with Vertical(id="loading-dialog"):
            yield Label("PLEASE WAIT", id="loading-title")
            yield Static(self.message, id="loading-message", markup=False)
            yield ProgressBar(
                total=None,
                show_percentage=False,
                show_eta=False,
                id="loading-progress",
            )
            if self._on_cancel is not None:
                with Horizontal(id="loading-actions"):
                    yield Button("Cancel", id="cancel-loading")

    @on(Button.Pressed, "#cancel-loading")
    def cancel_button_pressed(self) -> None:
        self.action_cancel_loading()

    def action_cancel_loading(self) -> None:
        if self._on_cancel is None or self._cancel_requested:
            return
        self._on_cancel()
        self._cancel_requested = True
        self.query_one("#loading-message", Static).update(
            "Cancellation requested; waiting for the current operation to stop..."
        )
        self.query_one("#cancel-loading", Button).disabled = True
