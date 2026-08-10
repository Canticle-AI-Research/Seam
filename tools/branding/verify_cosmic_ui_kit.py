"""Verify the reusable Canticle Cosmic UI Kit and its canonical dependency."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
KIT_ROOT = REPO_ROOT / "branding" / "canticle-cosmic-kit"
BASE_KIT_ROOT = REPO_ROOT / "branding" / "kit"
KIT_ID = "canticle-cosmic-ui"
KIT_VERSION = "1.0.0"
BASE_KIT_ID = "canticle-seam"
BASE_KIT_VERSION = "1.0.0"
BASE_TOKENS_SHA256 = "49be29295fc382caf005f3a7f6194482c6ca0d98b8076924fe072e0ffef9e7d2"

# Independent pin for the versioned manifest. An intentional kit change bumps
# the version and updates this constant in the same reviewed change.
MANIFEST_SHA256 = "1209225cb98802e5cbd7080dab1d44bdddd4b9c30ea287023cf41af453e83e42"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_FILES = {
    "README.md",
    "css/canticle-cosmic.css",
    "go/canticlecosmic/theme.go",
    "preview/index.html",
    "preview/preview.css",
    "tailwind/theme.css",
    "textual/canticle-cosmic.tcss",
    "tokens.json",
}
_MANIFEST_EXCLUSIONS = {"manifest.json"}
_MEDIA_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".go": "text/x-go; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".md": "text/markdown; charset=utf-8",
    ".tcss": "text/x-tcss; charset=utf-8",
}
_BASE_ASSETS = {
    "canticle_company_lockup": (
        "../kit/marks/canticle-company-lockup.svg",
        "0280de1d17a8652e8a3dcc7afe938ff6f86913d638e835a362eef3c838dfdd5b",
        "marks/canticle-company-lockup.svg",
    ),
    "seam_product_lockup": (
        "../kit/marks/seam-product-lockup.svg",
        "f296541cdac964f58aa6b407c04b4aa49fd589458bb71a54d4e75b57725e1b92",
        "marks/seam-product-lockup.svg",
    ),
}
_BASE_COLOR_PATHS = {
    "void": ("base", "bg_deep"),
    "night": ("base", "bg"),
    "panel": ("base", "bg_panel"),
    "well": ("base", "bg_sunk"),
    "bubble": ("base", "surface"),
    "ink": ("text_chrome", "text"),
    "ink_muted": ("text_chrome", "text_muted"),
    "ink_quiet": ("text_chrome", "text_dim"),
    "line": ("text_chrome", "border"),
    "line_bright": ("text_chrome", "border_hi"),
    "plasma": ("accent", "pink"),
    "magenta": ("accent", "magenta"),
    "lavender": ("accent", "lavender"),
    "orbit": ("accent", "cyan"),
    "mint": ("accent", "mint"),
    "aqua": ("accent", "green"),
    "sun": ("accent", "yellow"),
    "comet": ("accent", "orange"),
    "danger": ("accent", "red"),
    "blue": ("accent", "blue"),
    "ice": ("accent", "ice"),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{path.name}: cannot read valid UTF-8 JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{path.name}: top level must be an object")
        return None
    return value


def _inventory(root: Path, errors: list[str]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    try:
        root_stat = root.lstat()
    except OSError as exc:
        errors.append(f"kit root: cannot inspect: {exc}")
        return files
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        errors.append("kit root: must be a real directory, not a link")
        return files

    def visit(directory: Path, relative: PurePosixPath) -> None:
        try:
            with os.scandir(directory) as scan:
                entries = sorted(scan, key=lambda entry: entry.name)
        except OSError as exc:
            errors.append(f"{relative.as_posix() or '.'}: cannot inventory: {exc}")
            return
        for entry in entries:
            path = Path(entry.path)
            rel = relative / entry.name
            label = rel.as_posix()
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                errors.append(f"{label}: cannot inspect: {exc}")
                continue
            if entry.is_symlink():
                errors.append(f"{label}: links are forbidden")
            elif entry.is_dir(follow_symlinks=False):
                visit(path, rel)
            elif not stat.S_ISREG(entry_stat.st_mode):
                errors.append(f"{label}: must be a regular file")
            else:
                try:
                    files[label] = path.read_bytes()
                except OSError as exc:
                    errors.append(f"{label}: cannot read: {exc}")

    visit(root, PurePosixPath())
    return files


def _media_type(relative: str) -> str:
    suffix = PurePosixPath(relative).suffix.lower()
    if suffix not in _MEDIA_TYPES:
        raise ValueError(f"unsupported kit file extension: {relative}")
    return _MEDIA_TYPES[suffix]


def build_manifest(root: Path = KIT_ROOT) -> dict[str, Any]:
    """Return the deterministic manifest for the current regular-file inventory."""
    errors: list[str] = []
    inventory = _inventory(root, errors)
    if errors:
        raise ValueError("; ".join(errors))
    files = []
    for relative in sorted(set(inventory) - _MANIFEST_EXCLUSIONS):
        data = inventory[relative]
        files.append(
            {
                "path": relative,
                "media_type": _media_type(relative),
                "bytes": len(data),
                "sha256": _sha256(data),
            }
        )
    return {
        "schema_version": 1,
        "kit_id": KIT_ID,
        "version": KIT_VERSION,
        "extends": f"{BASE_KIT_ID}@{BASE_KIT_VERSION}",
        "files": files,
    }


def render_manifest(root: Path = KIT_ROOT) -> str:
    return json.dumps(build_manifest(root), indent=2, ensure_ascii=False) + "\n"


def _verify_manifest(root: Path, inventory: dict[str, bytes], errors: list[str]) -> None:
    manifest_data = inventory.get("manifest.json")
    if manifest_data is None:
        errors.append("manifest.json: required file is missing")
        return
    if MANIFEST_SHA256 == "TO_BE_PINNED":
        errors.append("manifest.json: verifier digest pin has not been finalized")
    elif _sha256(manifest_data) != MANIFEST_SHA256:
        errors.append(f"manifest.json: differs from pinned {KIT_VERSION} contract")
    try:
        manifest = json.loads(manifest_data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"manifest.json: invalid JSON: {exc}")
        return
    if not isinstance(manifest, dict):
        errors.append("manifest.json: top level must be an object")
        return
    expected_header = {
        "schema_version": 1,
        "kit_id": KIT_ID,
        "version": KIT_VERSION,
        "extends": f"{BASE_KIT_ID}@{BASE_KIT_VERSION}",
    }
    for key, expected in expected_header.items():
        if manifest.get(key) != expected:
            errors.append(f"manifest.json.{key}: expected {expected!r}")
    rows = manifest.get("files")
    if not isinstance(rows, list):
        errors.append("manifest.json.files: must be a list")
        return
    observed: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"manifest.json.files[{index}]: must be an object")
            continue
        relative = row.get("path")
        if not isinstance(relative, str):
            errors.append(f"manifest.json.files[{index}].path: must be a string")
            continue
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
            errors.append(f"manifest.json.files[{index}].path: unsafe path")
            continue
        if relative in observed:
            errors.append(f"manifest.json.files: duplicate path {relative}")
            continue
        observed[relative] = row
    expected_paths = set(inventory) - _MANIFEST_EXCLUSIONS
    if set(observed) != expected_paths:
        errors.append(
            "manifest.json.files: coverage mismatch "
            f"expected={sorted(expected_paths)} observed={sorted(observed)}"
        )
    if list(observed) != sorted(observed):
        errors.append("manifest.json.files: paths must be sorted")
    for relative, row in observed.items():
        data = inventory.get(relative)
        if data is None:
            continue
        try:
            expected_media_type = _media_type(relative)
        except ValueError as exc:
            errors.append(f"{relative}: {exc}")
        else:
            if row.get("media_type") != expected_media_type:
                errors.append(f"{relative}: media type mismatch")
        if row.get("bytes") != len(data):
            errors.append(f"{relative}: byte count mismatch")
        digest = row.get("sha256")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            errors.append(f"{relative}: invalid manifest SHA-256")
        elif digest != _sha256(data):
            errors.append(f"{relative}: SHA-256 mismatch")


def _nested(value: dict[str, Any], *path: str) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _verify_tokens(root: Path, base_root: Path, errors: list[str]) -> None:
    tokens = _read_json(root / "tokens.json", errors)
    base_tokens = _read_json(base_root / "tokens.json", errors)
    base_manifest = _read_json(base_root / "manifest.json", errors)
    if tokens is None or base_tokens is None or base_manifest is None:
        return
    expected_header = {"schema_version": 1, "kit_id": KIT_ID, "version": KIT_VERSION}
    for key, expected in expected_header.items():
        if tokens.get(key) != expected:
            errors.append(f"tokens.json.{key}: expected {expected!r}")
    extends = tokens.get("extends")
    if not isinstance(extends, dict):
        errors.append("tokens.json.extends: must be an object")
        return
    expected_extends = {
        "kit_id": BASE_KIT_ID,
        "version": BASE_KIT_VERSION,
        "path": "../kit",
        "tokens_sha256": BASE_TOKENS_SHA256,
    }
    for key, expected in expected_extends.items():
        if extends.get(key) != expected:
            errors.append(f"tokens.json.extends.{key}: expected {expected!r}")
    if base_manifest.get("kit_id") != BASE_KIT_ID or base_manifest.get("version") != BASE_KIT_VERSION:
        errors.append("base kit: id or version does not match declared dependency")
    try:
        base_tokens_data = (base_root / "tokens.json").read_bytes()
    except OSError as exc:
        errors.append(f"base kit tokens: cannot read: {exc}")
        return
    if _sha256(base_tokens_data) != BASE_TOKENS_SHA256:
        errors.append("base kit tokens: SHA-256 does not match declared dependency")
    primitives = _nested(tokens, "color", "primitive")
    base_color = base_tokens.get("color")
    if not isinstance(primitives, dict) or not isinstance(base_color, dict):
        errors.append("tokens.json.color.primitive: must be an object")
    else:
        if set(primitives) != set(_BASE_COLOR_PATHS):
            errors.append("tokens.json.color.primitive: exact inherited color set is required")
        for name, path in _BASE_COLOR_PATHS.items():
            expected = _nested(base_color, *path)
            if primitives.get(name) != expected:
                errors.append(f"tokens.json.color.primitive.{name}: must equal base token {'.'.join(path)}")
    assets = extends.get("assets")
    if not isinstance(assets, dict):
        errors.append("tokens.json.extends.assets: must be an object")
    else:
        for asset_id, (declared_path, digest, base_relative) in _BASE_ASSETS.items():
            row = assets.get(asset_id)
            if row != {"path": declared_path, "sha256": digest}:
                errors.append(f"tokens.json.extends.assets.{asset_id}: exact base asset pin required")
            try:
                actual = (base_root / base_relative).read_bytes()
            except OSError as exc:
                errors.append(f"base asset {base_relative}: cannot read: {exc}")
                continue
            if _sha256(actual) != digest:
                errors.append(f"base asset {base_relative}: SHA-256 mismatch")
    semantic = _nested(tokens, "color", "semantic")
    if not isinstance(semantic, dict):
        errors.append("tokens.json.color.semantic: must be an object")
    else:
        for name, reference in semantic.items():
            if not isinstance(reference, str) or not reference.startswith("color.primitive."):
                errors.append(f"tokens.json.color.semantic.{name}: must reference color.primitive")
                continue
            target = reference.removeprefix("color.primitive.")
            if not isinstance(primitives, dict) or target not in primitives:
                errors.append(f"tokens.json.color.semantic.{name}: unresolved reference {reference}")
    if _nested(tokens, "motion", "reduced_motion") != {
        "policy": "static-final-frame",
        "animated_distance_px": 0,
        "cursor_visible": True,
    }:
        errors.append("tokens.json.motion.reduced_motion: exact no-motion fallback required")
    if _nested(tokens, "component", "control_min_height_px") != 44:
        errors.append("tokens.json.component.control_min_height_px: must be 44")


class _PreviewInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []
        self.ids: set[str] = set()
        self.has_title = False
        self.has_h1 = False
        self.stylesheets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script":
            self.errors.append("preview/index.html: scripts are forbidden")
        if tag == "title":
            self.has_title = True
        if tag == "h1":
            self.has_h1 = True
        if "id" in values and values["id"]:
            self.ids.add(values["id"] or "")
        if tag == "img" and not values.get("alt"):
            self.errors.append("preview/index.html: every image needs non-empty alt text")
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.stylesheets.append(values["href"] or "")
        for name, value in attrs:
            if name.lower().startswith("on"):
                self.errors.append(f"preview/index.html: event attribute {name} is forbidden")
            if name in {"href", "src"} and value:
                parsed = urlsplit(value)
                if parsed.scheme or parsed.netloc or value.startswith("//"):
                    self.errors.append(f"preview/index.html: external resource {value!r} is forbidden")


def _verify_adapters(root: Path, errors: list[str]) -> None:
    texts: dict[str, str] = {}
    for relative in (
        "css/canticle-cosmic.css",
        "preview/index.html",
        "preview/preview.css",
        "tailwind/theme.css",
        "textual/canticle-cosmic.tcss",
        "go/canticlecosmic/theme.go",
    ):
        try:
            texts[relative] = (root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{relative}: cannot read UTF-8 text: {exc}")
    css = texts.get("css/canticle-cosmic.css", "")
    if "@import" in css or re.search(r"url\s*\(", css, re.IGNORECASE):
        errors.append("css/canticle-cosmic.css: imports and URL resources are forbidden")
    if re.search(r"(?m)^:root\s*,?", css):
        errors.append("css/canticle-cosmic.css: global :root styling is forbidden")
    for marker in (
        ".cc-bubble-card",
        ".cc-button",
        ".cc-input",
        ".cc-table",
        ".cc-orbit-stage",
        "@media (prefers-reduced-motion: reduce)",
        "@media (forced-colors: active)",
    ):
        if marker not in css:
            errors.append(f"css/canticle-cosmic.css: missing contract marker {marker}")
    preview = _PreviewInspector()
    preview.feed(texts.get("preview/index.html", ""))
    errors.extend(preview.errors)
    if not preview.has_title or not preview.has_h1 or "kit-content" not in preview.ids:
        errors.append("preview/index.html: title, h1, and #kit-content are required")
    if preview.stylesheets != ["../css/canticle-cosmic.css", "preview.css"]:
        errors.append("preview/index.html: exact local stylesheet order is required")
    tailwind = texts.get("tailwind/theme.css", "")
    if "@theme {" not in tailwind or "--*: initial" in tailwind:
        errors.append("tailwind/theme.css: must extend a Tailwind v4 theme without resetting it")
    for marker in (
        "--color-canticle-plasma: #ff6090;",
        "--font-canticle-bubble:",
        "--radius-cosmic-bubble: 2rem;",
        "--animate-cosmic-float:",
        "@media (prefers-reduced-motion: reduce)",
        "--animate-cosmic-float: none;",
    ):
        if marker not in tailwind:
            errors.append(f"tailwind/theme.css: missing contract marker {marker}")
    textual = texts.get("textual/canticle-cosmic.tcss", "")
    if not textual or re.search(r"(?m)^(?:Screen|Button|Input|DataTable|OptionList)\s*\{", textual):
        errors.append("textual/canticle-cosmic.tcss: bare widget selectors are forbidden")
    for marker in (".cc-cosmic-bubble", ".cc-cosmic-button", ".cc-cosmic-input", ".cc-cosmic-table"):
        if marker not in textual:
            errors.append(f"textual/canticle-cosmic.tcss: missing contract marker {marker}")
    go = texts.get("go/canticlecosmic/theme.go", "")
    if '"charm.land/lipgloss/v2"' not in go or '"image/color"' not in go:
        errors.append("go/canticlecosmic/theme.go: Lip Gloss v2 import is required")
    if "bubbletea" in go.lower() or "package canticlecosmic" not in go:
        errors.append("go/canticlecosmic/theme.go: presentation-only package contract violated")
    for marker in (
        "color.Color",
        "func New() Theme",
        "func (t Theme) Bubble()",
        "func (t Theme) PrimaryButton()",
    ):
        if marker not in go:
            errors.append(f"go/canticlecosmic/theme.go: missing contract marker {marker}")


def verify_kit(root: Path = KIT_ROOT, base_root: Path = BASE_KIT_ROOT) -> list[str]:
    errors: list[str] = []
    inventory = _inventory(root, errors)
    observed_files = set(inventory) - _MANIFEST_EXCLUSIONS
    if observed_files != _EXPECTED_FILES:
        errors.append(
            "kit inventory: exact file set required "
            f"expected={sorted(_EXPECTED_FILES)} observed={sorted(observed_files)}"
        )
    for relative, data in inventory.items():
        if relative == "manifest.json":
            continue
        if b"\r" in data:
            errors.append(f"{relative}: CR bytes are forbidden; use LF")
        if b"\x00" in data:
            errors.append(f"{relative}: NUL bytes are forbidden")
    _verify_manifest(root, inventory, errors)
    _verify_tokens(root, base_root, errors)
    _verify_adapters(root, errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=KIT_ROOT)
    parser.add_argument("--base-root", type=Path, default=BASE_KIT_ROOT)
    parser.add_argument(
        "--print-manifest",
        action="store_true",
        help="Print the deterministic manifest; never writes files.",
    )
    args = parser.parse_args(argv)
    if args.print_manifest:
        try:
            print(render_manifest(args.root), end="")
        except ValueError as exc:
            print(f"Cosmic UI kit manifest failed: {exc}", file=sys.stderr)
            return 1
        return 0
    errors = verify_kit(args.root, args.base_root)
    if errors:
        print("Canticle Cosmic UI Kit verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Canticle Cosmic UI Kit OK: {KIT_ID}@{KIT_VERSION} ({len(_EXPECTED_FILES)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
