"""Verify SEAM wiki navigation, local-link safety, and report registration."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import unicodedata
from collections import Counter, deque
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

HOME = Path("docs/README.md")
DOCS_DIR = Path("docs")
AUDITS_DIR = Path("docs/audits")
AUDIT_INDEX = AUDITS_DIR / "INDEX.md"
EXCLUDED_DIRS = (Path("docs/archive"), Path("docs/status_archive"))
DATED_DOC_HOMES = (
    Path("docs/audits"),
    Path("docs/handoffs"),
    Path("docs/status_archive"),
    Path("docs/superpowers/plans"),
)

_MARKDOWN = MarkdownIt("commonmark", {"html": True})


def _accept_every_link(url: str) -> bool:
    """Never let the parser decide a destination is too dangerous to report.

    markdown-it ships a ``validateLink`` that suppresses ``file:``,
    ``javascript:``, ``vbscript:``, and most ``data:`` destinations by emitting
    no ``link_open`` token at all, leaving them invisible downstream. That is
    the right default for rendering untrusted markdown and exactly wrong for a
    gate whose purpose is to *report* such destinations: a ``file:`` link was
    silently accepted rather than rejected, because nothing ever saw it.
    Whether a destination is allowed is ``_resolve_local_target``'s decision,
    not the parser's.
    """

    return True


def _keep_link_verbatim(url: str) -> str:
    """Hand the destination downstream exactly as authored.

    markdown-it's ``normalizeLink`` percent-encodes before anything else sees
    the value, which silently repairs malformed input this gate must reject:
    ``http://[invalid`` arrived as ``http://%5Binvalid``, which ``urlsplit``
    parses without complaint. Ordinary relative targets are unaffected, and
    ``_resolve_local_target`` already ``unquote``s whatever it is handed, so
    percent-encoded spellings still resolve.
    """

    return url


_MARKDOWN.validateLink = _accept_every_link
_MARKDOWN.normalizeLink = _keep_link_verbatim

_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_REPORT_NAME = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})-(?P<slug>[a-z0-9][a-z0-9-]*)\.md$"
)
_REPORT_LINK = re.compile(r"^\[[^\]]+\]\(([^\s)#?]+\.md)\)$")
_HISTORY_REF = re.compile(r"\bHISTORY#\d+\b")
_SHA256 = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")
_CODE_SPAN = re.compile(r"`([^`\r\n]+)`")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class _AuditRow:
    report_date: date
    filename: str
    history: str


def _relative(path: Path, root: Path) -> Path:
    return path.relative_to(root)


def _is_excluded(path: Path, root: Path) -> bool:
    relative = _relative(path, root)
    return any(relative == prefix or prefix in relative.parents for prefix in EXCLUDED_DIRS)


def _active_docs(root: Path) -> set[Path]:
    docs = root / DOCS_DIR
    if not docs.is_dir():
        return set()
    return {
        path
        for path in docs.rglob("*.md")
        if not _is_excluded(path, root) and not path.is_symlink()
    }


class _AnchorParser(HTMLParser):
    """Collect anchor destinations from rendered raw-HTML tokens only."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.targets: list[str] = []
        self.identifiers: set[str] = set()
        self._raw_text_element: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        folded = tag.casefold()
        attributes = {name.casefold(): value for name, value in attrs if value is not None}
        if identifier := attributes.get("id"):
            self.identifiers.add(identifier)
        if name := attributes.get("name"):
            self.identifiers.add(name)
        if self._raw_text_element is not None:
            return
        if folded in {"script", "style", "textarea"}:
            self._raw_text_element = folded
            return
        if folded != "a":
            return
        if target := attributes.get("href"):
            self.targets.append(target)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == self._raw_text_element:
            self._raw_text_element = None

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        raw_text_element = self._raw_text_element
        self.handle_starttag(tag, attrs)
        self._raw_text_element = raw_text_element


def _walk_tokens(tokens: list[Token]) -> list[Token]:
    walked: list[Token] = []
    for token in tokens:
        walked.append(token)
        if token.children:
            walked.extend(_walk_tokens(token.children))
    return walked


def _link_targets(text: str) -> list[str]:
    """Return destinations that CommonMark actually renders as links."""

    targets: list[str] = []
    for token in _walk_tokens(_MARKDOWN.parse(text)):
        if token.type == "link_open":
            target = token.attrGet("href")
            if target is not None:
                targets.append(target)
            continue
        if token.type not in {"html_block", "html_inline"}:
            continue
        anchors = _AnchorParser()
        anchors.feed(token.content)
        anchors.close()
        targets.extend(anchors.targets)
    return targets


def _heading_text(token: Token) -> str:
    text: list[str] = []
    for child in token.children or []:
        if child.type in {"text", "code_inline", "image"}:
            text.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            text.append(" ")
    return "".join(text)


