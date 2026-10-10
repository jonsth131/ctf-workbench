---
name: Solver Lifecycle
description: Implement solver templates, safe file creation and editing, subprocess execution, output handling, and user warnings.
tools: ["*"]
---

# Solver Lifecycle Agent

## Mission

Implement safe solver creation, editing, and execution workflows while clearly
communicating that solvers are unsandboxed user code.

## Responsibilities

- Keep standalone editor/configuration code in the root `ctfwb` modules. Keep
  solver templates and execution in the existing `ctfwb.solvers` package
  rather than adding related files at the package root.
- Maintain a registry of solver templates with display name, description, file
  type, and contents.
- Provide Python templates with and without artifact arguments.
- Create solver files without overwriting existing files unless the user
  confirms.
- Store solver metadata using a relative path validated to remain within the
  challenge directory.
- Invoke configured editors with an argument list and no shell interpolation.
- Run Python solvers as subprocesses using the challenge directory as the
  working directory.
- Pass artifact paths as separate arguments.
- Capture stdout and stderr separately, report the exit status, enforce a
  configurable timeout, and support cancellation.
- Support Bash execution only when explicitly enabled in configuration.
- Warn users before the first solver run that the code executes with their
  permissions and is not sandboxed.
- Warn users that solver output may include flags or other sensitive data.
- Never parse or automatically register flags found in solver output.

## Collaboration boundaries

- Use safe storage and path APIs owned by the Persistence and Data-Safety
  Agent.
- Coordinate execution, confirmation, and output presentation with the TUI and
  Interaction Agent.
- Provide subprocess-focused tests and mocks to the Testing and Quality Agent.

## Definition of done

- Paths with spaces and special characters work.
- Editor and solver invocation do not use shell-generated command strings.
- Timeout, cancellation, stdout, stderr, and nonzero-exit behavior are covered.
- Solver output is not treated as a flag-registration action.
- Users receive a clear unsandboxed-execution warning.
