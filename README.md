# CTF Workbench

CTF Workbench is a keyboard-first terminal interface for organizing Capture
The Flag (CTF) events. You can add CTFs manually or prefill their details from
a CTFtime event page. You can add challenges manually from a CTF's challenge
view or import challenge details and artifact references from CTFd. CTFs and
challenges are saved to the per-user data directory.

## Requirements

- Python 3.10 or newer
- A terminal that supports Textual

## Install and run

From the project directory, create and activate a virtual environment, then
install the project:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Start the interface with either command:

```sh
ctf-workbench
# or
python -m ctfwb
```

Check optional external tools used by solver helpers with:

```sh
ctf-workbench doctor
```

The command reports each registered tool as installed or missing and exits
nonzero if any are unavailable. It does not need the application configuration
or start the TUI.

Errors are written to `logs/ctf-workbench.log` under the configured data
directory. Pass `--debug` to either command to include exception types,
traceback frames, and CTFd HTTP status codes for failures; trace records omit
exception text to avoid echoing sensitive request details. Logs rotate at 1 MB
and retain three backups. Log files are owner-only on POSIX systems. CTFd
tokens are never written to logs.

Use the arrow keys or `j`/`k` to move through the CTF list. Press `a` to open
the **Add CTF** form. Only the name is required; year, platform URL, and
description are optional. Enter the details manually or provide an HTTPS
CTFtime event URL and choose **Parse URL** to prefill the form. Review and
confirm the details before adding the CTF. Press `e` to edit the selected CTF;
the form is prefilled and keeps its stable ID and challenge data. Press `d` to
remove it; confirm the prompt to delete the CTF and its saved challenges and
files.

Press `Enter` on a CTF to open its challenge view, and `Esc` to return to the
CTF list. The next launch opens the challenge view for the most recently opened
CTF, when that CTF is still available. In the challenge view, press `a` to add
a challenge manually; name is required, and category, points, and description
are optional. Press `e` to edit the selected challenge, including status, flag,
and artifact metadata. Artifact metadata is entered as a JSON list; each entry
has a stored `filename` and may include `original_filename` and `source_url`.
Challenge details show each artifact's stored filename with its
downloaded/not-downloaded status. The challenge list shows a
right-aligned, color-coded status badge at the end of each challenge name:
UNSOLVED, IN PROG, SOLVED, or SKIPPED. Press `d` to remove a challenge and
confirm deletion of its saved files. Press `t` to open the status selector and
choose unsolved, in progress, solved, or skipped. Press `f` to
open the flag editor; it is prefilled when a flag is set, and saving it empty
clears the flag. Adding a new flag marks the challenge solved, while editing or
clearing an existing flag leaves its status unchanged. Flag values are visible
when entered and in the challenge details. Challenge action logs include the
challenge name and flag value when a flag is added or updated. Use the arrow
keys or `j`/`k` to move through challenges. Press `Tab` to switch between the
challenge list and details; use the arrow keys or `j`/`k` to scroll the focused
pane, and `Ctrl-D`/`Ctrl-U` to page down/up. Notes from the selected challenge's
`notes.md` are shown in the details pane. Press `n` to edit that note in the
configured editor (default `nvim`). CTF and challenge changes remain in the
data directory across application restarts. The command bar grows to multiple
rows on narrow terminals and returns to one row when there is enough width.
Press `o` to open the selected challenge's artifacts directory in a separate
terminal (the default) or file explorer while Workbench stays running; press
`Esc` to cancel.
For a selected CTFd challenge,
press `x` to preview and download its artifacts; existing files are replaced
only after explicit confirmation. Press `r` to fetch and preview CTFd changes
for the CTF. These contextual actions appear only when applicable. Press `q` to
quit. In the challenge view, press `s` to create a solver from a template,
`v` to edit the solver, and `g` to run it; press `c` to cancel an active run.
Press `b` on either the CTF list or challenge view to create a ZIP backup or
export.

Choose the destination for the ZIP when exporting; a successful export is
written there, and export errors are reported in the shared log. CTFd tokens
and application logs are always excluded. Flags are omitted by default and
included only if you explicitly opt in.

## Importing CTFd challenges

In a CTF's challenge view, press `m` and choose **Paste JSON** or **CTFd API**.
Paste the full JSON text into the validation area. JSON import accepts one of
these CTFd challenge formats:

- A challenge array.
- The CTFd API response envelope, `{"success": true, "data": [...]}`.
- An export object containing `{"challenges": [...]}`.