def _github_slug_base(text: str) -> str:
    retained: list[str] = []
    for character in text.strip().casefold():
        category = unicodedata.category(character)
        if (
            character in {"-", "_"}
            or character.isspace()
            or category[0] in {"L", "M", "N"}
            or category == "So"
        ):
            retained.append(character)
    return "-".join("".join(retained).split())


def _document_anchors(text: str) -> set[str]:
    """Return GitHub-style heading slugs plus explicit raw-HTML anchors."""

    anchors: set[str] = set()
    used_heading_slugs: set[str] = set()
    tokens = _MARKDOWN.parse(text)
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and index + 1 < len(tokens):
            inline = tokens[index + 1]
            if inline.type == "inline":
                base = _github_slug_base(_heading_text(inline))
                if base:
                    slug = base
                    suffix = 0
                    while slug in used_heading_slugs:
                        suffix += 1
                        slug = f"{base}-{suffix}"
                    used_heading_slugs.add(slug)
                    anchors.add(slug)
        if token.type not in {"html_block", "html_inline"}:
            continue
        parser = _AnchorParser()
        parser.feed(token.content)
        parser.close()
        anchors.update(parser.identifiers)
    return anchors


def _lexical_path(path: Path) -> Path:
    return Path(os.path.normpath(path))


def _symlink_component(path: Path, root: Path) -> Path | None:
    """Return the first symlink in the lexical path from root to target."""

    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return current
    return None


def _has_noncanonical_parent_ascent(decoded_path: str) -> bool:
    """Reject ``name/..`` while retaining useful leading ``../`` links."""

    saw_normal_component = False
    for part in decoded_path.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if saw_normal_component:
                return True
            continue
        saw_normal_component = True
    return False


def _resolve_local_target(source: Path, target: str, root: Path) -> tuple[Path | None, str | None]:
    if not target or target.startswith("#"):
        return None, None

    decoded_target = unquote(target)
    if "\x00" in decoded_target:
        return None, f"{_relative(source, root)} uses malformed local link: {target}"
    if _WINDOWS_ABSOLUTE.match(decoded_target) or decoded_target.startswith("\\\\"):
        return None, f"{_relative(source, root)} uses unsupported absolute local link: {target}"

    try:
        parsed = urlsplit(target)
    except ValueError:
        return None, f"{_relative(source, root)} uses malformed link: {target}"
    if parsed.scheme.lower() == "file":
        return None, f"{_relative(source, root)} uses unsupported filesystem link: {target}"
    if parsed.scheme or parsed.netloc or target.startswith("//"):
        return None, None
    decoded = unquote(parsed.path)
    if not decoded:
        return None, None
    if decoded.startswith("/"):
        return None, f"{_relative(source, root)} uses unsupported absolute local link: {target}"
    if _has_noncanonical_parent_ascent(decoded):
        return None, f"{_relative(source, root)} uses unsafe non-canonical local link: {target}"

    lexical = _lexical_path(source.parent / decoded)
    try:
        symlink = _symlink_component(lexical, root)
    except (OSError, ValueError):
        return None, f"{_relative(source, root)} cannot inspect local link: {target}"
    if symlink is not None:
        return None, (
            f"{_relative(source, root)} link traverses symlink "
            f"{_relative(symlink, root)}: {target}"
        )

    try:
        resolved_root = root.resolve()
        resolved = lexical.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None, f"{_relative(source, root)} cannot inspect local link: {target}"
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None, f"{_relative(source, root)} link escapes repository: {target}"

    try:
        if not resolved.exists():
            return None, f"{_relative(source, root)} link target is missing: {target}"
        if not resolved.is_file():
            return None, f"{_relative(source, root)} link target is not a regular file: {target}"
    except (OSError, ValueError):
        return None, f"{_relative(source, root)} cannot inspect local link: {target}"
    return resolved, None


def _frontmatter(text: str) -> tuple[dict[str, str], str | None]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "opening frontmatter delimiter is missing"
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return metadata, None
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or key.strip() in metadata:
            return {}, "frontmatter is malformed or has duplicate keys"
        metadata[key.strip()] = value.strip().strip("\"'")
    return {}, "closing frontmatter delimiter is missing"


