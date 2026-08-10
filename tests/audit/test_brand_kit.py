from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from tools.branding.verify_brand_kit import (
    KIT_ROOT,
    SOURCE_COMMIT,
    _is_reparse_point,
    verify_kit,
)


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_kit(tmp_path: Path) -> Path:
    copy = tmp_path / "kit"
    shutil.copytree(KIT_ROOT, copy)
    return copy


def _refresh_manifest_digest(root: Path, relative: str) -> None:
    """Model an attacker updating the mutable manifest after changing an asset."""

    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    for asset in manifest["assets"]:
        if asset["path"] == relative:
            asset["sha256"] = digest
            break
    else:  # pragma: no cover - helper is only called with canonical assets
        raise AssertionError(f"missing manifest asset: {relative}")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _tcss_block_declarations(theme: str, selector: str) -> dict[str, str]:
    match = re.search(
        rf"(?ms)^{re.escape(selector)}\s*\{{(?P<body>.*?)^\}}",
        theme,
    )
    assert match is not None, selector
    return dict(re.findall(r"(?m)^\s+([A-Za-z][A-Za-z0-9-]*):\s*([^;]+);$", match.group("body")))


def test_canonical_brand_kit_verifies() -> None:
    assert verify_kit() == []


def test_hashed_kit_text_extensions_are_forced_to_lf() -> None:
    manifest = _json(KIT_ROOT / "manifest.json")
    asset_paths = [f"branding/kit/{asset['path']}" for asset in manifest["assets"]]
    checked_paths = ["branding/kit/manifest.json", *asset_paths]

    result = subprocess.run(
        ["git", "check-attr", "eol", "--", *checked_paths],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        capture_output=True,
        text=True,
    )

    observed = result.stdout.splitlines()
    assert len(observed) == len(checked_paths)
    assert all(line.endswith(": eol: lf") for line in observed)


def test_verifier_rejects_asset_tampering(tmp_path: Path) -> None:
    copy = _copy_kit(tmp_path)
    terminal = copy / "terminal" / "canticle-company-lockup.txt"
    terminal.write_text(terminal.read_text(encoding="utf-8").replace("Canticle", "Other"), encoding="utf-8")
    _refresh_manifest_digest(copy, "terminal/canticle-company-lockup.txt")

    errors = verify_kit(copy)

    assert "terminal/canticle-company-lockup.txt: differs from pinned 1.0.0 asset digest" in errors
    assert any("canonical cell grid" in error for error in errors)


def test_verifier_rejects_safe_geometry_rehash_against_independent_pin(
    tmp_path: Path,
) -> None:
    copy = _copy_kit(tmp_path)
    relative = "marks/seam-product-lockup.svg"
    svg = copy / relative
    svg.write_text(
        svg.read_text(encoding="utf-8").replace(
            '<rect x="1" y="9"',
            '<rect x="2" y="9"',
            1,
        ),
        encoding="utf-8",
    )
    _refresh_manifest_digest(copy, relative)

    errors = verify_kit(copy)

    assert f"{relative}: differs from pinned 1.0.0 asset digest" in errors
    assert f"{relative}: SHA-256 mismatch" not in errors
    assert not any("invalid static value" in error for error in errors)


def test_verifier_rejects_out_of_root_asset_symlink_without_following(
    tmp_path: Path,
) -> None:
    copy = _copy_kit(tmp_path)
    relative = "terminal/seam-product-lockup.txt"
    outside = tmp_path / "outside-lockup.txt"
    outside.write_bytes((KIT_ROOT / relative).read_bytes())
    target = copy / relative
    target.unlink()
    target.symlink_to(outside)

    errors = verify_kit(copy)

    assert f"{relative}: symlinks are forbidden" in errors


def test_verifier_rejects_self_loop_asset_symlink_without_resolving(
    tmp_path: Path,
) -> None:
    copy = _copy_kit(tmp_path)
    relative = "marks/seam-product-lockup.svg"
    target = copy / relative
    target.unlink()
    target.symlink_to(target.name)

    errors = verify_kit(copy)

    assert f"{relative}: symlinks are forbidden" in errors


