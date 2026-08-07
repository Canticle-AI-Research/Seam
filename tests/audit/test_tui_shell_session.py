"""`ShellSession` (`seam_runtime/tui/shell.py`): the `!`-mode subprocess layer.

Lifted from the superseded `TextualDashboardApp._execute_shell_command`
(`dashboard.py:1389`) so it is finally unit-testable without a TUI. `shell.py`
itself never imports `textual`, and neither does most of this file; the one
exception is the Settings-Switch test in `TestGateEnabledByTheSettingsSwitch`,
which mounts the real `SettingsPanel` widget and is guarded behind
`textual_required` (HISTORY#539) so a module-level import never aborts the
whole suite on an installation without the `dash` extra.
"""

from __future__ import annotations

import time
from importlib.util import find_spec
from pathlib import Path

import pytest

from seam_runtime.tui import shell
from seam_runtime.tui.shell import (
    DEFAULT_TIMEOUT_SECONDS,
    TIMEOUT_RETURNCODE,
    ShellResult,
    ShellSession,
)

textual_required = pytest.mark.skipif(
    find_spec("textual") is None, reason="textual is not installed"
)


class TestConstruction:
    def test_defaults_to_process_cwd(self) -> None:
        session = ShellSession()
        assert session.cwd == Path.cwd()

    def test_explicit_cwd_is_resolved(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path)
        assert session.cwd == tmp_path.resolve()

    def test_default_timeout(self) -> None:
        session = ShellSession()
        assert session.timeout == DEFAULT_TIMEOUT_SECONDS


class TestCd:
    def test_cd_absolute(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path)
        target = tmp_path / "sub"
        target.mkdir()
        result = session.run(f"cd {target}")
        assert result.returncode == 0
        assert session.cwd == target.resolve()
        assert str(target.resolve()) in result.stdout

    def test_cd_relative(self, tmp_path: Path) -> None:
        (tmp_path / "child").mkdir()
        session = ShellSession(cwd=tmp_path)
        result = session.run("cd child")
        assert result.returncode == 0
        assert session.cwd == (tmp_path / "child").resolve()

    def test_cd_relative_dot_dot(self, tmp_path: Path) -> None:
        (tmp_path / "child").mkdir()
        session = ShellSession(cwd=tmp_path / "child")
        result = session.run("cd ..")
        assert result.returncode == 0
        assert session.cwd == tmp_path.resolve()

    def test_chdir_alias(self, tmp_path: Path) -> None:
        target = tmp_path / "sub"
        target.mkdir()
        session = ShellSession(cwd=tmp_path)
        result = session.run(f"chdir {target}")
        assert result.returncode == 0
        assert session.cwd == target.resolve()

    def test_cd_with_no_argument_goes_home(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path)
        result = session.run("cd")
        assert result.returncode == 0
        assert session.cwd == Path.home().resolve()

    def test_cd_nonexistent_directory_does_not_move_cwd(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path)
        missing = tmp_path / "does-not-exist"
        result = session.run(f"cd {missing}")
        assert result.returncode != 0
        assert "No such directory" in result.stderr
        # cwd is unchanged on failure.
        assert session.cwd == tmp_path.resolve()

    def test_cd_onto_a_file_fails(self, tmp_path: Path) -> None:
        a_file = tmp_path / "not-a-dir.txt"
        a_file.write_text("x", encoding="utf-8")
        session = ShellSession(cwd=tmp_path)
        result = session.run(f"cd {a_file}")
        assert result.returncode != 0
        assert session.cwd == tmp_path.resolve()

    def test_cd_never_raises(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path)
        # Must come back as a ShellResult, not an exception, even for a
        # thoroughly bogus destination.
        result = session.run("cd /this/path/almost/certainly/does/not/exist")
        assert isinstance(result, ShellResult)
        assert result.returncode != 0


class TestPwd:
    def test_pwd(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path)
        result = session.run("pwd")
        assert result.returncode == 0
        assert result.stdout == str(tmp_path.resolve())

    def test_cwd_alias(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path)
        result = session.run("cwd")
        assert result.returncode == 0
        assert result.stdout == str(tmp_path.resolve())

    def test_pwd_reflects_a_prior_cd(self, tmp_path: Path) -> None:
        (tmp_path / "child").mkdir()
        session = ShellSession(cwd=tmp_path)
        session.run("cd child")
        result = session.run("pwd")
        assert result.stdout == str((tmp_path / "child").resolve())


