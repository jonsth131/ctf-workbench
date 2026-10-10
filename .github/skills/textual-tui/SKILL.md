---
name: textual-tui
description: Build and test Textual screens, widgets, bindings, focus behavior, events, and keyboard-first workflows for CTF Workbench.
---

# Textual TUI

Use this skill when implementing or testing CTF Workbench's Textual interface.

## Guidance

- Keep view code focused on presentation and user interaction; delegate domain
  operations to application services.
- Support arrow-key navigation and the corresponding `h`, `j`, `k`, `l`
  bindings where appropriate.
- Make focus and current selection visually clear.
- Preserve the two-pane challenge workflow: list on the left, details on the
  right.
- Keep both challenge panes keyboard-accessible with `Tab` focus switching,
  line scrolling, and page scrolling.
- Display a challenge's local notes in its details pane without creating a
  missing note file as a side effect.
- Use the app shell's shared LOG area for operation messages; do not duplicate
  its state in screens. Keep solver stdout and stderr in the dedicated output
  dialog rather than copying them into the shared log.
- Provide accessible confirmation, error, empty, loading, and cancellation
  states.
- Do not render imported descriptions as executable HTML.
- Never display tokens in logs or routine UI. Show registered flags in
  challenge details and include them in named action logs when added or
  updated.
- Test key workflows with Textual's testing facilities and avoid fragile
  assumptions about terminal rendering.
- Keep the Textual app shell and app-wide coordination in
  `src/ctfwb/ui/application.py`; do not add another screen's layout there.
- Put every screen/view in its own module under `src/ctfwb/ui/screens/`
  (for example, `ctfs.py` for CTF selection and `challenges.py` for the
  challenge list/details screen). Keep a screen's layout, styles, local
  bindings, and view-specific event handlers together. Add a new screen in a
  new file rather than extending `application.py` or an unrelated screen
  module; use app-level coordination for shared behavior.
- Put each UI model in its own module under `src/ctfwb/ui/models/`, named for
  the model (for example, `ctf.py` and `challenge.py`).
- Put dialogs under `src/ctfwb/ui/dialogs/`, grouped by the screen or workflow
  that owns them (`ctfs.py`, `challenges.py`, or `imports.py`); add dialog
  exports to `dialogs/__init__.py` when they are used by other UI modules.
