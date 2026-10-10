---
name: subprocess-solver-execution
description: Create and run challenge solvers using safe argument lists, bounded subprocesses, separate output capture, cancellation, and clear warnings.
---

# Subprocess and Solver Execution

Use this skill when creating, editing, or running challenge solver files.

## Code ownership

The standalone editor invocation is in `src/ctfwb/editor.py`. Solver template
and execution code is implemented in `src/ctfwb/solvers/`; keep related modules
and templates in that package rather than adding them at the package root.

## Guidance

- Treat solvers as arbitrary code running with the user's permissions.
- Warn the user before the first solver run that execution is not sandboxed.
- Warn that solver output may include flags or other sensitive data.
- Invoke editors and solvers with argument lists; do not interpolate commands
  through a shell.
- Use the challenge directory as the solver working directory.
- Pass artifact paths as separate arguments.
- Capture stdout and stderr separately and report the return code.
- Enforce a configurable finite timeout and support cancellation.
- Report cancellation distinctly from ordinary failure.
- Do not parse or automatically register flags in solver output.
- Enable Bash execution only when explicitly configured.
- Test paths with spaces, nonzero exits, output streams, timeouts, and
  cancellation.
