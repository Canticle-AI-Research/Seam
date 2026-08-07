"""Local shell execution for the SEAM TUI's `!` mode.

Lifted from the semantics of the superseded `TextualDashboardApp.
_execute_shell_command` (`dashboard.py:1389`, read for this rewrite but never
imported or modified: it lives nested inside a class inside a factory
function and is not an importable symbol) -- only there the `cd`/`pwd`
handling and the "render cwd + exit code" framing were trapped inside a
Textual App class, which made them impossible to unit test without a running
TUI. `ShellSession` is the same behaviour with the TUI cut away.

Operator decision on the security posture (`docs/roadmap/TUI_OPERATOR_SURFACE.md`
S2b): subprocess commands run with the operator's own shell via
`subprocess.run(shell=True, ...)`, unconditionally, once enabled --
HISTORY#272's allowlisted `shell=False` rewrite of `dashboard.py`'s
`_run_shell_subprocess` is deliberately NOT restored here, because pipes,
globs, `&&` chaining and `~` expansion are most of why `!` is worth having
over a plain allowlisted command runner, and `shell=False` would kill all of
them. What IS restored from that same HISTORY#272 entry is its master gate:
`_run_subprocess` below refuses every subprocess command unless
`SEAM_DASHBOARD_ALLOW_SHELL` is truthy in the process environment -- off by
default, exactly like the dashboard's original gate, and one Switch away in
the TUI's own Settings tab (`SEAM_DASHBOARD_ALLOW_SHELL` is already a
registered `bool` Setting in `config.py`'s "Dashboard" group). The gate (and
`SEAM_SHELL_TIMEOUT_SECONDS`, its twin from `dashboard.py:206`) is read fresh
from the environment on every call rather than cached at construction, so
flipping the Switch takes effect on the next `!` without relaunching the
TUI. `cd`/`pwd` are unaffected by the gate: they spawn no subprocess,
matching where HISTORY#272 put the gate originally (inside
`_run_shell_subprocess`, not around `cd`).

No `textual` import here on purpose: this module is unit-testable with zero
TUI, which the code it replaces never was.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .. import config

__all__ = [
    "ShellResult",
    "ShellSession",
    "DEFAULT_TIMEOUT_SECONDS",
    "TIMEOUT_RETURNCODE",
    "ALLOW_SHELL_ENV",
    "TIMEOUT_ENV",
    "DISABLED_MESSAGE",
    "shell_enabled",
]

#: Matches the shell convention (bash, GNU coreutils' `timeout`) for "the
#: process was killed after timing out" -- distinct from any real exit code
#: the command itself could have produced.
TIMEOUT_RETURNCODE = 124

DEFAULT_TIMEOUT_SECONDS = 10.0

#: HISTORY#272's master gate, lifted unchanged: off by default. Already a
#: registered `bool` Setting in `config.py`'s "Dashboard" group, so it is
#: already toggleable from the TUI's own Settings tab with no new plumbing.
ALLOW_SHELL_ENV = "SEAM_DASHBOARD_ALLOW_SHELL"

#: Twin of `dashboard.py:206`'s `_get_shell_timeout()` -- same name, same
#: 10.0 default, same fallback on an invalid value. Not imported from there:
#: `dashboard.py` pulls in optional heavy imports at module scope, and this
#: module's whole point is staying importable everywhere without them.
TIMEOUT_ENV = "SEAM_SHELL_TIMEOUT_SECONDS"

#: Shown wherever the gate blocks something: the subprocess refusal's
#: `stderr`, the shell-mode placeholder, and the one-line message printed on
#: latching into a disabled shell mode (`app.py`). One string, so the
#: wording can never drift between those three surfaces.
DISABLED_MESSAGE = (
    f"Shell execution is disabled. Set {ALLOW_SHELL_ENV}=1, or flip it on in "
    "the Settings tab, to enable it."
)


def shell_enabled() -> bool:
    """Return whether `!`-mode subprocess execution is currently allowed.

    Reads `ALLOW_SHELL_ENV` fresh from `os.environ` on every call instead of
    once at construction, because the value can change under a running
    process: saving the Switch in the Settings tab only persists it to the
    settings file (`settings_screen.py`'s `_save`) -- it is the *Reload*
    button (`_reload`, or a fresh relaunch's own startup call) that actually
    calls `config.apply_persisted_to_environ` and mutates `os.environ`. A
    per-construction read would still need a new `ShellSession` (in
    practice, relaunching the TUI) after Reload; a per-call read does not.

    Uses the same truthy vocabulary as every other `bool` Setting
    (`config._TRUTHY`: `1`/`true`/`yes`/`on`, case-insensitively), which
    covers both a hand-edited settings file and the Settings tab's own
    Switch (`SettingRow.raw_value()` persists the literal string `"1"`).
    """
    raw = os.environ.get(ALLOW_SHELL_ENV, "")
    return raw.strip().lower() in config._TRUTHY


def _shell_timeout() -> float:
    """`SEAM_SHELL_TIMEOUT_SECONDS`, read fresh per call like the gate above.

    Twin of `dashboard.py:206`'s `_get_shell_timeout()`: unset means the
    10-second default, and an unparsable value falls back to that same
    default rather than raising.
    """
    raw = os.environ.get(TIMEOUT_ENV)
    if raw is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class ShellResult:
    """The outcome of one `!` command. Never raised -- always returned."""

    command: str
    returncode: int
    stdout: str
    stderr: str
    cwd: str
    duration: float


class ShellSession:
    """Owns a working directory across `!` commands.

    `cd`/`chdir` and `pwd`/`cwd` are handled internally, without a
    subprocess: `cd` expands `~`, resolves relative paths against the
    session's own `cwd` (not the process's), and requires the destination to
    exist and be a directory. Everything else goes to the operator's real
    shell via `subprocess.run(shell=True, ...)`, gated by `ALLOW_SHELL_ENV`
    (see the module docstring) -- `cd`/`pwd` are exempt from that gate; they
    never reach a subprocess.

    Every method here returns a `ShellResult`; it never raises for an
    ordinary failure (a bad directory, a non-zero exit, a timeout, or the
    gate refusing a command). Only a genuine programming error (e.g.
    constructing with an unusable type) would raise, and that is not a case
    this class tries to swallow.
    """

    def __init__(
        self,
        cwd: str | Path | None = None,
        *,
        timeout: float | None = None,
    ) -> None:
        self.cwd: Path = Path(cwd).expanduser().resolve() if cwd is not None else Path.cwd()
        #: `None` (the default) means "read `TIMEOUT_ENV` fresh on every
        #: call" via `_shell_timeout()` above -- the same per-call-read
        #: contract as the gate. An explicit float pins this session to that
        #: value regardless of the environment, which is what lets tests
        #: force a short timeout deterministically.
        self._timeout_override = timeout

    @property
    def timeout(self) -> float:
        if self._timeout_override is not None:
            return self._timeout_override
        return _shell_timeout()

    def run(self, command: str) -> ShellResult:
        """Run one `!`-mode command against this session's `cwd`."""
        command = command.strip()
        if not command:
            return ShellResult(
                command=command, returncode=1, stdout="",
                stderr="Empty shell command.", cwd=str(self.cwd), duration=0.0,
            )

        token, _, remainder = command.partition(" ")
        token = token.lower()
        if token in ("cd", "chdir"):
            return self._cd(command, remainder)
        if token in ("pwd", "cwd") and not remainder.strip():
            return ShellResult(
                command=command, returncode=0, stdout=str(self.cwd),
                stderr="", cwd=str(self.cwd), duration=0.0,
            )
        return self._run_subprocess(command)

    def _cd(self, command: str, remainder: str) -> ShellResult:
        destination = remainder.strip() or str(Path.home())
        target = Path(destination).expanduser()
        if not target.is_absolute():
            target = self.cwd / target
        target = target.resolve()
        if not target.exists() or not target.is_dir():
            return ShellResult(
                command=command, returncode=1, stdout="",
                stderr=f"No such directory: {target}",
                cwd=str(self.cwd), duration=0.0,
            )
        self.cwd = target
        return ShellResult(
            command=command, returncode=0, stdout=f"cwd -> {self.cwd}",
            stderr="", cwd=str(self.cwd), duration=0.0,
        )

    def _run_subprocess(self, command: str) -> ShellResult:
        # The master gate (module docstring, HISTORY#272): read fresh here,
        # not cached from construction, so flipping the Settings-tab Switch
        # takes effect on the very next `!` command with no relaunch. `cd`/
        # `pwd` never reach this method, so they are unaffected by the gate.
        if not shell_enabled():
            return ShellResult(
                command=command, returncode=1, stdout="",
                stderr=DISABLED_MESSAGE, cwd=str(self.cwd), duration=0.0,
            )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            stdout = _decode(exc.stdout)
            stderr = _decode(exc.stderr)
            message = f"Command timed out after {self.timeout:g}s: {command}"
            stderr = f"{stderr}\n{message}".strip() if stderr else message
            return ShellResult(
                command=command, returncode=TIMEOUT_RETURNCODE,
                stdout=stdout, stderr=stderr, cwd=str(self.cwd), duration=duration,
            )
        except OSError as exc:
            duration = time.monotonic() - started
            return ShellResult(
                command=command, returncode=1, stdout="", stderr=str(exc),
                cwd=str(self.cwd), duration=duration,
            )
        duration = time.monotonic() - started
        return ShellResult(
            command=command, returncode=completed.returncode,
            stdout=completed.stdout, stderr=completed.stderr,
            cwd=str(self.cwd), duration=duration,
        )


def _decode(value: str | bytes | None) -> str:
    """`TimeoutExpired.stdout/.stderr` are `str` when `text=True` was passed
    to `subprocess.run` (as it always is here) before the timeout fired, but
    the attribute is typed permissively upstream -- decode defensively rather
    than assume."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value
