"""Shared helpers for the test suite."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

from simplay.shell import Shell


def drive(sensor: str, script: str, stdin: str = "") -> str:
    """Feed `script` to the playground the way a user would."""
    shell = Shell(sensor)
    buf = io.StringIO()
    with redirect_stdout(buf):
        for line in script.splitlines():
            shell.onecmd(line)
    return buf.getvalue()