def test_verifier_rejects_windows_junction_or_reparse_escape(tmp_path: Path) -> None:
    """Exercise a real NTFS junction on Windows and its classifier elsewhere."""
    if os.name != "nt":
        simulated = SimpleNamespace(
            st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
        )
        assert _is_reparse_point(tmp_path, simulated)
        return

    copy = _copy_kit(tmp_path)
    outside = tmp_path / "outside-kit"
    outside.mkdir()
    (outside / "payload.txt").write_text("outside\n", encoding="utf-8")
    junction = copy / "junction-escape"
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        check=True,
        capture_output=True,
        text=True,
    )

    errors = verify_kit(copy)

    assert "junction-escape: filesystem reparse points are forbidden" in errors


def test_verifier_rejects_non_regular_canonical_asset_before_read(
    tmp_path: Path,
) -> None:
    copy = _copy_kit(tmp_path)
    relative = "terminal/seam-product-lockup.txt"
    target = copy / relative
    target.unlink()
    target.mkdir()

    errors = verify_kit(copy)

    assert f"{relative}: canonical path component must be a regular file" in errors


def test_verifier_rejects_svg_event_handlers_after_manifest_rehash(tmp_path: Path) -> None:
    copy = _copy_kit(tmp_path)
    relative = "marks/seam-product-lockup.svg"
    svg = copy / relative
    svg.write_text(
        svg.read_text(encoding="utf-8").replace("<svg ", '<svg onload="alert(1)" ', 1),
        encoding="utf-8",
    )
    _refresh_manifest_digest(copy, relative)

    errors = verify_kit(copy)

    assert any("event-handler attribute onload is forbidden" in error for error in errors)


def test_verifier_rejects_svg_style_and_css_urls_after_manifest_rehash(
    tmp_path: Path,
) -> None:
    copy = _copy_kit(tmp_path)
    relative = "marks/seam-product-lockup.svg"
    svg = copy / relative
    svg.write_text(
        svg.read_text(encoding="utf-8").replace(
            '  <rect x="1"',
            '  <style>rect { fill: url("assets/palette.svg#ink"); }</style>\n  <rect x="1"',
            1,
        ),
        encoding="utf-8",
    )
    _refresh_manifest_digest(copy, relative)

    errors = verify_kit(copy)

    assert any("unsupported active or external element <style>" in error for error in errors)
    assert any("CSS URL or import resource is forbidden" in error for error in errors)


@pytest.mark.parametrize(
    "obfuscated_resource",
    [r"u\72l(../payload.svg)", "u/**/rl(../payload.svg)"],
)
def test_verifier_rejects_obfuscated_css_resources_with_closed_value_grammar(
    tmp_path: Path,
    obfuscated_resource: str,
) -> None:
    copy = _copy_kit(tmp_path)
    relative = "marks/seam-product-lockup.svg"
    svg = copy / relative
    svg.write_text(
        svg.read_text(encoding="utf-8").replace(
            'fill="#0a0b0a"',
            f'fill="{obfuscated_resource}"',
            1,
        ),
        encoding="utf-8",
    )
    _refresh_manifest_digest(copy, relative)

    errors = verify_kit(copy)

    assert any("attribute fill has an invalid static value" in error for error in errors)


