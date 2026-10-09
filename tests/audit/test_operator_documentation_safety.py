"""Statically check operator removal, checkout and test-scope documentation.

Never import the installer or execute documented commands. All paths remain
symbolic, including HOME; these tests cannot uninstall or open a user database.
"""

import ast
import re
import shlex
from pathlib import Path, PurePosixPath

import pytest
from markdown_it import MarkdownIt

REPO_ROOT = Path(__file__).resolve().parents[2]
MARKDOWN = MarkdownIt("commonmark", {"html": True})
WINDOWS_NATIVE_COMMANDS = (
    "python -m venv .venv",
    r".\.venv\Scripts\python.exe -m pip install --upgrade pip",
    r".\.venv\Scripts\python.exe -m pip install -r requirements.txt",
    r'.\.venv\Scripts\python.exe -m pip install -e ".[dash]"',
    r".\.venv\Scripts\python.exe -m pytest test_seam_all\test_seam.py tools\history\test_history_tools.py",
    r".\.venv\Scripts\python.exe seam.py doctor",
)
NATIVE_PYTHON = re.compile(r"^(?:python(?:\.exe)?|\.\\\.venv\\Scripts\\python\.exe)\s", re.IGNORECASE)
EXIT_CHECK = re.compile(r'if \(\$LASTEXITCODE -ne 0\) \{ throw "[^"\n]+" \}')


def _section(text: str, title: str, level: int) -> str:
    tokens = MARKDOWN.parse(text)
    starts = [
        index for index, token in enumerate(tokens)
        if token.type == "heading_open" and token.tag == f"h{level}"
        and tokens[index + 1].content == title
    ]
    assert len(starts) == 1, f"Expected exactly one {title!r} section"
    start = starts[0]
    line_start = tokens[start].map[0]
    line_end = len(text.splitlines())
    for token in tokens[start + 1:]:
        if token.type == "heading_open" and int(token.tag[1:]) <= level:
            line_end = token.map[0]
            break
    return "\n".join(text.splitlines()[line_start:line_end])


def _fences(text: str, language: str) -> list[str]:
    return [
        token.content for token in MARKDOWN.parse(text)
        if token.type == "fence" and token.info.strip() == language
    ]


def _macos_layout() -> dict[str, PurePosixPath]:
    tree = ast.parse((REPO_ROOT / "seam_runtime/installer.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "detect_layout")
    branches = [
        node for node in ast.walk(function)
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Call)
        and isinstance(node.test.left.func, ast.Name)
        and node.test.left.func.id == "current_platform_label"
        and len(node.test.comparators) == 1
        and isinstance(node.test.comparators[0], ast.Constant)
        and node.test.comparators[0].value == "macos"
    ]
    assert len(branches) == 1, "Review changed installer macOS layout before changing removal examples"
    assignments = {
        node.targets[0].id: node.value for node in branches[0].body
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
    }

    def symbolic(node: ast.expr) -> PurePosixPath:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return PurePosixPath(node.value)
        if isinstance(node, ast.Name):
            return symbolic(assignments[node.id])
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return symbolic(node.left) / symbolic(node.right)
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "Path"
            and node.func.attr == "home" and not node.args and not node.keywords
        ):
            return PurePosixPath("$HOME")
        raise AssertionError("Unsupported installer path expression; review the static safety contract")

    return {name: symbolic(assignments[name]) for name in ("install_root", "venv_dir", "bin_dir", "persistent_db_path")}


def _assert_runtime_only_removal(block: str, layout: dict[str, PurePosixPath]) -> None:
    allowed = {
        layout["venv_dir"],
        *(layout["bin_dir"] / name for name in _posix_shim_names()),
    }
    targets = []
    for line in block.splitlines():
        args = shlex.split(line, comments=True)
        if not args:
            continue
        assert args[0] == "rm", "Removal example must contain only explicit rm commands"
        targets.extend(PurePosixPath(arg) for arg in args[1:] if not arg.startswith("-"))
    assert set(targets) == allowed and len(targets) == len(allowed), "Removal targets exceed runtime/shim scope"
    database = layout["persistent_db_path"]
    assert all(target != database and target not in database.parents for target in targets)


