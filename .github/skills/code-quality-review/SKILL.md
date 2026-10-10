---
name: code-quality-review
description: Review CTF Workbench changes for correctness, maintainability, security, test coverage, and compliance with documented architecture and safety requirements.
---

# Code Quality Review

Use this skill when reviewing implementation changes or preparing a change for
merge.

## Review checklist

- Does the change meet the relevant documented architecture and safety
  requirements?
- Are new files placed in the right package? Keep standalone modules in
  `src/ctfwb/`, importer implementation in `importers/`, persistence
  implementation in `storage/`, and Textual code in `ui/`.
- Does each new screen/view have its own `ui/screens/` file, each UI model its
  own `ui/models/` file, and each dialog belong to the appropriate
  screen/workflow module under `ui/dialogs/`?
- Are public APIs re-exported from `importers/__init__.py` or
  `storage/__init__.py` instead of making callers depend on implementation
  modules? Keep `app.py` as the CLI and compatibility surface.
- Are validation and error paths handled clearly?
- Could it corrupt existing data or overwrite a file unexpectedly?
- Are all managed paths contained under the configured data directory?
- Could logs, errors, or exports expose CTFd tokens or other sensitive values?
- Are challenge flag values logged only in the intended named action entries?
- Are external calls bounded by timeouts and failure handling?
- Are subprocesses invoked without shell interpolation?
- Are user-visible destructive actions explicit and reversible where possible?
- Are tests deterministic and sufficient for edge cases?
- Does documentation describe behavior that actually exists?