def test_verifier_rejects_svg_processing_instructions_after_manifest_rehash(
    tmp_path: Path,
) -> None:
    copy = _copy_kit(tmp_path)
    relative = "marks/seam-product-lockup.svg"
    svg = copy / relative
    svg.write_text(
        '<?xml-stylesheet href="relative-theme.css"?>\n' + svg.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _refresh_manifest_digest(copy, relative)

    errors = verify_kit(copy)

    assert any("XML processing instructions are forbidden" in error for error in errors)


def test_verifier_rejects_svg_relative_resources_after_manifest_rehash(
    tmp_path: Path,
) -> None:
    copy = _copy_kit(tmp_path)
    relative = "marks/seam-product-lockup.svg"
    svg = copy / relative
    svg.write_text(
        svg.read_text(encoding="utf-8").replace("</svg>", '  <image href="../payload.svg"/>\n</svg>', 1),
        encoding="utf-8",
    )
    _refresh_manifest_digest(copy, relative)

    errors = verify_kit(copy)

    assert any("resource reference attribute href is forbidden" in error for error in errors)


@pytest.mark.parametrize(
    "token_path",
    [
        ("color", "semantic", "brand_live"),
        ("typography", "roles", "body"),
        ("lockup", "cursor_size", "width"),
        ("motion", "cursor_blink", "keyframes"),
        ("motion", "rgb_cycle", "targets"),
        ("motion", "rgb_cycle", "effects", "word_glow"),
        ("motion", "reduced_motion", "cursor_visible"),
    ],
)
def test_verifier_rejects_deletion_from_complete_token_schema(
    tmp_path: Path,
    token_path: tuple[str, ...],
) -> None:
    copy = _copy_kit(tmp_path)
    tokens_path = copy / "tokens.json"
    tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
    parent = tokens
    for key in token_path[:-1]:
        parent = parent[key]
    del parent[token_path[-1]]
    tokens_path.write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8")
    _refresh_manifest_digest(copy, "tokens.json")

    errors = verify_kit(copy)

    dotted_path = ".".join(("tokens.json", *token_path))
    assert f"{dotted_path}: required versioned token is missing" in errors


@pytest.mark.parametrize("nested_name", ["README.md", "manifest.json"])
def test_manifest_root_exclusions_do_not_hide_nested_assets(
    tmp_path: Path,
    nested_name: str,
) -> None:
    copy = _copy_kit(tmp_path)
    nested = copy / "marks" / nested_name
    nested.write_text("undeclared brand payload\n", encoding="utf-8")

    errors = verify_kit(copy)

    relative = nested.relative_to(copy).as_posix()
    assert any(relative in error and "coverage mismatch" in error for error in errors)


def test_readme_uses_real_semantic_token_paths() -> None:
    readme = (KIT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "color.semantic.brand_prompt" in readme
    assert "color.semantic.brand_live" in readme
    assert "color.semantic.brand.prompt" not in readme
    assert "color.semantic.brand.live" not in readme
    assert "Capable animated consumers may cycle" in readme
    assert "It does not\ncurrently implement `motion.rgb_cycle`" in readme


def test_tokens_preserve_the_pinned_canticle_contract() -> None:
    tokens = _json(KIT_ROOT / "tokens.json")
    assert tokens["source_commit"] == SOURCE_COMMIT

    color = tokens["color"]
    assert color["base"] == {
        "bg": "#1a1b26",
        "bg_deep": "#16161e",
        "bg_panel": "#1f2028",
        "bg_sunk": "#13131a",
        "surface": "#24253a",
        "brand_square": "#0a0b0a",
    }
    assert color["accent"]["pink"] == "#ff6090"
    assert color["accent"]["mint"] == "#9ece6a"
    assert color["text_chrome"]["text"] == "#c0caf5"

    typography = tokens["typography"]
    assert typography["families"]["mono"] == [
        "Fira Code",
        "JetBrains Mono",
        "Cascadia Mono",
        "monospace",
    ]
    assert typography["families"]["sans"] == ["Outfit", "system-ui", "sans-serif"]
    assert typography["families"]["accent"] == ["Press Start 2P", "monospace"]
    for role in typography["roles"].values():
        assert role["weight"] in typography["web_font_weights"][role["family"]]

    assert tokens["lockup"]["prompt"] == "❯"
    assert tokens["lockup"]["cursor"] == "█"
    assert tokens["motion"]["cursor_blink"]["duration_ms"] == 800
    assert tokens["motion"]["rgb_cycle"]["duration_ms"] == 8000
    assert [stop["offset_percent"] for stop in tokens["motion"]["rgb_cycle"]["stops"]] == [
        0,
        14,
        28,
        42,
        57,
        71,
        85,
        100,
    ]

    type_on = tokens["motion"]["product_type_on"]
    assert type_on == {
        "text": "SEAM",
        "frames": ["S", "SE", "SEA", "SEAM"],
        "interval_ms": 120,
        "final_hold_ms": 360,
        "iterations": 1,
        "reduced_motion_frame": "SEAM",
    }


def test_company_and_product_assets_keep_the_identity_hierarchy() -> None:
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    company_svg = ElementTree.parse(KIT_ROOT / "marks" / "canticle-company-lockup.svg")
    product_svg = ElementTree.parse(KIT_ROOT / "marks" / "seam-product-lockup.svg")

    company_words = [element.text for element in company_svg.findall("svg:text", namespace)]
    product_words = [element.text for element in product_svg.findall("svg:text", namespace)]
    assert company_words == ["❯", "Canticle"]
    assert product_words == ["❯", "SEAM"]

    accessibility = [
        (
            company_svg,
            "canticle-lockup-title",
            "canticle-lockup-desc",
            "Canticle",
        ),
        (product_svg, "seam-lockup-title", "seam-lockup-desc", "SEAM"),
    ]
    for document, title_id, desc_id, label in accessibility:
        root = document.getroot()
        assert root.get("aria-labelledby") == f"{title_id} {desc_id}"
        title = document.find(f"svg:title[@id='{title_id}']", namespace)
        desc = document.find(f"svg:desc[@id='{desc_id}']", namespace)
        assert title is not None and title.text == label
        assert desc is not None and desc.text and label in desc.text

    company_terminal = (KIT_ROOT / "terminal" / "canticle-company-lockup.txt").read_text(encoding="utf-8")
    product_terminal = (KIT_ROOT / "terminal" / "seam-product-lockup.txt").read_text(encoding="utf-8")
    assert "❯ █" in company_terminal and "Canticle" in company_terminal
    assert "❯ █" in product_terminal and "SEAM" in product_terminal
    assert "SEAM" not in company_terminal
    assert "Canticle" not in product_terminal


def test_verifier_rejects_empty_referenced_accessibility_text_after_rehash(
    tmp_path: Path,
) -> None:
    copy = _copy_kit(tmp_path)
    relative = "marks/seam-product-lockup.svg"
    svg = copy / relative
    svg.write_text(
        svg.read_text(encoding="utf-8").replace(
            "Terminal prompt and cursor in a bordered square followed by the SEAM product wordmark.",
            "",
        ),
        encoding="utf-8",
    )
    _refresh_manifest_digest(copy, relative)

    errors = verify_kit(copy)

    assert any("referenced <desc> text must be nonempty" in error for error in errors)


def test_verifier_rejects_unresolved_accessibility_reference_after_rehash(
    tmp_path: Path,
) -> None:
    copy = _copy_kit(tmp_path)
    relative = "marks/seam-product-lockup.svg"
    svg = copy / relative
    svg.write_text(
        svg.read_text(encoding="utf-8").replace(
            "seam-lockup-title seam-lockup-desc",
            "seam-lockup-title missing-lockup-desc",
        ),
        encoding="utf-8",
    )
    _refresh_manifest_digest(copy, relative)

    errors = verify_kit(copy)

    assert any("aria-labelledby must reference the asset-specific" in error for error in errors)


def test_provenance_pins_canticle_origin_main() -> None:
    provenance = _json(KIT_ROOT / "provenance.json")
    source = provenance["source"]
    assert source["ref"] == "origin/main"
    assert source["commit"] == SOURCE_COMMIT
    assert source["blobs"] == {
        "index.html": "f39bf25e8e0e97fda96ae6e8c64bafacfb95bb12",
        "styles.css": "9d24e4640574c30b7956d334757bb53b5120bac0",
        "favicon.svg": "0760cdcbe0e6b0c6a0594bfd236f28ac811927c5",
    }


def test_tui_consumer_matches_the_canonical_kit() -> None:
    """The first adopter must not become another almost-matching palette."""
    from seam_runtime.tui import brand

    tokens = _json(KIT_ROOT / "tokens.json")
    base = tokens["color"]["base"]
    accent = tokens["color"]["accent"]
    chrome = tokens["color"]["text_chrome"]
    type_on = tokens["motion"]["product_type_on"]

    assert brand.BG_DEEP == base["bg_deep"]
    assert brand.BG_PANEL == base["bg_panel"]
    assert brand.BRAND_SQUARE == base["brand_square"]
    assert brand.PINK == accent["pink"]
    assert brand.MAGENTA == accent["magenta"]
    assert brand.LAVENDER == accent["lavender"]
    assert brand.CYAN == accent["cyan"]
    assert brand.MINT == accent["mint"]
    assert brand.TEXT_MAIN == chrome["text"]
    assert brand.TEXT_DIM == chrome["text_dim"]
    assert brand.TEXT_MUTED == chrome["text_muted"]
    assert brand.PROMPT == tokens["lockup"]["prompt"]
    assert brand.CURSOR == tokens["lockup"]["cursor"]
    assert list(brand.STARTUP_WORD_FRAMES) == type_on["frames"]
    assert brand.STARTUP_FRAME_SECONDS * 1000 == type_on["interval_ms"]
    assert brand.STARTUP_HOLD_SECONDS * 1000 == type_on["final_hold_ms"]
    assert brand.CURSOR_BLINK_SECONDS * 1000 == tokens["motion"]["cursor_blink"]["duration_ms"]
    assert brand.CURSOR_TOGGLE_SECONDS == brand.CURSOR_BLINK_SECONDS / 2

    repo_root = Path(__file__).resolve().parents[2]
    theme = (repo_root / "seam_runtime" / "tui" / "theme.tcss").read_text(encoding="utf-8")
    expected_variables = {
        "$bg": base["bg"],
        "$bg-deep": base["bg_deep"],
        "$bg-panel": base["bg_panel"],
        "$bg-sunk": base["bg_sunk"],
        "$surface-alt": base["surface"],
        "$pink": accent["pink"],
        "$magenta": accent["magenta"],
        "$lavender": accent["lavender"],
        "$cyan": accent["cyan"],
        "$mint": accent["mint"],
        "$green": accent["green"],
        "$yellow": accent["yellow"],
        "$orange": accent["orange"],
        "$red": accent["red"],
        "$blue": accent["blue"],
        "$ice": accent["ice"],
        "$text-main": chrome["text"],
        "$text-dim": chrome["text_dim"],
        "$text-muted": chrome["text_muted"],
        "$edge": chrome["border"],
        "$edge-hi": chrome["border_hi"],
    }
    observed_variables = dict(re.findall(r"(?m)^(\$[A-Za-z][A-Za-z0-9-]*):\s*([^;]+);$", theme))
    assert observed_variables == expected_variables

    assert (
        _tcss_block_declarations(theme, "Screen").items()
        >= {
            "background": "$bg",
            "color": "$text-main",
        }.items()
    )
    assert (
        _tcss_block_declarations(theme, "#brand-bar").items()
        >= {
            "background": "$bg-deep",
            "border-bottom": "solid $edge",
        }.items()
    )
    assert (
        _tcss_block_declarations(theme, "#brand-symbol, #startup-symbol").items()
        >= {
            "border": "round $pink",
            "background": base["brand_square"],
        }.items()
    )
    assert _tcss_block_declarations(theme, "#brand-product")["color"] == "$pink"
    assert _tcss_block_declarations(theme, "#brand-context")["color"] == "$text-dim"
    assert _tcss_block_declarations(theme, "#brand-mode")["color"] == "$text-muted"
    assert _tcss_block_declarations(theme, "#brand-status")["color"] == "$green"
    assert _tcss_block_declarations(theme, "#startup-splash")["background"] == "$bg-deep"
    assert _tcss_block_declarations(theme, "#startup-word")["color"] == "$pink"