def _parse_date(value: str) -> date | None:
    if not _ISO_DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _audit_rows(index_text: str) -> tuple[list[_AuditRow], list[str]]:
    rows: list[_AuditRow] = []
    errors: list[str] = []
    for line in index_text.splitlines():
        if not re.match(r"^\|\s*\d{4}-\d{2}-\d{2}\s*\|", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            errors.append(f"{AUDIT_INDEX} has malformed registry row: {line.strip()}")
            continue
        report_date = _parse_date(cells[0])
        link = _REPORT_LINK.fullmatch(cells[1])
        if report_date is None or link is None:
            errors.append(f"{AUDIT_INDEX} has malformed registry row: {line.strip()}")
            continue
        filename = unquote(link.group(1))
        if Path(filename).name != filename or _REPORT_NAME.fullmatch(filename) is None:
            errors.append(f"{AUDIT_INDEX} uses non-canonical report link: {link.group(1)}")
            continue
        rows.append(_AuditRow(report_date, filename, cells[3]))
    return rows, errors


def _manifest_sections(text: str) -> list[list[str]]:
    lines = text.splitlines()
    tokens = _MARKDOWN.parse(text)
    sections: list[list[str]] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.tag != "h2" or token.map is None:
            continue
        if index + 1 >= len(tokens) or tokens[index + 1].type != "inline":
            continue
        if tokens[index + 1].content.strip().casefold() != "evidence manifest":
            continue
        start = token.map[1]
        end = len(lines)
        for following in tokens[index + 1 :]:
            if (
                following.type == "heading_open"
                and following.tag in {"h1", "h2"}
                and following.map is not None
                and following.map[0] >= start
            ):
                end = following.map[0]
                break
        sections.append(lines[start:end])
    return sections


def _looks_like_artifact_path(value: str) -> bool:
    if _SHA256.fullmatch(value.strip()):
        return False
    return "/" in value or "\\" in value or "." in Path(value).name


def _verify_evidence_manifest(report: Path, text: str, root: Path) -> list[str]:
    relative = _relative(report, root)
    sections = _manifest_sections(text)
    if len(sections) != 1:
        return [f"{relative} must contain exactly one ## Evidence manifest section"]

    lines = sections[0]
    none_lines = [
        line
        for line in lines
        if re.fullmatch(r"[ \t]*Raw artifacts:[ \t]*none[ \t]*", line)
    ]
    pair_count = 0
    malformed_declarations: list[str] = []
    for line in lines:
        hashes = _SHA256.findall(line)
        code_values = [value.strip() for value in _CODE_SPAN.findall(line)]
        paths = [value for value in code_values if _looks_like_artifact_path(value)]
        if hashes:
            if len(hashes) != 1 or len(paths) != 1:
                malformed_declarations.append(line.strip())
            else:
                pair_count += 1
        elif paths:
            malformed_declarations.append(line.strip())

    if malformed_declarations:
        return [f"{relative} has an artifact path without exactly one 64-hex SHA-256"]
    if none_lines:
        if len(none_lines) != 1 or pair_count:
            return [f"{relative} evidence manifest mixes or duplicates raw-artifact declarations"]
        return []
    if pair_count == 0:
        return [
            f"{relative} evidence manifest must declare `Raw artifacts: none` "
            "or artifact path and 64-hex SHA-256 pairs"
        ]
    return []


def _verify_audit_registry(root: Path) -> list[str]:
    audit_dir = root / AUDITS_DIR
    index = root / AUDIT_INDEX
    if not audit_dir.exists() and not index.exists():
        return []
    if not audit_dir.is_dir() or not index.is_file() or index.is_symlink():
        return [f"canonical audit registry is missing or unsafe: {AUDIT_INDEX}"]

    try:
        index_text = index.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"cannot read {AUDIT_INDEX}: {type(exc).__name__}"]

    errors: list[str] = []
    metadata, frontmatter_error = _frontmatter(index_text)
    if frontmatter_error is not None:
        errors.append(f"{AUDIT_INDEX} {frontmatter_error}")
    if metadata.get("schema") != "seam-audit-registry/v1":
        errors.append(f"{AUDIT_INDEX} must declare schema seam-audit-registry/v1")
    policy_start = _parse_date(metadata.get("policy_start", ""))
    if policy_start is None:
        errors.append(f"{AUDIT_INDEX} must declare a valid policy_start ISO date")

    rows, row_errors = _audit_rows(index_text)
    errors.extend(row_errors)
    report_files = sorted(
        path
        for path in audit_dir.iterdir()
        if path.is_file() and not path.is_symlink() and path.suffix.casefold() == ".md" and path != index
    )
    filenames: list[str] = []
    dated_reports: dict[str, date] = {}
    for report in report_files:
        match = _REPORT_NAME.fullmatch(report.name)
        if match is None:
            errors.append(f"audit report has non-canonical filename: {_relative(report, root)}")
            continue
        report_date = _parse_date(match.group("date"))
        if report_date is None:
            errors.append(f"audit report has invalid ISO date: {_relative(report, root)}")
            continue
        filenames.append(report.name)
        dated_reports[report.name] = report_date

    row_counts = Counter(row.filename for row in rows)
    for filename in filenames:
        if row_counts[filename] != 1:
            errors.append(f"{AUDITS_DIR / filename} must be registered exactly once in {AUDIT_INDEX}")
    for filename, count in sorted(row_counts.items()):
        if filename not in dated_reports:
            errors.append(f"{AUDIT_INDEX} references a missing report: {AUDITS_DIR / filename}")
        if count > 1:
            errors.append(f"{AUDIT_INDEX} registers report more than once: {AUDITS_DIR / filename}")

    if [row.report_date for row in rows] != sorted(
        (row.report_date for row in rows), reverse=True
    ):
        errors.append(f"{AUDIT_INDEX} report rows must be newest-first")
    for row in rows:
        filename_date = dated_reports.get(row.filename)
        if filename_date is not None and row.report_date != filename_date:
            errors.append(f"{AUDIT_INDEX} row date does not match report filename: {row.filename}")

    latest = metadata.get("latest", "")
    if not rows:
        errors.append(f"{AUDIT_INDEX} must register at least one report")
    else:
        if latest != Path(rows[0].filename).stem:
            errors.append(f"{AUDIT_INDEX} latest must identify the first newest report row")
        if f"{latest}.md" not in dated_reports:
            errors.append(f"{AUDIT_INDEX} latest points to a missing report: {latest}")

    if policy_start is not None:
        rows_by_filename = {row.filename: row for row in rows if row_counts[row.filename] == 1}
        for filename, report_date in sorted(dated_reports.items()):
            if report_date < policy_start:
                continue
            row = rows_by_filename.get(filename)
            if row is not None and _HISTORY_REF.search(row.history) is None:
                errors.append(
                    f"{AUDIT_INDEX} policy-era report must cite a HISTORY entry: {filename}"
                )
            try:
                report_text = (audit_dir / filename).read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                errors.append(f"cannot read {AUDITS_DIR / filename}: {type(exc).__name__}")
                continue
            errors.extend(_verify_evidence_manifest(audit_dir / filename, report_text, root))
    return errors