Challenge records use CTFd's `id`, `name`, `category`, `value` (or `points`),
`description`, and `files` fields. The importer also accepts
`remote_id`, `points`, and validated artifact metadata in JSON. A representative
non-sensitive export is included at
[`tests/fixtures/ctfd/challenges.json`](tests/fixtures/ctfd/challenges.json).
Unsupported or malformed input is rejected before storage is changed.

For a live import, use the CTFd **API v1** challenge endpoint
`GET /api/v1/challenges` and its per-challenge detail endpoint
`GET /api/v1/challenges/{id}`. See the
[CTFd API documentation](https://docs.ctfd.io/docs/api/redoc/).
The list endpoint provides summary data, so the importer also retrieves each
challenge's description and artifact references from its detail
endpoint. It never requests the referenced artifact URLs or downloads file
contents; artifact downloads are separate and are not part of import. Any
short-lived `token` query parameter on CTFd file links is discarded before
metadata is saved. Requests use CTFd's API-token header
(`Authorization: Token <API_TOKEN>`) and `Content-Type: application/json`
(required by CTFd to authenticate API tokens on GET requests), a 10-second
request timeout, and the documented `meta.pagination.pages` count to retrieve
all pages. The importer requires HTTPS and accepts a URL from any page on the
CTFd instance (for example, `https://demo.ctfd.io/challenges`). It appends
`/api/v1/challenges` to the entered URL first; if that request fails, it retries
using only the HTTPS host and appends the same API path. It does not follow
redirects. HTTP 401 is reported as token authentication failure; HTTP 403 is
reported as an access denial, which may be caused by event visibility, timing,
team membership, or email-verification restrictions. Rate limits, malformed
responses, and unavailable servers are also reported without logging the token.

After a successful API response, the entered token is stored in the CTF's
`token.json` with owner-only file permissions on POSIX systems. A saved token
is prefilled in the masked input only for the HTTPS base URL it was configured
with; changing the URL clears the prefilled token. CTFd tokens are not included
in logs. Do not share your data directory or token file.

Both sources show a preview before writing. Exact `remote_id` matches are
listed and left unchanged; name-only collisions are shown as suggestions and
added separately only after confirmation, never silently merged. Import adds
new challenges in one validated storage update and preserves existing flags,
status, solver files, notes, and local challenge data. Artifact metadata is
imported without fetching file contents. The selected challenge's `x` action
downloads its attached files separately; it obtains fresh CTFd file links,
restricts requests to the configured HTTPS host, and writes each file
atomically. New files download directly; if any target already exists, a
preview lists the affected files and requires explicit confirmation before
replacing them in place. The app does not keep artifact versions. Unsafe remote
filenames are sanitized for storage, colliding stored names receive a numeric
suffix, and the original filename remains in artifact metadata. Failed
transfers are reported and leave no partial file.

The `r` action refreshes imported challenges. CTFd imports are refreshed using
the saved platform URL and token; JSON imports are refreshed by pasting a new
CTFd JSON response or export. If both source types are present, choose which to
refresh. Refresh requires stable challenge IDs, previews additions and changed
fields before applying them, preserves local status, flags, solvers, notes,
and local-only artifacts, and retains challenges missing from the latest
source response. Refresh never downloads artifact contents automatically.

For a live CTFd API-imported challenge with a saved token and remote ID, the
flag dialog offers **Save** and **Save and submit**. Submitting is optional:
**Save** stores the flag locally without contacting CTFd, while **Save and
submit** sends it to CTFd for verification. The flag is saved and the challenge
marked solved only after CTFd reports it correct; an incorrect response or
request failure leaves the saved flag and status unchanged. The submitted flag
is never written to logs or error messages.

## Storage and configuration

The application reads an optional TOML configuration file. By default, the
file is `~/.config/ctf-workbench/config.toml` on Linux, under the platform's
Application Support directory on macOS, or `%APPDATA%\ctf-workbench\config.toml`
on Windows. If not configured, data is stored in the operating system's
per-user data directory (`~/.local/share/ctf-workbench` on Linux).

Set a custom location with either a top-level `data_dir` value or the
`[paths]` table:

```toml
[paths]
data_dir = "/path/to/ctf-workbench-data"

[editor]
executable = "nvim"
args = ["--wait"]

[solver]
python_interpreter = "/usr/bin/python3"
timeout_seconds = 30
bash_execution_enabled = false
```

Relative paths are resolved from the configuration file's directory. Data is
stored in versioned `ctfs.json` and per-challenge `information.json` files.
`last_ctf.json` stores the last-opened CTF ID so Workbench can reopen its
challenge view on the next launch.
Updates are written atomically and verified after replacement. Timestamped
backups are removed after verification and retained only if a write or its
verification fails. Versionless legacy documents are validated and migrated to
schema version 1 using the same backup handling.
Only one running instance may use a data directory at a time; a second instance
exits with a lock error. The editor is invoked without a shell, with its
configured arguments followed by the note or solver path. Solver workflows use
the configured Python interpreter (or the current Python interpreter), and the
finite timeout defaults to 30 seconds. Bash template creation is available;
running a Bash solver is disabled unless
`solver.bash_execution_enabled = true` is explicitly configured.

## Solver workflow service

The challenge view provides solver workflows: press `s` to choose a template
and create a solver, `v` to edit it, and `g` to run it. Press `c` to cancel an
active run. The solver backend is also available to callers through
`ctfwb.solvers.SolverService`; `list_templates()` returns the Python templates
with and without artifact arguments and a distinct template-only Bash entry.
`create_solver(ctf_id, challenge_id, template_id)` creates the template in the
challenge directory and records its validated relative path. Existing files
are never replaced unless the caller supplies `overwrite_confirmed=True`.
Solver path traversal and symlink paths are rejected by the storage API.

`edit_solver(ctf_id, challenge_id)` invokes the configured editor executable
and argument list without a shell, and reports launch and nonzero-exit errors.
`run_solver(ctf_id, challenge_id, artifact_paths, cancel_event=...)` runs the
configured Python interpreter with the challenge directory as its working
directory. Each artifact path is an independent process argument. The result
contains an outcome, return code, stdout, and stderr as separate fields;
timeout, cancellation, launch errors, and ordinary exits are distinguishable.
Callers may pass a `warning_callback`; otherwise Python warnings are emitted
before launch. In the TUI, completion opens a scrollable output dialog with
stdout and stderr separated; stderr is highlighted in light red. The **Close**
button is focused by default and aligned to the right. Tab to focus the output
pane when scrolling is needed; its highlighted border indicates focus. Use
arrow keys or `j`/`k` to scroll line by line and `Ctrl-D`/`Ctrl-U` to page. The
dialog has a single **Close** button. The shared log keeps the safety warnings
and run outcome, not the solver output. Output is never parsed or automatically
registered as a flag; flag registration remains an explicit user action.

Before running a solver, the application warns that solver code executes
unsandboxed with the user's permissions and that its output may contain
sensitive flags. A subprocess timeout and the `ctfwb.tools` convenience
helpers do not sandbox it or restrict filesystem or network access. The helper
functions currently include `read_bytes`, `read_text`, and `sha256_file`; use
them only as optional conveniences. `exiftool(path)` returns ExifTool's JSON
metadata for a file and requires the `exiftool` executable on `PATH`; use
`ctf-workbench doctor` to check registered external tools.

## Source layout

The CLI and standalone modules (`app.py`, `config.py`, `ctftime.py`,
`editor.py`, and `logging_setup.py`) live directly in `src/ctfwb/`. Related
multi-file features are grouped into packages: CTFd/JSON import code is in
`ctfwb.importers`, persistence is in `ctfwb.storage`, solver templates and
execution are in `ctfwb.solvers`, helper tools are in `ctfwb.tools`, and
Textual code is in `ctfwb.ui`. The UI app shell and shared coordination are in
`ui/application.py`; screens, models, and workflow dialogs are grouped in
`ui/screens/`, `ui/models/`, and `ui/dialogs/`, respectively. The supported
entry point remains `ctfwb.app`, and the `ctfwb.importers` and
`ctfwb.storage` package APIs re-export their public operations. The former
`ctfwb.imports` import path remains available as a compatibility shim.

## Build

Install the Python package build frontend and create source and wheel
distributions:

```sh
python -m pip install build
python -m build
```

The distribution files are written to `dist/`.

## Test

Install the test dependencies and run the test suite:

```sh
python -m pip install -e ".[test]"
python -m pytest
```

To include a coverage report:

```sh
python -m pytest --cov=ctfwb --cov-report=term-missing
```

## Formatting and linting

Install the linting tools alongside the test dependencies:

```sh
python -m pip install -e ".[test,lint]"
```

Format Python files with Ruff and check formatting before submitting changes:

```sh
ruff format .
ruff format --check .
```

Run the configured linter with:

```sh
ruff check .
```

To automatically fix supported lint issues, run `ruff check --fix .`.

## Contributing

For a change, create a focused branch, keep the change scoped, and add or update
tests and documentation as appropriate. Run the test suite before opening a
pull request, check formatting and linting, and describe the change and any
remaining limitations. The agent and skill files under `.github/` document
implementation ownership and practices.

GitHub Actions runs the tests on Python 3.10 through 3.14, checks Ruff lint and
formatting, and builds source and wheel distributions for pull requests and
pushes to `master`.
