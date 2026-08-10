"""Deterministically verify the canonical Canticle / SEAM brand kit."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[2]
KIT_ROOT = REPO_ROOT / "branding" / "kit"
SOURCE_COMMIT = "b492659e3ab5751bdaa576529b5a1cbf7a382635"
KIT_VERSION = "1.0.0"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_SVG_NUMBER_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_SVG_VIEWBOX_RE = re.compile(
    r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
    r"(?: -?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?){3}$"
)
_SVG_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_SVG_IDREFS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*(?: [A-Za-z_][A-Za-z0-9_.-]*)+$")
_SVG_COLOR_RE = re.compile(r"^#[0-9a-f]{6}$")
_SVG_ALLOWED_ATTRIBUTES = {
    "svg": {
        "viewBox",
        "role",
        "aria-labelledby",
        "data-brand-kit",
        "data-motion",
    },
    "title": {"id"},
    "desc": {"id"},
    "rect": {"x", "y", "width", "height", "rx", "fill", "stroke", "stroke-width"},
    "text": {
        "x",
        "y",
        "fill",
        "font-family",
        "font-size",
        "font-weight",
        "letter-spacing",
    },
}
_SVG_FONT_FAMILY = "'Fira Code', 'JetBrains Mono', 'Cascadia Mono', monospace"

_EXPECTED_ASSETS: dict[str, tuple[str, str]] = {
    "canticle.company.svg": ("marks/canticle-company-lockup.svg", "image/svg+xml"),
    "canticle.company.terminal": (
        "terminal/canticle-company-lockup.txt",
        "text/plain; charset=utf-8",
    ),
    "canticle.provenance": ("provenance.json", "application/json"),
    "canticle.tokens": ("tokens.json", "application/json"),
    "seam.product.svg": ("marks/seam-product-lockup.svg", "image/svg+xml"),
    "seam.product.terminal": (
        "terminal/seam-product-lockup.txt",
        "text/plain; charset=utf-8",
    ),
}

# These digests live in verifier code, outside the mutable kit manifest.  A
# consumer can therefore detect an asset+manifest rewrite that still claims to
# be the pinned v1.0.0 contract.  A deliberate asset change requires
# a new kit version and a reviewed verifier update.
_EXPECTED_ASSET_DIGESTS: dict[str, str] = {
    "marks/canticle-company-lockup.svg": ("0280de1d17a8652e8a3dcc7afe938ff6f86913d638e835a362eef3c838dfdd5b"),
    "marks/seam-product-lockup.svg": ("f296541cdac964f58aa6b407c04b4aa49fd589458bb71a54d4e75b57725e1b92"),
    "provenance.json": "1d64332a7a741fd5b027619fed1e3e41f5209805421b06a5f40ed9194f59e65a",
    "terminal/canticle-company-lockup.txt": ("e34ea4c25f6076c11934581c8d41c4f0a84510759587b824a67e544077a96046"),
    "terminal/seam-product-lockup.txt": ("549ab8110402a56067d0cedd10c7ecb0a3ce3e770f497afafc01e483965b92a7"),
    "tokens.json": "49be29295fc382caf005f3a7f6194482c6ca0d98b8076924fe072e0ffef9e7d2",
}

_EXPECTED_COLORS: dict[str, dict[str, str]] = {
    "base": {
        "bg": "#1a1b26",
        "bg_deep": "#16161e",
        "bg_panel": "#1f2028",
        "bg_sunk": "#13131a",
        "surface": "#24253a",
        "brand_square": "#0a0b0a",
    },
    "accent": {
        "pink": "#ff6090",
        "magenta": "#e478d0",
        "lavender": "#c4a7e7",
        "cyan": "#7dcfff",
        "mint": "#9ece6a",
        "green": "#73daca",
        "yellow": "#e0af68",
        "orange": "#ff9e64",
        "red": "#f7768e",
        "blue": "#7aa2f7",
        "ice": "#b4f9f8",
    },
    "text_chrome": {
        "text": "#c0caf5",
        "text_dim": "#565f89",
        "text_muted": "#a9b1d6",
        "border": "#3b3d57",
        "border_hi": "#565f89",
    },
    "glow": {
        "pink": "rgba(255, 96, 144, 0.25)",
        "cyan": "rgba(125, 207, 255, 0.2)",
        "mint": "rgba(115, 218, 202, 0.2)",
    },
}

_EXPECTED_FONT_FAMILIES = {
    "mono": ["Fira Code", "JetBrains Mono", "Cascadia Mono", "monospace"],
    "sans": ["Outfit", "system-ui", "sans-serif"],
    "accent": ["Press Start 2P", "monospace"],
}

_EXPECTED_LOCKUP = {
    "prompt": "❯",
    "cursor": "█",
    "alignment": "center",
    "line_height": 1,
    "gap": "0.6rem",
    "square": {
        "height": "30px",
        "inner_gap": "4px",
        "padding_inline": "9px",
        "background": "color.base.brand_square",
        "border_width": "1.5px",
        "border_radius": "7px",
    },
    "cursor_size": {"width": "8px", "height": "15px"},
}

_EXPECTED_RGB_STOPS = [
    (0, "color.accent.red"),
    (14, "color.accent.orange"),
    (28, "color.accent.yellow"),
    (42, "color.accent.mint"),
    (57, "color.accent.cyan"),
    (71, "color.accent.blue"),
    (85, "color.accent.magenta"),
    (100, "color.accent.red"),
]

_EXPECTED_SEMANTIC_COLORS = {
    "canvas": "color.base.bg",
    "chrome": "color.base.bg_deep",
    "panel": "color.base.bg_panel",
    "well": "color.base.bg_sunk",
    "surface": "color.base.surface",
    "text_primary": "color.text_chrome.text",
    "text_secondary": "color.text_chrome.text_muted",
    "text_quiet": "color.text_chrome.text_dim",
    "border": "color.text_chrome.border",
    "border_focus": "color.text_chrome.border_hi",
    "brand_prompt": "color.accent.mint",
    "brand_live": "color.accent.pink",
    "status_success": "color.accent.green",
    "status_warning": "color.accent.yellow",
    "status_danger": "color.accent.red",
    "status_info": "color.accent.cyan",
}

_EXPECTED_TYPOGRAPHY = {
    "families": _EXPECTED_FONT_FAMILIES,
    "web_font_weights": {
        "mono": [400, 600, 700],
        "sans": [300, 400, 600, 800],
        "accent": [400],
    },
    "roles": {
        "body": {"family": "mono", "weight": 400},
        "brand_prompt": {"family": "mono", "size": "0.85rem", "weight": 700},
        "brand_word": {
            "family": "mono",
            "size": "1.1rem",
            "weight": 700,
            "letter_spacing": "0.02em",
        },
        "display": {"family": "sans", "weight": 800},
        "pixel_accent": {"family": "accent", "weight": 400},
    },
}

_EXPECTED_MOTION = {
    "cursor_blink": {
        "duration_ms": 800,
        "timing": "step-end",
        "iterations": "infinite",
        "keyframes": [
            {"offset_percent": 0, "opacity": 1},
            {"offset_percent": 50, "opacity": 0},
            {"offset_percent": 100, "opacity": 1},
        ],
    },
    "rgb_cycle": {
        "duration_ms": 8000,
        "timing": "linear",
        "iterations": "infinite",
        "targets": ["lockup.border", "lockup.cursor", "lockup.word"],
        "stops": [{"offset_percent": offset, "color": color} for offset, color in _EXPECTED_RGB_STOPS],
        "effects": {
            "border_glow": {
                "near_blur_px": 18,
                "near_alpha": 0.35,
                "far_blur_px": 50,
                "far_alpha": 0.12,
            },
            "word_glow": {"blur_px": 12, "alpha": 0.5},
            "cursor_glow": {"blur_px": 8, "alpha": 1.0},
        },
    },
    "hover_lift": {"translate_y_px": -1, "duration_ms": 200, "timing": "ease"},
    "product_type_on": {
        "text": "SEAM",
        "frames": ["S", "SE", "SEA", "SEAM"],
        "interval_ms": 120,
        "final_hold_ms": 360,
        "iterations": 1,
        "reduced_motion_frame": "SEAM",
    },
    "reduced_motion": {"policy": "static-first-frame", "cursor_visible": True},
}

_EXPECTED_TOKENS: dict[str, Any] = {
    "schema_version": 1,
    "kit_id": "canticle-seam",
    "source_commit": SOURCE_COMMIT,
    "color": {**_EXPECTED_COLORS, "semantic": _EXPECTED_SEMANTIC_COLORS},
    "typography": _EXPECTED_TYPOGRAPHY,
    "lockup": _EXPECTED_LOCKUP,
    "motion": _EXPECTED_MOTION,
}

_EXPECTED_TERMINAL = {
    "terminal/canticle-company-lockup.txt": "╭────╮\n│ ❯ █│ Canticle\n╰────╯\n",
    "terminal/seam-product-lockup.txt": "╭────╮\n│ ❯ █│ SEAM\n╰────╯\n",
}

_EXPECTED_SVG_ACCESSIBILITY = {
    "marks/canticle-company-lockup.svg": (
        "Canticle",
        "canticle-lockup-title",
        "canticle-lockup-desc",
    ),
    "marks/seam-product-lockup.svg": (
        "SEAM",
        "seam-lockup-title",
        "seam-lockup-desc",
    ),
}

_EXPECTED_SOURCE_EXCERPTS = {
    ("styles.css", "5-37"): "507dce9efdb65adf6d6e7867d069791e08f08183ff65020ad702e7d5d670daa6",
    ("styles.css", "229-407"): "8ca8364c8ac5501aea33e8a9b0d5ce247d664badba2fbeb4797136f5cf084146",
    ("styles.css", "4225-4235"): "1c15822de9c2bcc7d93e9bc3c2760caaba9de919ee8a4a290486d5cb30da799d",
    ("index.html", "32-35"): "f4c51c7164ab1cd133fd0ee7007cd7d85402885e46a309049cbee08c178e333e",
}


def _read_json(relative: str, data: bytes, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{relative}: cannot read valid UTF-8 JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{relative}: top level must be a JSON object")
        return None
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_asset_relative(raw_path: object) -> str | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    if "\\" in raw_path:
        return None
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        return None
    if relative.as_posix() != raw_path:
        return None
    return relative.as_posix()


def _is_reparse_point(path: Path, entry_stat: object) -> bool:
    """Return whether a path can redirect traversal on Windows.

    NTFS junctions are not reported as ordinary symlinks, and Windows does
    not provide the same effective ``O_NOFOLLOW`` boundary as POSIX. Check
    both pathlib's junction classification and the raw reparse attribute so
    every redirecting filesystem object fails closed before traversal/read.
    """
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if int(getattr(entry_stat, "st_file_attributes", 0)) & reparse_flag:
        return True
    is_junction = getattr(path, "is_junction", None)
    if not callable(is_junction):
        return False
    try:
        return bool(is_junction())
    except OSError:
        # An uninspectable junction-like entry is not safe to traverse.
        return True


def _verify_kit_root(root: Path, errors: list[str]) -> bool:
    try:
        root_stat = root.lstat()
    except OSError as exc:
        errors.append(f"kit root: cannot inspect filesystem entry: {exc}")
        return False
    if stat.S_ISLNK(root_stat.st_mode):
        errors.append("kit root: symlinks are forbidden")
        return False
    if _is_reparse_point(root, root_stat):
        errors.append("kit root: filesystem reparse points are forbidden")
        return False
    if not stat.S_ISDIR(root_stat.st_mode):
        errors.append("kit root: must be a regular directory")
        return False
    return True


def _inventory_regular_files(root: Path, errors: list[str]) -> set[str]:
    """Inventory without following symlinks or reading non-regular entries."""

    regular_files: set[str] = set()

    def visit(directory: Path, relative_directory: PurePosixPath) -> None:
        try:
            with os.scandir(directory) as entries:
                ordered_entries = sorted(entries, key=lambda entry: entry.name)
        except OSError as exc:
            label = relative_directory.as_posix() if relative_directory.parts else "."
            errors.append(f"{label}: cannot inventory kit directory: {exc}")
            return
        for entry in ordered_entries:
            relative = relative_directory / entry.name
            label = relative.as_posix()
            try:
                if entry.is_symlink():
                    errors.append(f"{label}: symlinks are forbidden")
                    continue
                entry_path = Path(entry.path)
                entry_stat = entry.stat(follow_symlinks=False)
                if _is_reparse_point(entry_path, entry_stat):
                    errors.append(f"{label}: filesystem reparse points are forbidden")
                elif entry.is_dir(follow_symlinks=False):
                    visit(entry_path, relative)
                elif entry.is_file(follow_symlinks=False):
                    regular_files.add(label)
                else:
                    errors.append(f"{label}: non-regular filesystem entries are forbidden")
            except OSError as exc:
                errors.append(f"{label}: cannot inspect filesystem entry: {exc}")

    visit(root, PurePosixPath())
    return regular_files


def _read_regular_file(root: Path, relative: str, errors: list[str]) -> bytes | None:
    """Read one canonical file after rechecking every path component."""

    current = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current /= part
        try:
            entry_stat = current.lstat()
        except OSError as exc:
            errors.append(f"{relative}: cannot inspect canonical file: {exc}")
            return None
        if stat.S_ISLNK(entry_stat.st_mode):
            errors.append(f"{relative}: symlinks are forbidden")
            return None
        if _is_reparse_point(current, entry_stat):
            errors.append(f"{relative}: filesystem reparse points are forbidden")
            return None
        is_final = index == len(parts) - 1
        expected_type = stat.S_ISREG if is_final else stat.S_ISDIR
        if not expected_type(entry_stat.st_mode):
            kind = "regular file" if is_final else "directory"
            errors.append(f"{relative}: canonical path component must be a {kind}")
            return None

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(current, flags)
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            errors.append(f"{relative}: canonical asset must be a regular file")
            return None
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            return stream.read()
    except OSError as exc:
        errors.append(f"{relative}: cannot safely read canonical file: {exc}")
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _verify_manifest(
    manifest: dict[str, Any],
    canonical_files: Mapping[str, bytes],
    inventory: set[str],
    errors: list[str],
) -> None:
    expected_root_keys = {
        "schema_version",
        "kit_id",
        "version",
        "canonical_tokens",
        "provenance",
        "assets",
    }
    if set(manifest) != expected_root_keys:
        errors.append("manifest.json: root keys differ from the versioned contract")
    if manifest.get("schema_version") != 1:
        errors.append("manifest.json: schema_version must be 1")
    if manifest.get("kit_id") != "canticle-seam":
        errors.append("manifest.json: kit_id must be canticle-seam")
    if manifest.get("version") != KIT_VERSION:
        errors.append(f"manifest.json: version must be {KIT_VERSION}")
    if manifest.get("canonical_tokens") != "tokens.json":
        errors.append("manifest.json: canonical_tokens must be tokens.json")
    if manifest.get("provenance") != "provenance.json":
        errors.append("manifest.json: provenance must be provenance.json")

    assets = manifest.get("assets")
    if not isinstance(assets, list):
        errors.append("manifest.json: assets must be a list")
        return

    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    declared: dict[str, tuple[str, str]] = {}
    for index, asset in enumerate(assets):
        prefix = f"manifest.json: assets[{index}]"
        if not isinstance(asset, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if set(asset) != {"id", "path", "media_type", "sha256"}:
            errors.append(f"{prefix} keys differ from the versioned contract")
        asset_id = asset.get("id")
        raw_path = asset.get("path")
        media_type = asset.get("media_type")
        digest = asset.get("sha256")
        if not isinstance(asset_id, str) or not asset_id:
            errors.append(f"{prefix}.id must be a non-empty string")
            continue
        if asset_id in seen_ids:
            errors.append(f"{prefix}.id duplicates {asset_id}")
        seen_ids.add(asset_id)
        if not isinstance(raw_path, str):
            errors.append(f"{prefix}.path must be a string")
            continue
        if raw_path in seen_paths:
            errors.append(f"{prefix}.path duplicates {raw_path}")
        seen_paths.add(raw_path)
        if not isinstance(media_type, str):
            errors.append(f"{prefix}.media_type must be a string")
            continue
        declared[asset_id] = (raw_path, media_type)

        relative = _safe_asset_relative(raw_path)
        if relative is None:
            errors.append(f"{prefix}.path is not a safe kit-relative path")
            continue
        data = canonical_files.get(relative)
        if data is None:
            errors.append(f"{raw_path}: declared asset is not a canonical regular file")
            continue
        if not data:
            errors.append(f"{raw_path}: asset is empty")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            errors.append(f"{prefix}.sha256 must be a lowercase SHA-256 digest")
        elif digest != _sha256(data):
            errors.append(f"{raw_path}: SHA-256 mismatch")
        pinned_digest = _EXPECTED_ASSET_DIGESTS.get(raw_path)
        if pinned_digest is not None and digest != pinned_digest:
            errors.append(f"{prefix}.sha256 differs from the pinned {KIT_VERSION} digest")

    if declared != _EXPECTED_ASSETS:
        errors.append("manifest.json: asset IDs, paths, or media types differ from the canonical set")
    if [asset.get("id") for asset in assets if isinstance(asset, dict)] != sorted(seen_ids):
        errors.append("manifest.json: assets must be sorted by id")

    root_exclusions = {"README.md", "manifest.json"}
    actual_files = inventory - root_exclusions
    if actual_files != seen_paths:
        missing = sorted(actual_files - seen_paths)
        extra = sorted(seen_paths - actual_files)
        errors.append(f"manifest.json: coverage mismatch (undeclared={missing}, missing={extra})")


def _verify_pinned_asset_digests(canonical_files: Mapping[str, bytes], errors: list[str]) -> None:
    """Verify v1 assets without trusting checksums supplied by manifest.json."""

    for relative, expected_digest in _EXPECTED_ASSET_DIGESTS.items():
        data = canonical_files.get(relative)
        if data is not None and _sha256(data) != expected_digest:
            errors.append(f"{relative}: differs from pinned {KIT_VERSION} asset digest")


def _compare_contract(
    observed: object,
    expected: object,
    path: str,
    errors: list[str],
) -> None:
    """Recursively validate a versioned JSON value without permissive gaps."""

    if type(observed) is not type(expected):
        errors.append(f"{path}: expected {type(expected).__name__}, got {type(observed).__name__}")
        return
    if isinstance(expected, dict):
        assert isinstance(observed, dict)
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        for key in missing:
            errors.append(f"{path}.{key}: required versioned token is missing")
        for key in extra:
            errors.append(f"{path}.{key}: unknown key is not part of the versioned contract")
        for key in expected.keys() & observed.keys():
            _compare_contract(observed[key], expected[key], f"{path}.{key}", errors)
        return
    if isinstance(expected, list):
        assert isinstance(observed, list)
        if len(observed) != len(expected):
            errors.append(f"{path}: expected {len(expected)} items, got {len(observed)}")
        for index, (observed_item, expected_item) in enumerate(zip(observed, expected)):
            _compare_contract(observed_item, expected_item, f"{path}[{index}]", errors)
        return
    if observed != expected:
        errors.append(f"{path}: differs from the pinned {KIT_VERSION} contract")


def _verify_tokens(tokens: dict[str, Any], errors: list[str]) -> None:
    _compare_contract(tokens, _EXPECTED_TOKENS, "tokens.json", errors)


def _verify_provenance(provenance: dict[str, Any], errors: list[str]) -> None:
    source = provenance.get("source")
    if not isinstance(source, dict):
        errors.append("provenance.json: source must be an object")
        return
    if source.get("repository") != "https://github.com/BlackhatShiftey/Cantlicle":
        errors.append("provenance.json: source repository is not the audited Canticle repository")
    if source.get("ref") != "origin/main" or source.get("commit") != SOURCE_COMMIT:
        errors.append("provenance.json: source ref or commit differs from the audited source")
    expected_blobs = {
        "index.html": "f39bf25e8e0e97fda96ae6e8c64bafacfb95bb12",
        "styles.css": "9d24e4640574c30b7956d334757bb53b5120bac0",
        "favicon.svg": "0760cdcbe0e6b0c6a0594bfd236f28ac811927c5",
    }
    if source.get("blobs") != expected_blobs:
        errors.append("provenance.json: source blob IDs differ from origin/main at the pinned commit")

    excerpts = provenance.get("source_excerpts")
    observed: dict[tuple[object, object], object] = {}
    if isinstance(excerpts, list):
        for excerpt in excerpts:
            if isinstance(excerpt, dict):
                observed[(excerpt.get("path"), excerpt.get("lines"))] = excerpt.get("sha256")
    if observed != _EXPECTED_SOURCE_EXCERPTS:
        errors.append("provenance.json: source excerpt hashes or line ranges differ from the audit")


def _valid_svg_attribute_value(attribute: str, value: str) -> bool:
    """Accept only literal, self-contained values used by the static marks."""

    if attribute in {
        "x",
        "y",
        "width",
        "height",
        "rx",
        "stroke-width",
        "font-size",
        "letter-spacing",
    }:
        return _SVG_NUMBER_RE.fullmatch(value) is not None
    if attribute in {"fill", "stroke"}:
        return _SVG_COLOR_RE.fullmatch(value) is not None
    if attribute == "viewBox":
        return _SVG_VIEWBOX_RE.fullmatch(value) is not None
    if attribute == "id":
        return _SVG_ID_RE.fullmatch(value) is not None
    if attribute == "aria-labelledby":
        return _SVG_IDREFS_RE.fullmatch(value) is not None
    if attribute == "role":
        return value == "img"
    if attribute == "data-brand-kit":
        return value == f"canticle-seam@{KIT_VERSION}"
    if attribute == "data-motion":
        return value == "rgb-cycle cursor-blink"
    if attribute == "font-family":
        return value == _SVG_FONT_FAMILY
    if attribute == "font-weight":
        return value == "700"
    return False


def _verify_svg(
    relative: str,
    data: bytes,
    expected_label: str,
    expected_title_id: str,
    expected_desc_id: str,
    errors: list[str],
) -> None:
    name = PurePosixPath(relative).name
    try:
        source = data.decode("utf-8")
    except UnicodeError as exc:
        errors.append(f"{name}: cannot read UTF-8 SVG: {exc}")
        return

    # XML processing instructions can attach stylesheets or invoke consumer-
    # specific behavior before the SVG element is examined.  Versioned marks do
    # not need an XML declaration, stylesheet PI, doctype, or entity expansion.
    forbidden_xml_prelude = False
    if "<?" in source:
        errors.append(f"{name}: XML processing instructions are forbidden")
        forbidden_xml_prelude = True
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", source, re.IGNORECASE):
        errors.append(f"{name}: XML doctypes and entity declarations are forbidden")
        forbidden_xml_prelude = True
    if forbidden_xml_prelude:
        return

    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError as exc:
        errors.append(f"{name}: invalid UTF-8 SVG: {exc}")
        return
    if root.tag != f"{{{_SVG_NAMESPACE}}}svg":
        errors.append(f"{name}: root element must be an SVG")
    if not root.get("viewBox"):
        errors.append(f"{name}: viewBox is required")
    if root.get("role") != "img":
        errors.append(f"{name}: accessible image role is required")
    if root.get("data-brand-kit") != f"canticle-seam@{KIT_VERSION}":
        errors.append(f"{name}: data-brand-kit must identify v{KIT_VERSION}")

    expected_refs = [expected_title_id, expected_desc_id]
    observed_refs = (root.get("aria-labelledby") or "").split()
    if observed_refs != expected_refs:
        errors.append(f"{name}: aria-labelledby must reference the asset-specific title and description")

    allowed_elements = set(_SVG_ALLOWED_ATTRIBUTES)
    ids: dict[str, list[ElementTree.Element]] = {}
    for element in root.iter():
        if not isinstance(element.tag, str):
            errors.append(f"{name}: XML processing instructions are forbidden")
            continue
        if not element.tag.startswith(f"{{{_SVG_NAMESPACE}}}"):
            errors.append(f"{name}: foreign XML namespaces are forbidden")
        local_tag = element.tag.rsplit("}", 1)[-1]
        if local_tag not in allowed_elements:
            errors.append(f"{name}: unsupported active or external element <{local_tag}>")

        element_id = element.get("id")
        if element_id:
            ids.setdefault(element_id, []).append(element)
        for attribute, value in element.attrib.items():
            local_attribute = attribute.rsplit("}", 1)[-1]
            normalized_attribute = local_attribute.lower()
            if attribute.startswith("{"):
                errors.append(f"{name}: namespaced attribute {local_attribute} is forbidden")
            if normalized_attribute.startswith("on"):
                errors.append(f"{name}: event-handler attribute {normalized_attribute} is forbidden")
            if normalized_attribute in {"href", "src"}:
                errors.append(f"{name}: resource reference attribute {normalized_attribute} is forbidden")
            if normalized_attribute == "style":
                errors.append(f"{name}: inline style attributes are forbidden")
            if re.search(r"url\s*\(", value, re.IGNORECASE) or "@import" in value.lower():
                errors.append(f"{name}: CSS URL or import resource is forbidden")
            if local_attribute not in _SVG_ALLOWED_ATTRIBUTES.get(local_tag, set()):
                errors.append(f"{name}: attribute {local_attribute} is not allowed on <{local_tag}>")
            elif not _valid_svg_attribute_value(local_attribute, value):
                errors.append(f"{name}: attribute {local_attribute} has an invalid static value")

    if re.search(r"url\s*\(", source, re.IGNORECASE) or re.search(r"@import\b", source, re.IGNORECASE):
        errors.append(f"{name}: CSS URL or import resource is forbidden")

    duplicate_ids = sorted(element_id for element_id, elements in ids.items() if len(elements) != 1)
    if duplicate_ids:
        errors.append(f"{name}: duplicate accessibility IDs are forbidden: {duplicate_ids}")

    accessible_elements: dict[str, tuple[str, str]] = {}
    for reference, expected_tag in (
        (expected_title_id, "title"),
        (expected_desc_id, "desc"),
    ):
        referenced = ids.get(reference, [])
        if len(referenced) != 1:
            errors.append(f"{name}: aria-labelledby reference {reference} must resolve once")
            continue
        element = referenced[0]
        local_tag = element.tag.rsplit("}", 1)[-1]
        content = " ".join("".join(element.itertext()).split())
        if local_tag != expected_tag:
            errors.append(f"{name}: {reference} must identify a <{expected_tag}> element")
        if not content:
            errors.append(f"{name}: referenced <{expected_tag}> text must be nonempty")
        accessible_elements[expected_tag] = (reference, content)

    title_content = accessible_elements.get("title", ("", ""))[1]
    desc_content = accessible_elements.get("desc", ("", ""))[1]
    if title_content and title_content != expected_label:
        errors.append(f"{name}: accessible title must be {expected_label}")
    if desc_content and expected_label not in desc_content:
        errors.append(f"{name}: accessible description must name {expected_label}")

    text = "".join(root.itertext())
    if "❯" not in text or expected_label not in text:
        errors.append(f"{name}: prompt glyph or {expected_label} label is missing")
    for required_color in ("#0a0b0a", "#ff6090", "#9ece6a"):
        if required_color not in source:
            errors.append(f"{name}: missing canonical first-frame color {required_color}")


def _verify_terminal_assets(canonical_files: Mapping[str, bytes], errors: list[str]) -> None:
    for relative, expected in _EXPECTED_TERMINAL.items():
        data = canonical_files.get(relative)
        if data is None:
            continue
        try:
            observed = data.decode("utf-8")
        except UnicodeError as exc:
            errors.append(f"{relative}: cannot read UTF-8 terminal asset: {exc}")
            continue
        if observed != expected:
            errors.append(f"{relative}: terminal lockup differs from the canonical cell grid")
        if any(ord(character) < 32 and character not in "\n\t" for character in observed):
            errors.append(f"{relative}: terminal lockup contains control characters")


def verify_kit(kit_root: Path | str = KIT_ROOT) -> list[str]:
    """Return a sorted list of brand-kit contract violations."""

    root = Path(kit_root)
    errors: list[str] = []
    if not _verify_kit_root(root, errors):
        return sorted(set(errors))

    inventory = _inventory_regular_files(root, errors)
    canonical_paths = {
        "README.md",
        "manifest.json",
        *_EXPECTED_ASSET_DIGESTS,
    }
    canonical_files: dict[str, bytes] = {}
    for relative in sorted(canonical_paths):
        data = _read_regular_file(root, relative, errors)
        if data is not None:
            canonical_files[relative] = data

    manifest_data = canonical_files.get("manifest.json")
    tokens_data = canonical_files.get("tokens.json")
    provenance_data = canonical_files.get("provenance.json")
    manifest = _read_json("manifest.json", manifest_data, errors) if manifest_data is not None else None
    tokens = _read_json("tokens.json", tokens_data, errors) if tokens_data is not None else None
    provenance = _read_json("provenance.json", provenance_data, errors) if provenance_data is not None else None

    if manifest is not None:
        _verify_manifest(manifest, canonical_files, inventory, errors)
    if tokens is not None:
        _verify_tokens(tokens, errors)
    if provenance is not None:
        _verify_provenance(provenance, errors)

    # This check intentionally does not consume manifest.json.  The manifest is
    # useful to downstream consumers but cannot be its own trust anchor.
    _verify_pinned_asset_digests(canonical_files, errors)

    for relative, (label, title_id, desc_id) in _EXPECTED_SVG_ACCESSIBILITY.items():
        data = canonical_files.get(relative)
        if data is not None:
            _verify_svg(relative, data, label, title_id, desc_id, errors)
    _verify_terminal_assets(canonical_files, errors)
    return sorted(set(errors))


def main() -> int:
    errors = verify_kit()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"brand kit verified: {len(_EXPECTED_ASSETS)} canonical assets at {KIT_ROOT}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the public function
    raise SystemExit(main())
