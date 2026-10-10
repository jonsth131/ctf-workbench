"""CTF selection and details view."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static


class CTFSelectionView(Widget):
    """Display the CTF list and details pane in the application home view."""

    DEFAULT_CSS = """
    #workspace {
        height: 1fr;
        padding: 1 2;
    }

    #ctf-panel {
        width: 1fr;
        min-width: 24;
        border: round #397a78;
        padding: 0 1;
    }

    #detail-panel {
        width: 2fr;
        min-width: 30;
        border: round #397a78;
        padding: 0 2;
        margin-left: 1;
    }

    #ctf-panel:focus-within {
        border: round #56a9a3;
    }

    .panel-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    #ctf-list {
        height: 1fr;
        border: none;
        background: transparent;
        scrollbar-gutter: stable;
    }

    #ctf-list > ListItem {
        padding: 0 1;
        color: #d7e4df;
    }

    #ctf-list > ListItem.--highlight {
        background: #176b66;
        color: #ffffff;
        text-style: bold;
    }

    #ctf-details {
        height: 1fr;
        color: #d7e4df;
    }

    #ctf-list.ctf-empty {
        height: 1fr;
        content-align: center middle;
        color: #9cb8b2;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="workspace"):
            with Vertical(id="ctf-panel"):
                yield Label("YOUR CTFS", classes="panel-title")
                if self.app._ctfs:
                    yield self.make_ctf_list()
                else:
                    yield Static(
                        "No CTFs yet.\n\nPress A to add a CTF.",
                        id="ctf-list",
                        classes="ctf-empty",
                        markup=False,
                    )
            with Vertical(id="detail-panel"):
                yield Label("SELECTED CTF", classes="panel-title")
                yield Static(
                    "Select a CTF to view its details.",
                    id="ctf-details",
                    markup=False,
                )

    def on_mount(self) -> None:
        if self.app._ctfs:
            self.query_one("#ctf-list", ListView).focus()

    def make_ctf_list(self) -> ListView:
        return ListView(
            *(ListItem(Static(ctf.name, markup=False)) for ctf in self.app._ctfs),
            id="ctf-list",
        )

    def render_ctf_details(self, index: int) -> None:
        ctf = self.app._ctfs[index]
        details = [
            ctf.name,
            "",
            f"Year: {ctf.year if ctf.year is not None else '—'}",
            f"Platform: {ctf.platform_url or '—'}",
            "",
            ctf.description or "No description.",
        ]
        self.query_one("#ctf-details", Static).update("\n".join(details))

    async def refresh_ctf_list(self, selected_index: int) -> None:
        old_list = self.query_one("#ctf-list")
        await old_list.remove()
        panel = self.query_one("#ctf-panel", Vertical)
        if self.app._ctfs:
            await panel.mount(self.make_ctf_list())
            ctf_list = self.query_one("#ctf-list", ListView)
            selected_index = min(selected_index, len(self.app._ctfs) - 1)
            ctf_list.index = selected_index
            ctf_list.focus()
            self.render_ctf_details(selected_index)
        else:
            await panel.mount(
                Static(
                    "No CTFs yet.\n\nPress A to add a CTF.",
                    id="ctf-list",
                    classes="ctf-empty",
                    markup=False,
                )
            )
            self.screen.set_focus(None)
            self.query_one("#ctf-details", Static).update(
                "Select a CTF to view its details."
            )

    @on(ListView.Highlighted, "#ctf-list")
    def show_ctf_details(self, event: ListView.Highlighted) -> None:
        """Update the details pane when the lightbar moves."""
        index = event.list_view.index
        if index is not None:
            self.render_ctf_details(index)

    @on(ListView.Selected, "#ctf-list")
    def open_selected_ctf(self, event: ListView.Selected) -> None:
        """Open the challenge view for the CTF currently on the lightbar."""
        index = event.list_view.index
        if index is None:
            return
        self.app.open_ctf(index)