def verify(repo_root: Path) -> list[str]:
    """Return deterministic wiki errors for ``repo_root``."""

    root = repo_root.resolve()
    home = root / HOME
    errors: list[str] = []
    if _symlink_component(home, root) is not None or not home.is_file():
        return [f"canonical wiki home is missing or unsafe: {HOME}"]

    active = _active_docs(root)
    symlink_docs = sorted(
        path
        for path in (root / DOCS_DIR).rglob("*.md")
        if not _is_excluded(path, root) and path.is_symlink()
    )
    errors.extend(
        f"active documentation page must not be a symlink: {_relative(path, root)}"
        for path in symlink_docs
    )

    reachable: set[Path] = set()
    queue: deque[Path] = deque([home])
    while queue:
        source = queue.popleft()
        if source in reachable:
            continue
        reachable.add(source)
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read {_relative(source, root)}: {type(exc).__name__}")
            continue

        for target in _link_targets(text):
            resolved, problem = _resolve_local_target(source, target, root)
            if problem is not None:
                errors.append(problem)
                continue
            if resolved is None or resolved.suffix.casefold() != ".md":
                continue
            try:
                resolved.relative_to(root / DOCS_DIR)
            except ValueError:
                continue
            if not _is_excluded(resolved, root) and resolved not in reachable:
                queue.append(resolved)

    missing = sorted(active - reachable)
    errors.extend(
        f"active documentation page is unreachable from {HOME}: {_relative(path, root)}"
        for path in missing
    )
    errors.extend(_verify_audit_registry(root))
    return sorted(set(errors))


def _verify_staged(repo_root: Path) -> int:
    """Export the Git index and run the staged verifier against staged content."""

    root = repo_root.resolve()
    with TemporaryDirectory(prefix="seam-wiki-index-") as temporary:
        staged_root = Path(temporary)
        try:
            export = subprocess.run(
                ["git", "checkout-index", "--all", f"--prefix={staged_root}{os.sep}"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            print("SEAM staged wiki verification FAILED: cannot execute Git")
            return 1
        if export.returncode != 0:
            print("SEAM staged wiki verification FAILED: cannot export Git index")
            return 1

        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        staged = subprocess.run(
            [sys.executable, "-m", "tools.docs.verify_wiki", "--root", str(staged_root)],
            cwd=staged_root,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        if staged.stdout:
            print(staged.stdout, end="")
        if staged.stderr:
            print(staged.stderr, end="", file=sys.stderr)
        return staged.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: current directory).",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Verify the exact Git index using the verifier staged in that index.",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.staged:
        return _verify_staged(root)
    errors = verify(root)
    if errors:
        print("SEAM wiki verification FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1
    active = _active_docs(root)
    print(f"SEAM wiki OK: {len(active)} active documentation pages reachable from {HOME}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
