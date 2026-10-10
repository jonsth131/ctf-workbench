"""Tests for updating and removing CTFs from the main screen."""

import asyncio
import json

from textual.widgets import Footer, Input, ListView, Static, TextArea

from ctfwb import CTFWorkbenchApp, DataStore, generate_id
from ctfwb.storage import utc_timestamp


def test_edit_ctf_prefills_form_and_persists_updates(tmp_path) -> None:
    async def exercise() -> None:
        store = DataStore(tmp_path / "user-data")
        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await pilot.press("a")
            app.screen.query_one("#ctf-name", Input).value = "Original CTF"
            app.screen.query_one("#ctf-year", Input).value = "2025"
            app.screen.query_one("#ctf-platform", Input).value = "https://old.example"
            app.screen.query_one("#ctf-description", TextArea).text = "Original details"
            await pilot.click("#confirm-add")

            original = store.load_ctfs()[0]
            store.load_challenges(original["id"])

            await pilot.press("e")
            dialog = app.screen
            assert dialog.query_one("#ctf-name", Input).value == "Original CTF"
            assert dialog.query_one("#ctf-year", Input).value == "2025"
            assert (
                dialog.query_one("#ctf-platform", Input).value == "https://old.example"
            )
            assert (
                dialog.query_one("#ctf-description", TextArea).text
                == "Original details"
            )
            assert "UPDATE CTF" in str(
                dialog.query_one("#dialog-title", Static).render()
            )

            dialog.query_one("#ctf-name", Input).value = "Updated CTF"
            dialog.query_one("#ctf-year", Input).value = "2026"
            dialog.query_one("#ctf-platform", Input).value = "https://new.example"
            dialog.query_one("#ctf-description", TextArea).text = "Updated details"
            await pilot.click("#confirm-add")

            updated = store.load_ctfs()[0]
            assert updated["id"] == original["id"]
            assert updated["created_at"] == original["created_at"]
            assert updated["name"] == "Updated CTF"
            assert updated["year"] == 2026
            assert updated["platform_url"] == "https://new.example"
            assert updated["description"] == "Updated details"
            assert len(store.load_challenges(original["id"])) == 0
            assert "Updated CTF" in str(app.query_one("#ctf-details", Static).render())
            assert "Updated CTF" in str(
                app.query_one("#ctf-list", ListView)
                .children[0]
                .query_one(Static)
                .render()
            )

        restarted = CTFWorkbenchApp(data_store=store)
        async with restarted.run_test():
            assert "Updated CTF" in str(
                restarted.query_one("#ctf-details", Static).render()
            )

    asyncio.run(exercise())


def test_removing_ctf_requires_confirmation_and_deletes_saved_data(tmp_path) -> None:
    async def exercise() -> None:
        store = DataStore(tmp_path / "user-data")
        ctf_id = generate_id()
        timestamp = utc_timestamp()
        store.save_ctfs(
            [
                {
                    "id": ctf_id,
                    "name": "Delete Me",
                    "year": None,
                    "platform_url": None,
                    "description": "",
                    "source": "manual",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
            ]
        )
        store.load_challenges(ctf_id)
        ctf_directory = store.data_dir / "ctfs" / ctf_id
        token_file = ctf_directory / "token.json"
        token_file.write_text(json.dumps({"token": "local-secret"}), encoding="utf-8")

        app = CTFWorkbenchApp(data_store=store)
        async with app.run_test() as pilot:
            await pilot.press("d")
            confirmation = app.screen
            assert "Delete Me" in str(
                confirmation.query_one("#delete-ctf-message", Static).render()
            )
            assert "all its saved challenges and files" in str(
                confirmation.query_one("#delete-ctf-message", Static).render()
            )

            await pilot.press("escape")
            assert store.load_ctfs()[0]["id"] == ctf_id
            assert token_file.exists()

            await pilot.press("d")
            await pilot.click("#confirm-delete-ctf")

            assert store.load_ctfs() == []
            assert not ctf_directory.exists()
            assert "No CTFs yet." in str(app.query_one("#ctf-list", Static).render())
            assert "Select a CTF to view its details." in str(
                app.query_one("#ctf-details", Static).render()
            )
            assert "Removed CTF: Delete Me" in str(
                app.query_one("#log-message", Static).render()
            )
            footer_labels = " ".join(
                str(widget.render()) for widget in app.query_one(Footer).children
            )
            assert "Add" in footer_labels
            assert "Add CTF" not in footer_labels
            bindings = {
                binding.key: binding.description for binding in CTFWorkbenchApp.BINDINGS
            }
            assert bindings["a"] == "Add"
            assert bindings["e"] == "Edit"
            assert bindings["d"] == "Delete"
            assert bindings["j"] == "Next"
            assert bindings["k"] == "Prev"

            await pilot.press("a")
            assert app.screen.query_one("#ctf-name", Input)

    asyncio.run(exercise())
