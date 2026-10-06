"""Update/check managed documentation references; never run SEAM commands.

The parser and canonical link definitions supply data, not product qualification.
Hand-written prose is preserved and affected pages enter an explicit review queue.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import html
import itertools
import json
import math
import os
import re
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qsl, quote, unquote, urlsplit

from tools.docs import verify_wiki
from tools.security.secret_scan import scan_bytes

CONFIG = "tools/docs/reference_config.json"
CATALOG = "docs/reference/command_catalog.json"
STATE = "docs/reference/reference_state.json"
START = "<!-- seam-docs:links:start -->"
END = "<!-- seam-docs:links:end -->"
GENERATED = "<!-- seam-docs:generated-command-reference/v1 -->"
LINK_ID = re.compile(r"\[seam:([a-z0-9-]+)\]", re.IGNORECASE)
CLI_MENTION = re.compile(r"\bseam(?:[ \t]+|\[)")


class ReferenceError(ValueError):
    """Missing/unsafe metadata must stop generation before any writes."""


@dataclass
class Result:
    errors: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    unmanaged: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.pending


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _sha(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReferenceError(f"duplicate metadata key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    if not isinstance(value, dict):
        raise ReferenceError(f"metadata must be an object: {path.name}")
    return value


def _value(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, (tuple, list)):
        return [_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    raise ReferenceError(f"unsupported CLI metadata value type: {type(value).__name__}")


def describe_parser(parser: argparse.ArgumentParser) -> list[dict]:
    """Reuse palette traversal helpers, retain every parser level and argument.

    Inherited options retain their defining scope: root/parent options belong
    before the relevant subcommand, rather than being falsely advertised as
    leaf options. Alias paths include parent and leaf aliases together.
    """
    from seam_runtime.tui.commands import _subparser_action, _subparser_help

    rows = []

    def walk(node, path, spellings, inherited, summary):
        action = _subparser_action(node)
        if action is not None and not isinstance(action, argparse._SubParsersAction):
            raise ReferenceError("unsupported parser choices shape; cannot silently omit commands")
        own = []
        for arg in node._actions:
            if isinstance(arg, argparse._SubParsersAction):
                continue
            item = {
                "scope": path, "dest": arg.dest, "flags": list(arg.option_strings),
                "action": type(arg).__name__, "nargs": _value(arg.nargs),
                "required": bool(arg.required), "default": _value(arg.default),
                "const": _value(arg.const), "metavar": _value(arg.metavar),
                "type": getattr(arg.type, "__qualname__", None),
                "choices": None if arg.choices is None else [_value(c) for c in arg.choices],
                "help": arg.help,
            }
            if arg.default == argparse.SUPPRESS:
                item["default_kind"] = "suppressed"
            own.append(item)
        groups = [{"required": bool(g.required), "arguments": [a.dest for a in g._group_actions]}
                  for g in node._mutually_exclusive_groups]
        rows.append({"path": path, "aliases": sorted(s for s in spellings if s != path),
                     "summary": summary or node.description or "", "arguments": own,
                     "inherited_arguments": inherited, "exclusive_groups": groups,
                     "subcommands_required": bool(action.required) if action else False,
                     "leaf": action is None})
        if action is None:
            return
        help_map = _subparser_help(action)
        children = {}
        for name, child in action.choices.items():
            children.setdefault(id(child), (child, []))[1].append(name)
        for child, names in children.values():
            canonical = names[0]
            variants = [f"{parent} {name}" for parent, name in itertools.product(spellings, names)]
            walk(child, f"{path} {canonical}", variants, inherited + own, help_map.get(canonical, ""))

    walk(parser, "seam", ["seam"], [], parser.description)
    return sorted(rows, key=lambda row: row["path"])


def build_catalog(root: Path) -> dict:
    """Strict factory import; unlike the palette, errors never become [] ."""
    tree = ast.parse(_safe(root, "seam_runtime/cli.py").read_text(encoding="utf-8"))
    factory = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_parser"), None)
    db_defaults = [keyword.value for node in ast.walk(factory) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"
                   and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "--db"
                   for keyword in node.keywords if keyword.arg == "default"] if factory else []
    resolver = [value for value in db_defaults if isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name) and value.func.id == "default_runtime_db_path"
                and not value.args and not value.keywords]
    if len(resolver) != 1:
        raise ReferenceError("database default resolver changed; review its redaction contract before generation")
    from seam_runtime import cli

    if Path(cli.__file__).resolve() != (root / "seam_runtime/cli.py").resolve():
        raise ReferenceError("CLI was imported from another checkout; metadata is not source-bound")
    # Do not disclose a developer's HOME/environment-specific install path.
    # This documents the actual default resolver expression, not a guessed path.
    with patch.object(cli, "default_runtime_db_path", return_value="default_runtime_db_path()"):
        commands = describe_parser(cli.build_parser())
    for row in commands:
        for arg in row["arguments"] + row["inherited_arguments"]:
            if arg["dest"] == "db" and arg["default"] == "default_runtime_db_path()":
                arg["default_kind"] = "source_expression"
    paths = ["seam_runtime/cli.py", "seam_runtime/tui/commands.py", "seam_runtime/installer.py",
             "seam_runtime/lossless.py", "seam_runtime/holographic.py", "seam_runtime/benchmarks.py",
             "seam_runtime/context_views.py", "seam_runtime/retrieval.py", "pyproject.toml"]
    sources = {}
    for name in paths:
        raw = _safe(root, name).read_bytes()
        sources[name] = {"sha256": hashlib.sha256(raw).hexdigest(),
                         "git_blob_sha1": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}
    return {"schema": "seam-command-reference/1", "sources": sources,
            "source_revision_kind": "content-addressed Git blob plus SHA-256; no moving HEAD/timestamp",
            "commands": commands}


def _historical(name: str) -> bool:
    p = Path(name)
    return (any(part in {"archive", "status_archive", "archive_entries", ".seam", ".git", ".venv", ".opencode"}
                for part in p.parts)
            or p.name in {"HISTORY.md", "HISTORY_INDEX.md"}
            or bool(re.match(r"^\d{4}-\d{2}-\d{2}-", p.name)))


def _safe(root: Path, name: str, *, writable=False) -> Path:
    if not isinstance(name, str):
        raise ReferenceError("repository path must be a string")
    path = Path(name)
    if (path.is_absolute() or not path.parts or name != path.as_posix() or "\\" in name
            or re.search(r"[\x00-\x1f\x7f]", name) or any(part in {"..", "."} for part in path.parts)):
        raise ReferenceError(f"path must be a canonical repository-relative path: {name}")
    if writable and (_historical(name) or path.suffix not in {".md", ".json"}):
        raise ReferenceError(f"historical/unmanaged output cannot be overwritten: {name}")
    if writable and (any(part.lower() in {"legal", "licenses", "licensing"} for part in path.parts)
                     or re.search(r"licen[cs]|notice|copying|copyright", path.name, re.IGNORECASE)):
        raise ReferenceError(f"licensing/notice documents require explicit owner review: {name}")
    result = root / path
    if verify_wiki._symlink_component(result, root) is not None:
        raise ReferenceError(f"symlink path is not safe: {name}")
    return result


def _documents(root: Path) -> dict[str, str]:
    command = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.md"],
                             cwd=root, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
                             capture_output=True, check=False)
    if command.returncode == 0:
        names = set(command.stdout.decode().rstrip("\0").split("\0"))
    else:  # isolated no-Git fixtures, not an alternate production authority
        names = {p.relative_to(root).as_posix() for p in root.rglob("*.md")}
    result = {}
    for name in sorted(names):
        if not name or _historical(name):
            continue
        path = _safe(root, name)
        if path.is_file():
            result[name] = path.read_text(encoding="utf-8")
    return result


def _without_links(text: str) -> str:
    return re.sub(re.escape(START) + r".*?" + re.escape(END), "", text, flags=re.DOTALL)


def _cell(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return html.escape(text).replace("|", "&#124;").replace("\n", "<br>")


def _render_commands(catalog: dict, page="docs/reference/CLI_REFERENCE.md") -> str:
    catalog_link = quote(os.path.relpath(CATALOG, Path(page).parent).replace(os.sep, "/"), safe="/-._~")
    lines = [GENERATED, "", "# CLI definition reference", "", "Generated by `python -m tools.docs.sync_references --update`.", "",
             "Local review candidate. Public/private placement and redistribution rights require explicit review before publication.",
             "These are parser definitions, not execution, security, release or licensing qualification.",
             "Options belong at their defining scope. Put root options before the first subcommand and parent options before its child.",
             "The database default is the source resolver expression; local paths and environment values are not recorded.", "",
             f"Source revisions are content-addressed Git blobs plus SHA-256 in [command_catalog.json]({catalog_link}).", ""]
    for row in catalog["commands"]:
        lines.extend([f"## {_cell(row['path'])}", "", _cell(row["summary"]), ""])
        if row["aliases"]:
            lines.extend(["Aliases: " + "; ".join(_cell(a) for a in row["aliases"]), ""])
        if not row["leaf"]:
            lines.extend([f"Subcommand required: {str(row['subcommands_required']).lower()}.", ""])
        lines.extend(["| Scope | Argument / aliases | Arity | Required | Default | Const | Metavar | Type / action | Choices | Help |",
                      "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"])
        for arg in row["inherited_arguments"] + row["arguments"]:
            default = "omitted unless supplied" if arg.get("default_kind") == "suppressed" else arg["default"]
            cells = [arg["scope"], " / ".join(arg["flags"]) or arg["dest"],
                     1 if arg["nargs"] is None else arg["nargs"], arg["required"], default, arg["const"], arg["metavar"],
                     f"{arg['type'] or 'implicit'} / {arg['action']}", arg["choices"], arg["help"] or ""]
            lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
        if row["exclusive_groups"]:
            lines.extend(["", "Mutually exclusive groups: " + _cell(row["exclusive_groups"])])
        lines.append("")
    return "\n".join(lines)


def _link_definition(root: Path, page: str, target: str) -> str:
    if (not isinstance(target, str) or re.search(r"[\s<>\x00-\x1f\x7f]", target)
            or re.search(r"[\x00-\x1f\x7f]", unquote(target))):
        raise ReferenceError("canonical link contains whitespace, control characters or unsafe delimiters")
    parsed = urlsplit(target)
    if parsed.scheme:
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or "\\" in parsed.netloc or parsed.port == 0):
            raise ReferenceError("canonical external links must be credential-free HTTPS URLs")
        if any(re.search(r"token|secret|password|credential|signature|api.?key|auth", key, re.IGNORECASE)
               for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
            raise ReferenceError("canonical external links cannot carry credential query fields")
        return target
    if parsed.netloc or parsed.query:
        raise ReferenceError("canonical local links cannot use a host or query")
    path = _safe(root, unquote(parsed.path))
    relative = os.path.relpath(path, (root / page).parent).replace(os.sep, "/")
    return quote(relative, safe="/-._~") + ("#" + parsed.fragment if parsed.fragment else "")


def _validate_links(root: Path, links: dict, virtual: dict[str, str]):
    for link_id, target in links.items():
        if not isinstance(link_id, str) or not re.fullmatch(r"[a-z0-9-]+", link_id) or not isinstance(target, str) or not target:
            raise ReferenceError("invalid canonical link ID/target")
        _link_definition(root, "README.md", target)
        parsed = urlsplit(target)
        if parsed.scheme:
            continue  # identity only; no claim of live network availability
        name = unquote(parsed.path)
        path = _safe(root, name)
        if name not in virtual and not path.is_file():
            raise ReferenceError(f"canonical link {link_id} has a missing target: {name}")
        if parsed.fragment:
            text = virtual[name] if name in virtual else path.read_text(encoding="utf-8")
            if unquote(parsed.fragment) not in verify_wiki._document_anchors(text):
                raise ReferenceError(f"canonical link {link_id} has a missing fragment")


def _link_key(target: str) -> tuple:
    parsed = urlsplit(target)
    return (parsed.scheme, parsed.netloc.lower(), os.path.normpath(unquote(parsed.path)), parsed.query)


def _baseline_registered(root: Path) -> bool:
    environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    indexed = subprocess.run(["git", "ls-files", "--cached", "--", CATALOG, STATE], cwd=root,
                             env=environment, capture_output=True, check=False)
    if indexed.returncode == 0 and indexed.stdout.strip():
        return True
    head = subprocess.run(["git", "cat-file", "-e", f"HEAD:{STATE}"], cwd=root,
                          env=environment, capture_output=True, check=False)
    return head.returncode == 0


def _digest(value, length=64) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def _validate_catalog(root: Path, catalog: dict):
    if (not isinstance(catalog, dict) or catalog.get("schema") != "seam-command-reference/1"
            or not isinstance(catalog.get("sources"), dict) or not catalog["sources"]
            or not isinstance(catalog.get("source_revision_kind"), str)
            or not isinstance(catalog.get("commands"), list) or not catalog["commands"]):
        raise ReferenceError("missing source-bound command metadata; empty fallback is forbidden")
    for name, identity in catalog["sources"].items():
        _safe(root, name)
        if (not isinstance(identity, dict) or not _digest(identity.get("sha256"))
                or not _digest(identity.get("git_blob_sha1"), 40)):
            raise ReferenceError("missing source content identities")
    paths = []
    row_fields = {"path", "aliases", "summary", "arguments", "inherited_arguments",
                  "exclusive_groups", "subcommands_required", "leaf"}
    arg_fields = {"scope", "dest", "flags", "action", "nargs", "required", "default",
                  "const", "metavar", "type", "choices", "help"}
    for row in catalog["commands"]:
        if (not isinstance(row, dict) or not row_fields <= row.keys()
                or not isinstance(row["path"], str) or not row["path"].startswith("seam")
                or not isinstance(row["aliases"], list) or not isinstance(row["summary"], str)
                or not isinstance(row["leaf"], bool) or not isinstance(row["subcommands_required"], bool)
                or any(not isinstance(row[key], list) for key in ("arguments", "inherited_arguments", "exclusive_groups"))):
            raise ReferenceError("incomplete command contract")
        paths.append(row["path"])
        for arg in row["arguments"] + row["inherited_arguments"]:
            if (not isinstance(arg, dict) or not arg_fields <= arg.keys()
                    or not isinstance(arg["flags"], list) or not isinstance(arg["required"], bool)):
                raise ReferenceError("incomplete argument contract")
    if (len(set(paths)) != len(paths) or "seam" not in paths
            or not any(row["leaf"] and row["path"].startswith("seam ") for row in catalog["commands"])):
        raise ReferenceError("missing/duplicate root or leaf command contract")


def _validate_state(root: Path, state: dict, previous: dict):
    required = {"schema", "baseline_is_identity_not_semantic_approval", "links", "command_contract_sha256", "catalog_sha256",
                "documents", "unmanaged_documents", "pending_reviews", "review_acknowledgements", "scope"}
    if (not required <= state.keys() or state.get("schema") != "seam-doc-reference-state/2"
            or state["baseline_is_identity_not_semantic_approval"] is not True
            or state["command_contract_sha256"] != _sha(previous["commands"])
            or state["catalog_sha256"] != _sha(previous)
            or not isinstance(state["scope"], str)
            or not isinstance(state["unmanaged_documents"], list)
            or any(not isinstance(state[key], dict) for key in ("links", "documents", "pending_reviews", "review_acknowledgements"))):
        raise ReferenceError("incomplete/inconsistent saved state; cannot discard review history")
    for name, identity in state["documents"].items():
        _safe(root, name)
        if not _digest(identity):
            raise ReferenceError("invalid saved document identity")
    for name in state["unmanaged_documents"]:
        _safe(root, name)
    for key, target in state["links"].items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9-]+", key):
            raise ReferenceError("invalid saved link ID")
        _link_definition(root, "README.md", target)
    for group in ("pending_reviews", "review_acknowledgements"):
        for name, review in state[group].items():
            _safe(root, name)
            if (not isinstance(review, dict) or not isinstance(review.get("reasons"), list) or not review["reasons"]
                    or any(not isinstance(reason, str) for reason in review["reasons"])
                    or not _digest(review.get("document_sha256")) or not _digest(review.get("command_contract_sha256"))):
                raise ReferenceError("incomplete saved review record")
            # Older explicit reviews retain their original narrower provenance.
            for key in ("source_revisions_sha256", "link_registry_sha256"):
                if key in review and not _digest(review[key]):
                    raise ReferenceError("invalid saved review provenance")
            if group == "review_acknowledgements" and not isinstance(review.get("scope"), str):
                raise ReferenceError("missing saved acknowledgement scope")


def _no_secrets(name: str, text: str):
    findings = scan_bytes(name, text.encode("utf-8"), include_binary=True)
    if findings:
        raise ReferenceError("unsafe generated metadata: " + "; ".join(finding.format() for finding in findings))


def _write_transaction(root: Path, expected: dict, changed: list[str]):
    """Stage all writes and recovery copies; roll back recoverable replacement errors.

    This is not filesystem-wide atomicity across process death. A persistent
    rollback failure retains recovery files and the caller fails visibly.
    """
    staged, backups, originals, created_dirs, applied = {}, {}, {}, [], []
    retain = set()

    def temporary(path, content, mode):
        with NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".seam-docs-", delete=False) as stream:
            name = Path(stream.name)
            staged_files.add(name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        return name

    staged_files = set()
    try:
        for name in changed:
            path = _safe(root, name, writable=True)
            missing = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            path.parent.mkdir(parents=True, exist_ok=True)
            created_dirs.extend(reversed(missing))
            original = path.read_bytes() if path.exists() else None
            mode = stat.S_IMODE(path.stat().st_mode) if original is not None else 0o644
            originals[name] = original
            if original is not None:
                backups[name] = temporary(path, original, mode)
            staged[name] = temporary(path, expected[name].encode("utf-8"), mode)
        # Do not overwrite a concurrent authored edit made while preparing.
        for name in changed:
            path = _safe(root, name, writable=True)
            if (path.read_bytes() if path.exists() else None) != originals[name]:
                raise ReferenceError("managed output changed concurrently; rerun after review")
        # Commit review state last. Recovery copies are ready before any write.
        for name in sorted(changed, key=lambda name: name == STATE):
            os.replace(staged[name], _safe(root, name, writable=True))
            applied.append(name)
    except (OSError, ReferenceError) as exc:
        failed = []
        for name in reversed(applied):
            try:
                path = _safe(root, name, writable=True)
                if originals[name] is None:
                    path.unlink()
                else:
                    os.replace(backups[name], path)
            except OSError:
                failed.append(name)
                if name in backups:
                    retain.add(backups[name])
        if failed:
            raise ReferenceError("update and rollback failed; restore retained .seam-docs- recovery files for: "
                                 + ", ".join(failed)) from exc
        raise
    finally:
        for path in staged_files - retain:
            path.unlink(missing_ok=True)
        for directory in reversed(created_dirs):
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()


def run(root: Path, *, catalog: dict | None = None, update=False, acknowledge=()) -> Result:
    root = root.resolve()
    result = Result()
    try:
        config = _read_json(_safe(root, CONFIG))
        _no_secrets(CONFIG, _json(config))
        if config.get("schema") != "seam-doc-references/1":
            raise ReferenceError("missing/unsupported reference configuration schema")
        links, pages, command_pages = (config.get(k) for k in ("links", "managed_pages", "command_pages"))
        if not isinstance(links, dict) or not links or not isinstance(pages, list) or not pages or not isinstance(command_pages, list) or not command_pages:
            raise ReferenceError("missing canonical links or registered managed copies")
        targets = pages + command_pages + [CATALOG, STATE]
        if len(set(targets)) != len(targets):
            raise ReferenceError("duplicate managed output registration")
        for name in targets:
            if not isinstance(name, str):
                raise ReferenceError("output path must be a string")
            _safe(root, name, writable=True)
        for name in pages:
            if Path(name).suffix != ".md":
                raise ReferenceError("managed link pages must be Markdown")
        for name in command_pages:
            if not name.startswith("docs/reference/") or Path(name).suffix != ".md":
                raise ReferenceError("whole generated command pages must stay under docs/reference/")
            path = _safe(root, name, writable=True)
            if path.exists() and not path.read_text(encoding="utf-8").startswith(GENERATED + "\n"):
                raise ReferenceError(f"authored page cannot be replaced by a generated reference: {name}")
        catalog = build_catalog(root) if catalog is None else catalog
        _validate_catalog(root, catalog)
        _no_secrets(CATALOG, _json(catalog))
        documents = _documents(root)
        expected = {name: _render_commands(catalog, name) for name in command_pages}
        for name in pages:
            text = documents.get(name)
            if text is None or text.count(START) != 1 or text.count(END) != 1 or text.index(END) < text.index(START):
                raise ReferenceError(f"managed page needs exactly one ordered link block: {name}")
            defs = "\n".join(f"[seam:{key}]: {_link_definition(root, name, value)}" for key, value in sorted(links.items()))
            expected[name] = re.sub(re.escape(START) + r".*?" + re.escape(END),
                                    lambda _: START + "\n" + defs + "\n" + END, text, flags=re.DOTALL)
        _validate_links(root, links, expected)
        for name, text in documents.items():
            authored = _without_links(text) if name in pages else text
            used = {key.lower() for key in LINK_ID.findall(authored)}
            unknown = used - set(links)
            if unknown:
                raise ReferenceError(f"unresolved canonical link IDs in {name}: {', '.join(sorted(unknown))}")
            if used and name not in pages:
                raise ReferenceError(f"canonical link consumer needs a registered definition block: {name}")
        catalog_path, state_path = (_safe(root, name, writable=True) for name in (CATALOG, STATE))
        if catalog_path.exists() != state_path.exists():
            raise ReferenceError("incomplete baseline: restore catalog/state together; cannot silently reset pending review")
        if not catalog_path.exists() and (_baseline_registered(root)
                                          or any((root / name).exists() for name in command_pages)):
            raise ReferenceError("saved baseline is missing; restore it instead of discarding pending reviews")
        previous = _read_json(catalog_path) if catalog_path.exists() else None
        state = _read_json(state_path) if state_path.exists() else {}
        if previous is not None:
            _validate_catalog(root, previous)
            _validate_state(root, state, previous)
        manual = {name: (_without_links(text) if name in pages else text)
                  for name, text in documents.items() if name not in command_pages}
        result.unmanaged = sorted(set(manual) - set(pages))
        pending = dict(state.get("pending_reviews", {}))
        command_changed = previous is not None and previous["commands"] != catalog["commands"]
        source_changed = previous is not None and previous["sources"] != catalog["sources"]
        old_links = state.get("links", links)
        link_changes = {key for key in set(old_links) | set(links) if old_links.get(key) != links.get(key)}
        old_documents = state.get("documents", {})
        for name in set(old_documents) - set(manual):
            reasons = set(pending.get(name, {}).get("reasons", []))
            reasons.add("hand-written page removed; review its removal explicitly")
            pending[name] = {"reasons": sorted(reasons), "document_sha256": old_documents[name],
                             "document_missing": True, "command_contract_sha256": _sha(catalog["commands"]),
                             "source_revisions_sha256": _sha(catalog["sources"]), "link_registry_sha256": _sha(links)}
        for name, text in manual.items():
            reasons = set(pending.get(name, {}).get("reasons", []))
            if command_changed and CLI_MENTION.search(text):
                reasons.add("CLI definitions changed; review hand-written command claims/examples")
            if source_changed and CLI_MENTION.search(text):
                reasons.add("CLI source revisions changed; review hand-written command behavior claims")
            for key in link_changes:
                old = old_links.get(key)
                if key in {identity.lower() for identity in LINK_ID.findall(text)}:
                    reasons.add(f"canonical link {key} changed; review its hand-written consumer prose")
                if old:
                    local_old = _link_definition(root, name, old)
                    if old in text or any(_link_key(target) == _link_key(local_old)
                                          for target in verify_wiki._link_targets(text)):
                        reasons.add(f"canonical link {key} changed; review unmanaged link/prose")
            text_hash = hashlib.sha256(text.encode()).hexdigest()
            if previous is not None and old_documents.get(name) != text_hash:
                reasons.add("hand-written content added/changed; review the authored change")
            if reasons:
                pending[name] = {"reasons": sorted(reasons), "document_sha256": text_hash,
                                 "command_contract_sha256": _sha(catalog["commands"]),
                                 "source_revisions_sha256": _sha(catalog["sources"]),
                                 "link_registry_sha256": _sha(links)}
        if acknowledge and not update:
            raise ReferenceError("review acknowledgement requires --update and explicit paths")
        acknowledgements = dict(state.get("review_acknowledgements", {}))
        for name in acknowledge:
            if name not in pending or (name not in manual and not pending[name].get("document_missing")):
                raise ReferenceError(f"cannot acknowledge a missing/nonpending page: {name}")
            acknowledgements[name] = {**pending.pop(name),
                                      "scope": "Explicit review of the flagged change; not a whole-page audit, licensing approval or release qualification."}
        state = {"schema": "seam-doc-reference-state/2", "baseline_is_identity_not_semantic_approval": True,
                 "links": links, "command_contract_sha256": _sha(catalog["commands"]),
                 "catalog_sha256": _sha(catalog),
                 "documents": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in sorted(manual.items())},
                 "unmanaged_documents": result.unmanaged, "pending_reviews": pending,
                 "review_acknowledgements": acknowledgements,
                 "scope": "Active Markdown identity/review queue. Historical records, full audit, licensing, release and live website qualification remain separate."}
        expected[CATALOG], expected[STATE] = _json(catalog), _json(state)
        for name, text in expected.items():
            _no_secrets(name, text)
        result.pending = sorted(pending)
        for name, text in sorted(expected.items()):
            path = _safe(root, name, writable=True)
            if not path.exists() or path.read_bytes() != text.encode():
                result.changed.append(name)
                if not update:
                    result.errors.append(f"stale/missing managed reference: {name}")
        if update:
            _write_transaction(root, expected, result.changed)
    except (ReferenceError, OSError, ValueError, TypeError, KeyError, ImportError, RuntimeError, AttributeError) as exc:
        message = f"{type(exc).__name__}: {exc}"
        if scan_bytes("generation-error.txt", message.encode("utf-8"), include_binary=True):
            message = f"{type(exc).__name__}: generation failed; unsafe diagnostic content withheld"
        result.errors.append(message)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true", help="Read-only stale/metadata/pending-review gate")
    modes.add_argument("--update", action="store_true", help="Regenerate registered copies; preserve prose/history")
    modes.add_argument("--watch", action="store_true", help="Poll local definitions with a fresh process; no install/publication")
    parser.add_argument("--staged", action="store_true", help="Check the exact index using its staged generator and CLI")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--acknowledge", nargs="*", default=[], metavar="PAGE", help="Record explicit review of named pending pages")
    args = parser.parse_args(argv)
    if args.staged:
        if not args.check or args.acknowledge:
            parser.error("--staged requires --check and cannot acknowledge reviews")
        return _check_staged(args.root.resolve())
    if args.watch:
        if not math.isfinite(args.interval) or args.interval < 1 or args.acknowledge:
            parser.error("watch needs finite interval >=1 and cannot acknowledge reviews")
        try:
            while True:
                subprocess.run([sys.executable, "-m", "tools.docs.sync_references", "--update", "--root", str(args.root.resolve())],
                               cwd=args.root, check=False)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            return 130
    result = run(args.root, update=args.update, acknowledge=args.acknowledge)
    print(_json({"ok": result.ok, "changed": result.changed, "errors": result.errors,
                 "pending_reviews": result.pending, "active_unmanaged_documents": result.unmanaged}), end="")
    return 0 if result.ok else 1


def _check_staged(root: Path) -> int:
    """Like verify_wiki, verify the exact index; an unstaged repair cannot hide drift."""
    with TemporaryDirectory(prefix="seam-doc-reference-index-") as temporary:
        staged_root = Path(temporary)
        export = subprocess.run(["git", "checkout-index", "--all", f"--prefix={staged_root}{os.sep}"],
                                cwd=root, capture_output=True, check=False,
                                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        if export.returncode:
            print("SEAM reference verification FAILED: cannot export Git index", file=sys.stderr)
            return 1
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "GIT_OPTIONAL_LOCKS": "0"}
        environment.pop("PYTHONPATH", None)
        result = subprocess.run([sys.executable, "-m", "tools.docs.sync_references", "--check", "--root", str(staged_root)],
                                cwd=staged_root, env=environment, capture_output=True, text=True, check=False)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        return result.returncode


if __name__ == "__main__":
    sys.exit(main())
