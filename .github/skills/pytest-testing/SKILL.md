---
name: pytest-testing
description: Write deterministic pytest tests using fixtures, temporary directories, mocks, parametrization, subprocess tests, and pytest-cov.
---

# pytest Testing

Use this skill when adding or improving CTF Workbench tests.

Test the package interfaces `ctfwb.app`, `ctfwb.importers`, and
`ctfwb.storage` where practical. For implementation-specific monkeypatches,
use the owning package module (for example `ctfwb.storage.data_store`).

## Guidance

- Run pytest and other Python tools from the repository-root `venv/`
  environment. Activate it with `source venv/bin/activate` on macOS/Linux or
  `venv\Scripts\Activate.ps1` in PowerShell, and invoke tests with
  `python -m pytest`. If the environment is missing, create it with
  `python3 -m venv venv` (or `py -m venv venv` on Windows). Do not commit the
  virtual environment.
- Use pytest fixtures to share setup and teardown.
- Use temporary directories for storage and path tests.
- Mock HTTP services and external tools; do not require live services.
- Parameterize validation and failure cases where it improves clarity.
- Test public behavior and safety properties, not private implementation details.
- Cover malformed input, cancellation, timeouts, and partial-failure cases.
- Use controlled subprocess fixtures rather than brittle wall-clock timing.
- Measure coverage with pytest-cov, emphasizing persistence, imports, and solver
  execution.
- Keep fixtures representative and document the schema they exercise.
