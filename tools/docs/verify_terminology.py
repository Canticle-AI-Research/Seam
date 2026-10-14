"""Verify canonical SEAM terminology in active authority documents."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT_AUTHORITY_FILES = (
    Path("README.md"),
    Path("REPO_LEDGER.md"),
    Path("SEAM_SPEC_V0.1.md"),
)
CORE_EXPANSION_FILES = (
    Path("README.md"),
    Path("REPO_LEDGER.md"),
    Path("docs/MIRL_V1.md"),
    Path("docs/TERMINOLOGY.md"),
)
EXCLUDED_DOC_PREFIXES = (
    Path("docs/archive"),
    Path("docs/audits"),
    Path("docs/handoffs"),
    Path("docs/prompts"),
    Path("docs/roadmap"),
    Path("docs/status_archive"),
    Path("docs/superpowers/plans"),
)
CANONICAL_MIRL_EXPANSION = "Machine Intermediate Representation Language"
CANONICAL_SEAM_EXPANSION = "Surface Encoded Agent Memory"

# Capture a bounded candidate phrase, then distinguish the four-word name from
# ordinary following prose. Additional title words remain a competing name.
_MIRL_AFTER = re.compile(
    r"\bMIRL\s+(?:means|stands\s+for|expands\s+to|is\s+short\s+for|=)\s+"
    r"(?P<expansion>[A-Z][A-Za-z-]*(?:\s+[A-Z][A-Za-z-]*){0,5})",
    re.IGNORECASE,
)
_MIRL_BEFORE = re.compile(
    r"(?P<expansion>[A-Z][A-Za-z-]*(?:\s+[A-Z][A-Za-z-]*){2,5})\s+"
    r"\(MIRL\)",
)
_SEAM_AFTER = re.compile(
    r"\bSEAM\s+(?:means|stands\s+for|expands\s+to|is\s+short\s+for|=)\s+"
    r"(?P<expansion>[A-Z][A-Za-z-]*(?:\s+[A-Z][A-Za-z-]*){0,5})",
    re.IGNORECASE,
)
_SEAM_BEFORE = re.compile(
    r"(?P<expansion>[A-Z][A-Za-z-]*(?:\s+[A-Z][A-Za-z-]*){2,5})\s+"
    r"\(SEAM\)",
)
_PRODUCT_TOKEN = re.compile(
    r"\b(?P<product>SEAM Suite|SEAM Client|SEAM SDK|Python HTTP client)\s*"
    r"\(\s*`(?P<token>seam-(?:suite|client|sdk))`\s*\)"
)
_ALLOWED_PRODUCT_TOKENS = {
    "SEAM Suite": "seam-suite",
    "SEAM SDK": "seam-sdk",
    "Python HTTP client": "seam-client",
}
_DISTRIBUTED_RUNTIME_COLLISIONS = (
    re.compile(r"\bSEAM (?:Suite|Client)\s+(?:is|means|=)\s+the\s+Distributed Runtime\b", re.IGNORECASE),
    re.compile(r"\bDistributed Runtime\s+(?:is|means|=)\s+(?:the\s+)?SEAM (?:Suite|Client)\b", re.IGNORECASE),
)
_GLOSSARY_MARKERS = (
    "Canticle Research",
    "Surface Encoded Agent Memory",
    CANONICAL_MIRL_EXPANSION,
    "`RAW`",
    "`IR`",
    "`PACK`",
    "`LENS`",
    "`SEAM-RC/1`",
    "`SEAM-LX/1`",
    "`SEAM-HS/1`",
    "Canonical and derived data",
    "Knowledge graph",
    "Reasoning graph",
    "SEAM Suite",
    "SEAM Client",
    "`seam-client`",
    "`seam-sdk`",
    "Distributed Runtime",
)


def _is_excluded(relative: Path) -> bool:
    return any(relative == prefix or prefix in relative.parents for prefix in EXCLUDED_DOC_PREFIXES)


def _has_symlink(path: Path, root: Path) -> bool:
    return any(part.is_symlink() for part in (path, *path.parents) if part != root and root in part.parents)


def authority_paths(root: Path) -> tuple[Path, ...]:
    """Return deterministic active authority paths covered by the contract."""

    paths = [root / relative for relative in ROOT_AUTHORITY_FILES
             if not _has_symlink(root / relative, root) and (root / relative).is_file()]
    docs = root / "docs"
    if not _has_symlink(docs, root) and docs.is_dir():
        paths.extend(
            path
            for path in docs.rglob("*.md")
            if path.is_file()
            and not _has_symlink(path, root)
            and not _is_excluded(path.relative_to(root))
        )
    return tuple(sorted(set(paths)))


def _display(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _normalized_expansion(value: str) -> str:
    return " ".join(value.replace("*", "").split())


def _definition_expansion(value: str) -> str:
    words = _normalized_expansion(value).split()
    end = min(4, len(words))
    while end < len(words) and words[end][0].isupper():
        end += 1
    return " ".join(words[:end])


def _canonical_before(expansion: str, canonical: str) -> bool:
    # Only a grammatical article may precede the name. An arbitrary title
    # prefix defines a different expansion even when its suffix is canonical.
    value = expansion.casefold()
    return value in {canonical, "the " + canonical, "a " + canonical, "an " + canonical}


def _verify_text(path: Path, root: Path, text: str) -> list[str]:
    relative = _display(path, root)
    errors: list[str] = []
    prose = text.replace("**", "").replace("__", "").replace("`", "")

    for pattern in (_MIRL_AFTER, _MIRL_BEFORE):
        for match in pattern.finditer(prose):
            expansion = _normalized_expansion(match.group("expansion"))
            if pattern is _MIRL_AFTER:
                expansion = _definition_expansion(expansion)
            canonical = CANONICAL_MIRL_EXPANSION.casefold()
            matches = expansion.casefold() == canonical
            if pattern is _MIRL_BEFORE:
                matches = _canonical_before(expansion, canonical)
            if not matches:
                errors.append(
                    f"{relative}:{_line_number(prose, match.start())} has competing MIRL expansion: {expansion}"
                )

    for pattern in (_SEAM_AFTER, _SEAM_BEFORE):
        for match in pattern.finditer(prose):
            expansion = _normalized_expansion(match.group("expansion"))
            if pattern is _SEAM_AFTER:
                expansion = _definition_expansion(expansion)
            canonical = CANONICAL_SEAM_EXPANSION.casefold()
            matches = expansion.casefold() == canonical
            if pattern is _SEAM_BEFORE:
                matches = _canonical_before(expansion, canonical)
            if not matches:
                errors.append(
                    f"{relative}:{_line_number(prose, match.start())} has competing SEAM expansion: {expansion}"
                )

    for match in _PRODUCT_TOKEN.finditer(text):
        product = match.group("product")
        token = match.group("token")
        expected = _ALLOWED_PRODUCT_TOKENS.get(product)
        if expected != token:
            expectation = "no package-token alias" if expected is None else f"`{expected}`"
            errors.append(
                f"{relative}:{_line_number(text, match.start())} has product-name collision: "
                f"{product} cannot name `{token}`; expected {expectation}"
            )

    for pattern in _DISTRIBUTED_RUNTIME_COLLISIONS:
        for match in pattern.finditer(text):
            errors.append(
                f"{relative}:{_line_number(text, match.start())} has product-name collision: "
                "Distributed Runtime is a license-defined subset, not a product-name synonym"
            )

    return errors


def verify(root: Path) -> list[str]:
    """Return terminology contract violations under ``root``."""

    root = root.resolve()
    errors: list[str] = []
    for relative in {*ROOT_AUTHORITY_FILES, *CORE_EXPANSION_FILES, Path("docs")}:
        if _has_symlink(root / relative, root):
            errors.append(f"unsafe terminology authority must not use symlinks: {relative.as_posix()}")
    if errors:
        return sorted(errors)
    for path in authority_paths(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read {_display(path, root)}: {type(exc).__name__}")
            continue
        errors.extend(_verify_text(path, root, text))

    glossary = root / "docs/TERMINOLOGY.md"
    seam_authorities = (root / "SEAM_SPEC_V0.1.md", root / "REPO_LEDGER.md")
    is_seam_checkout = any(path.is_file() for path in seam_authorities)
    if is_seam_checkout:
        for relative in CORE_EXPANSION_FILES:
            path = root / relative
            if not path.is_file():
                errors.append(f"required core terminology document is missing: {relative.as_posix()}")
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                errors.append(f"cannot read {relative.as_posix()}: {type(exc).__name__}")
                continue
            if CANONICAL_MIRL_EXPANSION not in text:
                errors.append(
                    f"{relative.as_posix()} is missing exact MIRL expansion: "
                    f"{CANONICAL_MIRL_EXPANSION}"
                )

    if not glossary.is_file() and is_seam_checkout:
        errors.append("required canonical glossary is missing: docs/TERMINOLOGY.md")
    elif glossary.is_file():
        try:
            text = glossary.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read docs/TERMINOLOGY.md: {type(exc).__name__}")
        else:
            for marker in _GLOSSARY_MARKERS:
                if marker not in text:
                    errors.append(f"docs/TERMINOLOGY.md is missing canonical marker: {marker}")

    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: current directory).",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    errors = verify(root)
    if errors:
        print("SEAM terminology verification FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"SEAM terminology OK: {len(authority_paths(root))} active authority pages checked")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
