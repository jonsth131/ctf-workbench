---
name: bbs-interface-design
description: Apply a restrained late-1980s-to-mid-1990s BBS visual language to CTF Workbench's keyboard-first TUI.
---

# BBS-Inspired Interface Design

Use this skill when shaping the visual language and navigation of the TUI.

Screen-specific layout and styling belong with each view under
`src/ctfwb/ui/screens/` (currently `ctfs.py` and `challenges.py`). Keep
application-wide LOG history and message handling coordinated through
`src/ctfwb/ui/application.py`. The app shell owns the shared LOG area; screens
should not duplicate its state or logging logic.

## Guidance

- Use compact layouts inspired by classic ANSI-era BBS interfaces.
- Use color and emphasis to clarify selection, status, and hierarchy rather than
  decorate every element.
- Use a lightbar-like selection treatment for lists.
- Keep navigation keyboard-first, supporting arrows and familiar `h`, `j`, `k`,
  `l` movement where appropriate.
- Preserve clear focus indication and accessible contrast.
- Keep the LOG area readable and distinguish messages, errors, and operation
  output.
- Do not let visual styling obscure confirmations, warnings, or sensitive-data
  cautions.
- Keep screens practical at common terminal sizes.