def _posix_shim_names(source: str | None = None) -> tuple[str, ...]:
    if source is None:
        source = (REPO_ROOT / "seam_runtime/installer.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "write_shims")
    branches = [
        node for node in function.body if isinstance(node, ast.If)
        and isinstance(node.test, ast.Attribute) and node.test.attr == "is_windows"
        and isinstance(node.test.value, ast.Name) and node.test.value.id == "layout"
    ]
    assert len(branches) == 1, "Review changed shim generation before changing removal examples"
    assignments = {
        node.targets[0].id: node.value for node in branches[0].orelse
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
    }
    returns = [node for node in function.body if isinstance(node, ast.Return)]
    assert len(returns) == 1 and isinstance(returns[0].value, ast.Tuple)
    names = []
    for symbol in returns[0].value.elts:
        assert isinstance(symbol, ast.Name)
        value = assignments[symbol.id]
        assert isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div)
        assert isinstance(value.left, ast.Attribute) and value.left.attr == "bin_dir"
        assert isinstance(value.left.value, ast.Name) and value.left.value.id == "layout"
        assert isinstance(value.right, ast.Constant) and isinstance(value.right.value, str)
        names.append(value.right.value)
    assert names and len(names) == len(set(names))
    return tuple(names)


def _assert_native_fail_closed(block: str) -> None:
    # This checks the documented one-line guard contract, not PowerShell execution.
    lines = [line.strip() for line in block.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    native_indices = [index for index, line in enumerate(lines) if NATIVE_PYTHON.match(line)]
    assert native_indices, "Expected native Python commands"
    for index in native_indices:
        assert index + 1 < len(lines) and EXIT_CHECK.fullmatch(lines[index + 1]), (
            "Every native Python invocation needs an immediate nonzero-exit throw check"
        )
    guard_indices = {index for index, line in enumerate(lines) if "$LASTEXITCODE" in line}
    assert guard_indices == {index + 1 for index in native_indices}, "No misplaced or surplus native-exit checks"
    assert lines.count('$ErrorActionPreference = "Stop"') == 1
    assert lines.index('$ErrorActionPreference = "Stop"') < native_indices[0]


def _assert_checkout_prerequisite(section: str) -> None:
    blocks = _fences(section, "powershell")
    assert len(blocks) == 1
    block = blocks[0]
    assert "c:\\users\\" not in block.casefold(), "Personal profile path is not a portable checkout prerequisite"
    assert block.lstrip().startswith("& {"), "Run the root guard and setup as one script block"
    before_venv = block.split("python -m venv .venv", 1)[0]
    assert before_venv != block, "Expected the documented venv command"
    for filename in ("seam.py", "pyproject.toml", "requirements.txt"):
        assert f"Test-Path -LiteralPath .\\{filename} -PathType Leaf" in before_venv
    assert "throw " in before_venv, "Stop before setup outside the reviewed checkout root"
    assert "reviewed SEAM checkout root" in section


def test_macos_ordinary_uninstall_targets_runtime_and_shims_only() -> None:
    text = (REPO_ROOT / "docs/MACOS.md").read_text(encoding="utf-8")
    uninstall = _section(text, "Uninstall", 2)
    blocks = _fences(uninstall, "bash")
    assert blocks
    _assert_runtime_only_removal(blocks[0], _macos_layout())
    prose = " ".join(uninstall.split())
    assert "custom `SEAM_DB_PATH`" in prose
    assert "database and any associated files are outside the removal targets" in prose


@pytest.mark.parametrize("target", [
    "$HOME/Library/Application Support/SEAM",
    "$HOME/Library/Application Support/SEAM/state",
    "$HOME/Library/Application Support/SEAM/state/seam.db",
    "$SEAM_DB_PATH",
])
def test_removal_guard_rejects_persistent_data_targets(target: str) -> None:
    layout = _macos_layout()
    safe = f'rm -rf "{layout["venv_dir"]}"\n' + "\n".join(
        f'rm -f "{layout["bin_dir"] / name}"' for name in _posix_shim_names()
    )
    with pytest.raises(AssertionError, match="runtime/shim scope"):
        _assert_runtime_only_removal(safe + f'\nrm -rf "{target}"', layout)


def test_removal_shim_names_follow_the_installer_source() -> None:
    source = (REPO_ROOT / "seam_runtime/installer.py").read_text(encoding="utf-8")
    original = _posix_shim_names(source)
    assert "seam-benchmark" in original
    changed = _posix_shim_names(source.replace('"seam-benchmark"', '"reviewed-benchmark-name"'))
    assert len(changed) == len(original)
    assert set(changed) - set(original) == {"reviewed-benchmark-name"}
    assert set(original) - set(changed) == {"seam-benchmark"}


def test_data_deletion_is_a_separate_explicit_decision() -> None:
    text = (REPO_ROOT / "docs/MACOS.md").read_text(encoding="utf-8")
    purge = _section(text, "Intentional data deletion", 3)
    prose = " ".join(purge.split())
    assert "separate destructive action" in prose
    assert "SEAM_DB_PATH" in prose and "state/" in prose
    assert "verify your retention or backup procedure" in prose
    assert "does not provide a verified backup or restore procedure" in prose
    assert not _fences(purge, "bash"), "Do not add a generic data-purge command to ordinary uninstall"


def test_windows_repo_local_setup_checks_the_reviewed_checkout_root() -> None:
    text = (REPO_ROOT / "docs/setup.md").read_text(encoding="utf-8")
    section = _section(text, "Repo-Local Development Install", 2)
    # Limit to the Windows subsection; macOS/Linux keep their own examples.
    _assert_checkout_prerequisite(section.split("macOS bash:", 1)[0])


def test_windows_repo_local_setup_stops_after_each_native_failure() -> None:
    text = (REPO_ROOT / "docs/setup.md").read_text(encoding="utf-8")
    section = _section(text, "Repo-Local Development Install", 2).split("macOS bash:", 1)[0]
    blocks = _fences(section, "powershell")
    assert len(blocks) == 1
    actual = tuple(line.strip() for line in blocks[0].splitlines() if NATIVE_PYTHON.match(line.strip()))
    assert actual == WINDOWS_NATIVE_COMMANDS, "Preserve the scoped setup commands and review new native invocations"
    _assert_native_fail_closed(blocks[0])


def _native_guard_fixture() -> list[str]:
    lines = ['& {', '$ErrorActionPreference = "Stop"']
    for index, command in enumerate(WINDOWS_NATIVE_COMMANDS):
        lines.extend((command, f'if ($LASTEXITCODE -ne 0) {{ throw "Native step {index} failed; stop." }}'))
    lines.append('}')
    return lines


@pytest.mark.parametrize("position", range(len(WINDOWS_NATIVE_COMMANDS)))
@pytest.mark.parametrize("defect", ("missing", "misplaced"))
def test_each_native_invocation_rejects_missing_or_misplaced_exit_checks(position: int, defect: str) -> None:
    lines = _native_guard_fixture()
    _assert_native_fail_closed("\n".join(lines))
    index = lines.index(WINDOWS_NATIVE_COMMANDS[position])
    guard = lines.pop(index + 1)
    if defect == "misplaced":
        lines.insert(index, guard)
    with pytest.raises(AssertionError):
        _assert_native_fail_closed("\n".join(lines))


@pytest.mark.parametrize("defect", ("missing", "late"))
def test_native_failure_guard_requires_early_terminating_powershell_errors(defect: str) -> None:
    lines = _native_guard_fixture()
    preference = lines.pop(1)
    if defect == "late":
        lines.insert(4, preference)
    with pytest.raises(AssertionError):
        _assert_native_fail_closed("\n".join(lines))


@pytest.mark.parametrize("defect", ("personal_path", "missing_root_file", "guard_after_venv"))
def test_checkout_guard_rejects_nonportable_or_late_prerequisites(defect: str) -> None:
    guard = "\n".join(f"Test-Path -LiteralPath .\\{name} -PathType Leaf" for name in (
        "seam.py", "pyproject.toml", "requirements.txt",
    ))
    block = "& {\n" + guard + '\nthrow "reviewed SEAM checkout root"\npython -m venv .venv\n}'
    if defect == "personal_path":
        block = block.replace("& {", "& {\ncd C:\\Users\\someone\\Documents\\Codex")
    elif defect == "missing_root_file":
        block = block.replace("Test-Path -LiteralPath .\\seam.py -PathType Leaf", "REMOVED_ROOT_CHECK")
    else:
        block = block.replace("python -m venv .venv", "")
        block = block.replace("& {", "& {\npython -m venv .venv")
    with pytest.raises(AssertionError):
        _assert_checkout_prerequisite("reviewed SEAM checkout root\n```powershell\n" + block + "\n```")


def test_single_file_commands_have_scoped_label_and_broader_coverage_links() -> None:
    text = (REPO_ROOT / "docs/SEAM_OPERATOR_GUIDE.md").read_text(encoding="utf-8")
    testing = _section(text, "6. Testing SEAM", 2)
    tokens = MARKDOWN.parse(testing)
    headings = [tokens[i + 1].content for i, token in enumerate(tokens) if token.type == "heading_open"]
    assert "Run the full suite" not in headings
    scoped = _section(testing, "Run the scoped runtime regression file", 3)
    assert _fences(scoped, "powershell") == ["python -m pytest test_seam_all\\test_seam.py -q\n"]
    assert _fences(scoped, "bash") == ["./.venv/bin/python -m pytest test_seam_all/test_seam.py -q\n"]
    destinations = {
        child.attrGet("href") for token in MARKDOWN.parse(scoped) for child in (token.children or [])
        if child.type == "link_open"
    }
    assert {"../pytest.ini", "../.github/workflows/ci.yml"} <= destinations
    for destination in destinations:
        assert (REPO_ROOT / "docs" / destination).resolve().is_file()
    assert "not a report that those jobs ran" in scoped
    assert '<a id="run-the-full-suite"></a>' in testing, "Preserve the existing heading bookmark"