class TestSubprocess:
    """Subprocess behaviour with the gate ON -- gate behaviour itself (off by
    default, per-call re-read, the Settings-Switch string) lives in
    `TestShellGate` and `TestGateEnabledByTheSettingsSwitch` below."""

    @pytest.fixture(autouse=True)
    def _gate_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(shell.ALLOW_SHELL_ENV, "1")

    def test_stdout_capture(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path)
        result = session.run("echo hello-seam")
        assert result.returncode == 0
        assert result.stdout.strip() == "hello-seam"

    def test_stderr_capture(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path)
        result = session.run("echo oops 1>&2")
        assert result.returncode == 0
        assert result.stderr.strip() == "oops"

    def test_nonzero_exit_code(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path)
        result = session.run("exit 7")
        assert result.returncode == 7

    def test_command_runs_in_session_cwd(self, tmp_path: Path) -> None:
        (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
        session = ShellSession(cwd=tmp_path)
        result = session.run("ls")
        assert "marker.txt" in result.stdout

    def test_shell_syntax_is_honoured(self, tmp_path: Path) -> None:
        """`shell=True` by design (Part 2 of the task): pipes and chaining
        work, unlike the old allowlisted `shell=False` dashboard shell."""
        session = ShellSession(cwd=tmp_path)
        result = session.run("echo a && echo b")
        assert result.returncode == 0
        assert "a" in result.stdout
        assert "b" in result.stdout

    def test_result_reports_cwd_and_is_never_negative_duration(
        self, tmp_path: Path
    ) -> None:
        session = ShellSession(cwd=tmp_path)
        result = session.run("true")
        assert result.cwd == str(tmp_path.resolve())
        assert result.duration >= 0.0

    def test_never_raises_for_a_missing_binary(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path)
        result = session.run("this-command-does-not-exist-anywhere")
        assert isinstance(result, ShellResult)
        assert result.returncode != 0


class TestTimeout:
    @pytest.fixture(autouse=True)
    def _gate_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(shell.ALLOW_SHELL_ENV, "1")

    def test_timeout_returns_distinct_code_not_an_exception(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path, timeout=0.2)
        started = time.monotonic()
        result = session.run("sleep 5")
        elapsed = time.monotonic() - started
        assert isinstance(result, ShellResult)
        assert result.returncode == TIMEOUT_RETURNCODE
        assert result.returncode != 0
        assert "timed out" in result.stderr.lower()
        # Actually bounded by the timeout, not the full sleep duration.
        assert elapsed < 4.0

    def test_timeout_does_not_move_cwd(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path, timeout=0.2)
        session.run("sleep 5")
        assert session.cwd == tmp_path.resolve()


class TestEmptyCommand:
    def test_empty_command_is_a_clear_error_not_a_crash(self, tmp_path: Path) -> None:
        session = ShellSession(cwd=tmp_path)
        result = session.run("   ")
        assert result.returncode != 0
        assert result.stderr


class TestShellGate:
    """`SEAM_DASHBOARD_ALLOW_SHELL`, HISTORY#272's master gate restored (not
    its allowlisted `shell=False` rewrite -- see `shell.py`'s module
    docstring): off by default, `cd`/`pwd` unaffected, re-read per call."""

    def test_gate_off_by_default_refuses_and_spawns_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(shell.ALLOW_SHELL_ENV, raising=False)
        calls: list[tuple[object, object]] = []
        monkeypatch.setattr(shell.subprocess, "run", lambda *a, **k: calls.append((a, k)))

        session = ShellSession(cwd=tmp_path)
        result = session.run("echo should-not-run")

        # Asserting only the refusal message would still pass if the command
        # actually ran (its output is simply discarded) -- the process must
        # never even be spawned.
        assert calls == []
        assert result.returncode != 0
        assert shell.ALLOW_SHELL_ENV in result.stderr
        assert "Settings" in result.stderr

    def test_gate_on_runs_normally(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(shell.ALLOW_SHELL_ENV, "1")
        session = ShellSession(cwd=tmp_path)
        result = session.run("echo shell-is-on")
        assert result.returncode == 0
        assert result.stdout.strip() == "shell-is-on"

    def test_cd_and_pwd_work_with_the_gate_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(shell.ALLOW_SHELL_ENV, raising=False)
        (tmp_path / "child").mkdir()
        session = ShellSession(cwd=tmp_path)
        assert session.run("cd child").returncode == 0
        pwd_result = session.run("pwd")
        assert pwd_result.returncode == 0
        assert pwd_result.stdout == str((tmp_path / "child").resolve())

    def test_cd_and_pwd_work_with_the_gate_on(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(shell.ALLOW_SHELL_ENV, "1")
        (tmp_path / "child").mkdir()
        session = ShellSession(cwd=tmp_path)
        assert session.run("cd child").returncode == 0
        pwd_result = session.run("pwd")
        assert pwd_result.returncode == 0
        assert pwd_result.stdout == str((tmp_path / "child").resolve())

    def test_gate_is_re_read_per_call_no_new_session_needed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(shell.ALLOW_SHELL_ENV, raising=False)
        session = ShellSession(cwd=tmp_path)  # constructed while the gate is off

        refused = session.run("echo flip-me")
        assert refused.returncode != 0
        assert shell.ALLOW_SHELL_ENV in refused.stderr

        monkeypatch.setenv(shell.ALLOW_SHELL_ENV, "1")  # flip mid-session
        allowed = session.run("echo flip-me")  # same session, never reconstructed
        assert allowed.returncode == 0
        assert allowed.stdout.strip() == "flip-me"

        monkeypatch.delenv(shell.ALLOW_SHELL_ENV, raising=False)  # flip back off
        refused_again = session.run("echo flip-me")
        assert refused_again.returncode != 0
        assert shell.ALLOW_SHELL_ENV in refused_again.stderr


class TestShellTimeoutEnv:
    """`SEAM_SHELL_TIMEOUT_SECONDS`, `dashboard.py:206`'s `_get_shell_timeout`
    twin: read fresh per call, 10.0 default, invalid value falls back to
    10.0. An explicit constructor `timeout=` still pins the value (that is
    what lets `TestTimeout` above force a short deterministic timeout)."""

    @pytest.fixture(autouse=True)
    def _gate_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(shell.ALLOW_SHELL_ENV, "1")

    def test_unset_env_is_the_10s_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(shell.TIMEOUT_ENV, raising=False)
        session = ShellSession(cwd=tmp_path)
        assert session.timeout == DEFAULT_TIMEOUT_SECONDS == 10.0

    def test_env_value_is_honoured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(shell.TIMEOUT_ENV, "0.2")
        session = ShellSession(cwd=tmp_path)  # no explicit constructor override
        assert session.timeout == 0.2
        started = time.monotonic()
        result = session.run("sleep 5")
        elapsed = time.monotonic() - started
        assert result.returncode == TIMEOUT_RETURNCODE
        assert elapsed < 4.0

    def test_invalid_env_value_falls_back_to_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(shell.TIMEOUT_ENV, "not-a-number")
        session = ShellSession(cwd=tmp_path)
        assert session.timeout == DEFAULT_TIMEOUT_SECONDS

    def test_explicit_constructor_timeout_overrides_the_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(shell.TIMEOUT_ENV, "999")
        session = ShellSession(cwd=tmp_path, timeout=0.2)
        assert session.timeout == 0.2

    def test_timeout_is_re_read_per_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(shell.TIMEOUT_ENV, raising=False)
        session = ShellSession(cwd=tmp_path)
        assert session.timeout == DEFAULT_TIMEOUT_SECONDS
        monkeypatch.setenv(shell.TIMEOUT_ENV, "0.2")
        assert session.timeout == 0.2


@textual_required
class TestGateEnabledByTheSettingsSwitch:
    """Whatever string the Settings tab's `bool` Switch persists must be a
    string that actually enables this gate.

    The old dashboard checked `os.environ.get(...) != "1"` exactly
    (`dashboard.py:1446`) -- an exact-match trap: if the Switch ever wrote
    something else (`"true"`, `"True"`, ...) that old check would silently
    reject it, and an operator who flipped the Switch on would see `!`
    keep refusing with no clue why. This test drives the real widget rather
    than trusting a read of `settings_screen.py`'s source.
    """

    def test_switch_on_persists_a_value_that_enables_the_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from textual.app import App, ComposeResult
        from textual.widgets import Switch

        from seam_runtime import config
        from seam_runtime.tui.settings_screen import SettingRow, SettingsPanel

        monkeypatch.delenv(shell.ALLOW_SHELL_ENV, raising=False)
        # Isolate from whatever this machine's own operator has persisted --
        # matches `test_tui_supersedes_dashboard.py`'s
        # `test_mounts_with_export_lines_and_junk_names`.
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "settings.env")

        class _Harness(App[None]):
            def compose(self) -> ComposeResult:
                yield SettingsPanel()

        persisted: list[str] = []

        async def _check() -> None:
            app = _Harness()
            async with app.run_test(size=(200, 60)) as pilot:
                await pilot.pause()
                switch = app.query_one("#set-seam-dashboard-allow-shell", Switch)
                switch.value = True
                await pilot.pause()
                row = next(
                    r for r in app.query(SettingRow)
                    if r.setting.name == shell.ALLOW_SHELL_ENV
                )
                persisted.append(row.raw_value())

        asyncio.run(_check())

        assert persisted, "SEAM_DASHBOARD_ALLOW_SHELL row was not found on the mounted panel"
        value = persisted[0]
        assert value, "the Switch persisted an empty string for its ON state"
        # Pin today's actual behaviour: the Switch writes the literal "1",
        # which the OLD `!= "1"` exact-match check would have accepted fine.
        # If this ever changes, this assertion (not just the functional one
        # below) is what will catch it.
        assert value == "1"

        monkeypatch.setenv(shell.ALLOW_SHELL_ENV, value)
        session = ShellSession(cwd=tmp_path)
        result = session.run("echo settings-switch-enabled-me")
        assert result.returncode == 0
        assert "settings-switch-enabled-me" in result.stdout
