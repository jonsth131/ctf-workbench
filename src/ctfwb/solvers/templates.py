"""Solver template registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SolverTemplate:
    """A named starter file and the metadata needed to create it."""

    template_id: str
    display_name: str
    description: str
    file_type: str
    filename: str
    contents: str


TEMPLATES: tuple[SolverTemplate, ...] = (
    SolverTemplate(
        template_id="python-artifacts",
        display_name="Python (artifact arguments)",
        description="Receives each selected artifact path as a command-line argument.",
        file_type="python",
        filename="solve.py",
        contents='''"""Challenge solver; artifact paths are command-line arguments."""

import sys
from pathlib import Path

from ctfwb.tools import sha256_file


def main() -> int:
    for argument in sys.argv[1:]:
        artifact = Path(argument)
        print(f"{artifact}: {sha256_file(artifact)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    ),
    SolverTemplate(
        template_id="python",
        display_name="Python (no artifact arguments)",
        description="A minimal Python solver that starts without required arguments.",
        file_type="python",
        filename="solve.py",
        contents='''"""Challenge solver starter."""

from pathlib import Path

from ctfwb.tools import read_text


def main() -> int:
    notes = Path("notes.txt")
    print(read_text(notes) if notes.exists() else "Solver ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    ),
    SolverTemplate(
        template_id="bash",
        display_name="Bash (template only)",
        description="Creates a Bash file; running it is separately gated by configuration.",
        file_type="bash",
        filename="solve.sh",
        contents="""#!/usr/bin/env bash
set -euo pipefail

# Artifact paths, if supplied, are available as "$@".
printf 'Solver ready. Received %s artifact argument(s).\\n' "$#"
""",
    ),
)


def get_template(template_id: str) -> SolverTemplate:
    """Return a registered template by stable ID."""
    for template in TEMPLATES:
        if template.template_id == template_id:
            return template
    raise KeyError(f"unknown solver template: {template_id}")


def list_templates() -> tuple[SolverTemplate, ...]:
    """Return all available templates in display order."""
    return TEMPLATES
