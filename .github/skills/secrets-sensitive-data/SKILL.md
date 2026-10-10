---
name: secrets-sensitive-data
description: Protect CTFd tokens and other sensitive values while handling visible challenge flags, logs, exports, persistence, and UI flows.
---

# Secrets and Sensitive Data

Use this skill whenever handling CTFd credentials, flags, solver output, or
exports.

## Code ownership

- Keep CTFd request credential handling in
  `src/ctfwb/importers/ctfd_client.py`.
- Keep saved-token reads and writes behind the `ctfwb.storage` API,
  implemented in `src/ctfwb/storage/data_store.py`.
- Keep log redaction and diagnostic policy in
  `src/ctfwb/logging_setup.py`.
- Keep import credential inputs in `src/ctfwb/ui/dialogs/imports.py`; keep
  challenge flag display and editing in the relevant UI screen and dialog
  modules.

## Guidance

- Never include CTFd tokens in logs, exports, or error messages.
- Send tokens only to the configured CTFd host.
- Do not log sensitive request headers.
- Store tokens separately in the CTF directory as specified by the design.
- Display registered flags in challenge details and include them in named
  challenge action logs when added or updated.
- Include flags in an export only after explicit user opt-in.
- Do not automatically register or persist flags found in solver output.
- Never expose CTFd tokens in logs, errors, or UI output.
- Test token redaction and verify challenge flag log entries using distinctive
  sentinel values.
