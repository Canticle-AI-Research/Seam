from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tools.docs.verify_wiki import main, verify


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_recursive_collection_makes_every_active_page_reachable(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\n\n[Manuals](manuals/README.md)\n")
    _write(tmp_path, "docs/manuals/README.md", "# Manuals\n\n[Use](use.md)\n")
    _write(tmp_path, "docs/manuals/use.md", "# Use\n")

    assert verify(tmp_path) == []


def test_missing_navigation_target_fails_closed(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\n\n[Missing](missing.md)\n")

    errors = verify(tmp_path)

    assert any("link target is missing" in error for error in errors)


@pytest.mark.parametrize(
    ("home_link", "extra_page"),
    [
        ("[Missing section](#missing-section)", None),
        ("[Missing section](page.md#missing-section)", "# Page\n"),
    ],
    ids=("same-page", "cross-page"),
)
def test_local_link_fragments_must_name_existing_anchors(tmp_path, home_link, extra_page):
    _write(tmp_path, "docs/README.md", f"# Wiki\n\n{home_link}\n")
    if extra_page is not None:
        _write(tmp_path, "docs/page.md", extra_page)

    errors = verify(tmp_path)

    assert any("link fragment is missing" in error for error in errors)


def test_local_link_fragments_accept_heading_and_explicit_html_anchors(tmp_path):
    _write(
        tmp_path,
        "docs/README.md",
        "# Wiki\n\n[Home](#wiki)\n\n[Page](page.md#explicit-anchor)\n",
    )
    _write(tmp_path, "docs/page.md", '# Page\n\n<a id="explicit-anchor"></a>\n')

    assert verify(tmp_path) == []


def test_unindexed_active_page_is_rejected(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\n")
    _write(tmp_path, "docs/orphan.md", "# Orphan\n")

    errors = verify(tmp_path)

    assert any("docs/orphan.md" in error and "unreachable" in error for error in errors)


def test_code_fence_does_not_make_page_reachable(tmp_path):
    _write(
        tmp_path,
        "docs/README.md",
        "# Wiki\n\n```markdown\n[Not navigation](orphan.md)\n```\n",
    )
    _write(tmp_path, "docs/orphan.md", "# Orphan\n")

    errors = verify(tmp_path)

    assert any("docs/orphan.md" in error and "unreachable" in error for error in errors)


def test_other_code_forms_do_not_make_page_reachable(tmp_path):
    _write(
        tmp_path,
        "docs/README.md",
        """# Wiki

`[Inline code](orphan.md)`

    [Indented code](orphan.md)

````markdown
[Long fence](orphan.md)
```
````

\\[Escaped syntax](orphan.md)

> ```markdown
> [Blockquoted fence](orphan.md)
> ```
""",
    )
    _write(tmp_path, "docs/orphan.md", "# Orphan\n")

    errors = verify(tmp_path)

    assert any("docs/orphan.md" in error and "unreachable" in error for error in errors)


@pytest.mark.parametrize(
    "link",
    [
        "[Nested [label]](file:///tmp/outside.md)",
        r"[Escaped \] label](file:///tmp/outside.md)",
        "[Multiline\nlabel](file:///tmp/outside.md)",
        "[Angle destination](<file:///tmp/outside.md>)",
    ],
    ids=("nested-label", "escaped-label", "multiline-label", "angle-destination"),
)
def test_rendered_commonmark_link_shapes_cannot_bypass_validation(tmp_path, link):
    _write(tmp_path, "docs/README.md", f"# Wiki\n\n{link}\n")

    errors = verify(tmp_path)

    assert any("uses unsupported filesystem link" in error for error in errors)


def test_angle_destination_with_spaces_makes_page_reachable(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\n\n[Page](<page with spaces.md>)\n")
    _write(tmp_path, "docs/page with spaces.md", "# Page\n")

    assert verify(tmp_path) == []


def test_paragraph_indentation_does_not_hide_a_rendered_link(tmp_path):
    _write(
        tmp_path,
        "docs/README.md",
        "# Wiki\n\nParagraph text\n    [Outside](file:///tmp/outside.md)\n",
    )

    errors = verify(tmp_path)

    assert any("uses unsupported filesystem link" in error for error in errors)


@pytest.mark.parametrize(
    "markdown",
    [
        "> ```markdown\n> [Code](ignored.md)\n[Outside](file:///tmp/outside.md)\n",
        "- ```markdown\n  [Code](ignored.md)\n[Outside](file:///tmp/outside.md)\n",
    ],
    ids=("blockquote", "list-item"),
)
def test_unclosed_contained_fence_does_not_hide_following_link(tmp_path, markdown):
    _write(tmp_path, "docs/README.md", f"# Wiki\n\n{markdown}")

    errors = verify(tmp_path)

    assert any("uses unsupported filesystem link" in error for error in errors)
    assert not any("ignored.md" in error for error in errors)


def test_inline_raw_code_element_still_renders_markdown_links(tmp_path):
    _write(
        tmp_path,
        "docs/README.md",
        "# Wiki\n\n<code>[Outside](file:///tmp/outside.md)</code>\n",
    )

    errors = verify(tmp_path)

    assert any("uses unsupported filesystem link" in error for error in errors)


def test_unclosed_fence_does_not_make_page_reachable(tmp_path):
    _write(
        tmp_path,
        "docs/README.md",
        "# Wiki\n\n```markdown\n[Not navigation](orphan.md)\n",
    )
    _write(tmp_path, "docs/orphan.md", "# Orphan\n")

    errors = verify(tmp_path)

    assert any("docs/orphan.md" in error and "unreachable" in error for error in errors)


def test_reference_link_is_resolved_and_cannot_escape_repository(tmp_path):
    repo = tmp_path / "repo"
    _write(
        repo,
        "docs/README.md",
        "# Wiki\n\n[Outside][target]\n\n[target]: ../../outside.md\n",
    )
    _write(tmp_path, "outside.md", "# Outside\n")

    errors = verify(repo)

    assert any("escapes repository" in error for error in errors)


def test_archives_are_outside_active_coverage(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\n")
    _write(tmp_path, "docs/archive/old.md", "# Old\n")
    _write(tmp_path, "docs/status_archive/old-status.md", "# Old status\n")

    assert verify(tmp_path) == []


def test_dated_documents_must_live_in_a_declared_canonical_home(tmp_path):
    _write(
        tmp_path,
        "docs/README.md",
        "# Wiki\n\n[Misrouted report](2026-08-12-review.md)\n",
    )
    _write(tmp_path, "docs/2026-08-12-review.md", "# Review\n")

    errors = verify(tmp_path)

    assert any(
        "dated documentation must live in a canonical dated-document home" in error
        and "docs/2026-08-12-review.md" in error
        for error in errors
    )


def test_navigation_link_cannot_escape_repository(tmp_path):
    repo = tmp_path / "repo"
    _write(repo, "docs/README.md", "# Wiki\n\n[Outside](../../outside.md)\n")
    _write(tmp_path, "outside.md", "# Outside\n")

    errors = verify(repo)

    assert any("escapes repository" in error for error in errors)


def test_navigation_rejects_directory_targets(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\n\n[Folder](manuals/)\n")
    (tmp_path / "docs/manuals").mkdir()

    errors = verify(tmp_path)

    assert any("not a regular file" in error for error in errors)


def test_active_markdown_symlink_is_rejected(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\n\n[Real](real.md)\n[Alias](alias.md)\n")
    real = _write(tmp_path, "docs/real.md", "# Real\n")
    (tmp_path / "docs/alias.md").symlink_to(real.name)

    errors = verify(tmp_path)

    assert any("must not be a symlink" in error for error in errors)
    assert any("link traverses symlink" in error for error in errors)


def test_cyclic_markdown_symlink_is_reported_without_crashing(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\n\n[Loop](loop.md)\n")
    (tmp_path / "docs/loop.md").symlink_to("loop.md")

    errors = verify(tmp_path)

    assert any("docs/loop.md" in error and "must not be a symlink" in error for error in errors)
    assert any("link traverses symlink docs/loop.md" in error for error in errors)


def test_canonical_home_rejects_a_symlinked_docs_directory(tmp_path):
    repo = tmp_path / "repo"
    outside_docs = tmp_path / "outside-docs"
    _write(tmp_path, "outside-docs/README.md", "# Outside\n")
    repo.mkdir()
    (repo / "docs").symlink_to(outside_docs, target_is_directory=True)

    assert verify(repo) == ["canonical wiki home is missing or unsafe: docs/README.md"]


def test_navigation_rejects_file_uri_targets(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\n\n[Outside](file:///tmp/outside.md)\n")

    errors = verify(tmp_path)

    assert any("uses unsupported filesystem link" in error for error in errors)


@pytest.mark.parametrize(
    "link",
    [
        "[Script](javascript:alert(1))",
        "[Script](vbscript:msgbox(1))",
        '<a href="data:text/html,unsafe">Inline data</a>',
    ],
    ids=("javascript", "vbscript", "raw-html-data"),
)
def test_navigation_rejects_dangerous_uri_schemes(tmp_path, link):
    _write(tmp_path, "docs/README.md", f"# Wiki\n\n{link}\n")

    errors = verify(tmp_path)

    assert any("uses dangerous URI scheme" in error for error in errors)


def test_malformed_url_is_reported_without_crashing(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\n\n[Bad](http://[invalid)\n")

    errors = verify(tmp_path)

    assert any("uses malformed link" in error for error in errors)


def test_encoded_null_local_link_is_reported_without_crashing(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\n\n[Bad](bad%00.md)\n")

    errors = verify(tmp_path)

    assert any("uses malformed local link" in error for error in errors)


def test_raw_html_anchor_cannot_bypass_file_uri_rejection(tmp_path):
    _write(
        tmp_path,
        "docs/README.md",
        '# Wiki\n\n<a href="file:///tmp/outside.md">Outside</a>\n',
    )

    errors = verify(tmp_path)

    assert any("uses unsupported filesystem link" in error for error in errors)


@pytest.mark.parametrize("target", ["C:/Windows/win.ini", r"C:\Windows\win.ini"])
def test_windows_absolute_links_are_rejected(tmp_path, target):
    _write(tmp_path, "docs/README.md", f"# Wiki\n\n[Outside]({target})\n")

    errors = verify(tmp_path)

    assert any("uses unsupported absolute local link" in error for error in errors)


def test_every_reachable_page_has_its_local_links_validated(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\n\n[Router](REPORTS.md)\n")
    _write(tmp_path, "docs/REPORTS.md", "# Reports\n\n[Missing](missing.md)\n")

    errors = verify(tmp_path)

    assert any("docs/REPORTS.md link target is missing" in error for error in errors)


def test_audit_registry_history_references_must_exist(tmp_path):
    report = "2026-08-12-review.md"
    _write(tmp_path, "docs/README.md", "# Wiki\n\n[Audits](audits/INDEX.md)\n")
    index = _write(
        tmp_path,
        "docs/audits/INDEX.md",
        f"""---
schema: seam-audit-registry/v1
latest: 2026-08-12-review
policy_start: 2026-08-01
---

# Audits

| Date | Report | Summary | History |
|---|---|---|---|
| 2026-08-12 | [Review]({report}) | Review | HISTORY#999999 |
""",
    )
    _write(
        tmp_path,
        f"docs/audits/{report}",
        "# Review\n\n## Evidence manifest\n\nRaw artifacts: none\n",
    )
    _write(tmp_path, "HISTORY.md", "id: 001\n")

    errors = verify(tmp_path)

    assert any("references missing HISTORY#999999" in error for error in errors)

    index.write_text(
        index.read_text(encoding="utf-8").replace("HISTORY#999999", "HISTORY#1"),
        encoding="utf-8",
    )
    assert verify(tmp_path) == []


def test_staged_mode_cannot_be_masked_by_a_fixed_working_copy(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    source_root = Path(__file__).resolve().parents[2]
    for relative in (
        "tools/docs/__init__.py",
        "tools/docs/verify_wiki.py",
    ):
        source = source_root / relative
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    _write(repo, "docs/README.md", "# Wiki\n\n[Missing](missing.md)\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "docs", "tools"], cwd=repo, check=True)

    _write(repo, "docs/README.md", "# Wiki\n")
    assert verify(repo) == []

    assert main(["--root", str(repo), "--staged"]) == 1
    assert "link target is missing" in capsys.readouterr().out


def test_cli_returns_nonzero_for_an_invalid_wiki(tmp_path, capsys):
    _write(tmp_path, "docs/README.md", "# Wiki\n")
    _write(tmp_path, "docs/orphan.md", "# Orphan\n")

    assert main(["--root", str(tmp_path)]) == 1
    assert "SEAM wiki verification FAILED" in capsys.readouterr().out
