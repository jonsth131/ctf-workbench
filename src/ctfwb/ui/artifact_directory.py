"""Open managed artifact directories in a terminal or file explorer."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def open_directory_in_terminal(directory: Path) -> None:
    """Launch a new terminal with the user's shell in the directory."""
    shell = (
        os.environ.get("COMSPEC", "cmd.exe")
        if os.name == "nt"
        else os.environ.get("SHELL", "/bin/sh")
    )
    if os.name == "nt":
        terminal = shutil.which("wt.exe") or shutil.which("wt")
        if terminal is None:
            subprocess.Popen(
                [shell],
                cwd=directory,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return
        _launch([terminal, "-d", str(directory), shell], directory)
        return

    if sys.platform == "darwin":
        terminal = shutil.which("osascript")
        if terminal is None:
            raise FileNotFoundError("Could not find osascript to open Terminal.app.")
        script = (
            "on run argv\n"
            '  tell application "Terminal"\n'
            "    activate\n"
            '    do script "cd " & quoted form of (item 1 of argv)\n'
            "  end tell\n"
            "end run"
        )
        _launch([terminal, "-e", script, str(directory)], directory)
        return

    configured_terminal = os.environ.get("TERMINAL")
    if configured_terminal:
        command = shlex.split(configured_terminal)
        if not command:
            raise FileNotFoundError("The TERMINAL setting is empty.")
        terminal = shutil.which(command[0])
        if terminal is None:
            raise FileNotFoundError(
                f"Could not find configured terminal {command[0]!r}."
            )
        _launch([terminal, *command[1:], "-e", shell], directory)
        return

    terminal = next(
        (
            executable
            for name in (
                "kitty",
                "x-terminal-emulator",
                "gnome-terminal",
                "konsole",
                "xfce4-terminal",
                "xterm",
                "alacritty",
                "foot",
                "wezterm",
            )
            if (executable := shutil.which(name)) is not None
        ),
        None,
    )
    if terminal is None:
        raise FileNotFoundError(
            "No terminal emulator found; set the TERMINAL environment variable."
        )
    _launch([terminal, "-e", shell], directory)


def _launch(arguments: list[str], directory: Path) -> None:
    subprocess.Popen(
        arguments,
        cwd=directory,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
    )


def open_directory_in_file_explorer(directory: Path) -> None:
    """Launch the platform's default file manager for a directory."""
    command = (
        "explorer.exe"
        if os.name == "nt"
        else "open"
        if sys.platform == "darwin"
        else "xdg-open"
    )
    executable = shutil.which(command)
    if executable is None:
        raise FileNotFoundError(f"Could not find {command} to open the directory.")
    subprocess.Popen(
        [executable, str(directory)],
        cwd=directory,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
    )
