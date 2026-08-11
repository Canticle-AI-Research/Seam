from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.branding.verify_cosmic_ui_kit import (
    BASE_KIT_ROOT,
    BASE_TOKENS_SHA256,
    KIT_ID,
    KIT_ROOT,
    KIT_VERSION,
    build_manifest,
    render_manifest,
    verify_kit,
)


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_kit(tmp_path: Path) -> Path:
    copy = tmp_path / "canticle-cosmic-kit"
    shutil.copytree(KIT_ROOT, copy)
    return copy


def _refresh_manifest(root: Path) -> None:
    (root / "manifest.json").write_text(render_manifest(root), encoding="utf-8")


def test_canonical_cosmic_ui_kit_verifies() -> None:
    assert verify_kit() == []


def test_manifest_is_deterministic_and_complete() -> None:
    rendered = render_manifest()
    assert rendered == (KIT_ROOT / "manifest.json").read_text(encoding="utf-8")

    manifest = json.loads(rendered)
    assert manifest["kit_id"] == KIT_ID
    assert manifest["version"] == KIT_VERSION
    assert manifest["extends"] == "canticle-seam@1.0.0"
    paths = [row["path"] for row in manifest["files"]]
    assert paths == sorted(paths)
    assert len(paths) == 8


def test_tokens_inherit_every_canonical_color_without_a_second_palette() -> None:
    tokens = _json(KIT_ROOT / "tokens.json")
    base = _json(BASE_KIT_ROOT / "tokens.json")

    assert tokens["extends"]["tokens_sha256"] == BASE_TOKENS_SHA256
    assert hashlib.sha256((BASE_KIT_ROOT / "tokens.json").read_bytes()).hexdigest() == BASE_TOKENS_SHA256
    primitive = tokens["color"]["primitive"]
    assert primitive["void"] == base["color"]["base"]["bg_deep"]
    assert primitive["night"] == base["color"]["base"]["bg"]
    assert primitive["plasma"] == base["color"]["accent"]["pink"]
    assert primitive["orbit"] == base["color"]["accent"]["cyan"]
    assert primitive["mint"] == base["color"]["accent"]["mint"]
    assert primitive["ink"] == base["color"]["text_chrome"]["text"]


def test_tokens_pin_company_and_product_lockups() -> None:
    tokens = _json(KIT_ROOT / "tokens.json")
    assets = tokens["extends"]["assets"]

    for row in assets.values():
        relative = row["path"].removeprefix("../kit/")
        assert hashlib.sha256((BASE_KIT_ROOT / relative).read_bytes()).hexdigest() == row["sha256"]


def test_web_css_is_namespaced_and_has_accessibility_fallbacks() -> None:
    css = (KIT_ROOT / "css" / "canticle-cosmic.css").read_text(encoding="utf-8")

    assert ".cc-bubble-card" in css
    assert ".cc-button" in css
    assert ".cc-table" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (forced-colors: active)" in css
    assert "--cc-shadow-focus" in css
    assert re.search(r"\.cc-help\s*\{\s*color:\s*var\(--cc-ink-muted\);", css)
    assert not re.search(r"(?m)^:root\s*,?", css)
    assert '[data-canticle-theme="cosmic"]' not in css
    assert "@import" not in css
    assert not re.search(r"url\s*\(", css, re.IGNORECASE)


def test_preview_is_local_script_free_and_labels_decorative_orbit() -> None:
    html = (KIT_ROOT / "preview" / "index.html").read_text(encoding="utf-8")

    assert "<script" not in html.lower()
    assert 'src="../../kit/marks/canticle-company-lockup.svg"' in html
    assert "Decorative orbit · no graph relation implied" in html
    assert "cc-skip-link" in html
    assert 'id="kit-content"' in html
    assert "aria-selected" not in html


def test_tailwind_adapter_extends_v4_theme_without_resetting_defaults() -> None:
    theme = (KIT_ROOT / "tailwind" / "theme.css").read_text(encoding="utf-8")

    assert "@theme {" in theme
    assert "--*: initial" not in theme
    assert "--color-canticle-plasma: #ff6090;" in theme
    assert "--font-canticle-bubble:" in theme
    assert "--animate-cosmic-float:" in theme
    assert "@keyframes canticle-cosmic-float" in theme
    assert "@media (prefers-reduced-motion: reduce)" in theme
    assert "--animate-cosmic-float: none;" in theme


def test_textual_adapter_is_opt_in_instead_of_restyling_bare_widgets() -> None:
    theme = (KIT_ROOT / "textual" / "canticle-cosmic.tcss").read_text(encoding="utf-8")

    assert ".cc-cosmic-bubble" in theme
    assert ".cc-cosmic-button" in theme
    assert ".cc-cosmic-table" in theme
    assert not re.search(r"(?m)^(?:Screen|Button|Input|DataTable|OptionList)\s*\{", theme)


def test_go_adapter_targets_lip_gloss_v2_and_owns_no_bubble_tea_state() -> None:
    source = (KIT_ROOT / "go" / "canticlecosmic" / "theme.go").read_text(encoding="utf-8")

    assert '"charm.land/lipgloss/v2"' in source
    assert '"image/color"' in source
    assert "package canticlecosmic" in source
    assert "color.Color" in source
    assert "func (t Theme) Bubble() lipgloss.Style" in source
    assert "func (t Theme) PrimaryButton() lipgloss.Style" in source
    assert "charm.land/bubbletea" not in source


def test_kit_text_is_forced_to_lf_by_git_attributes() -> None:
    paths = [f"branding/canticle-cosmic-kit/{row['path']}" for row in build_manifest()["files"]]
    paths.append("branding/canticle-cosmic-kit/manifest.json")
    result = subprocess.run(
        ["git", "check-attr", "eol", "--", *paths],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        capture_output=True,
        text=True,
    )
    observed = result.stdout.splitlines()
    assert len(observed) == len(paths)
    assert all(line.endswith(": eol: lf") for line in observed)


def test_verifier_rejects_asset_tampering_even_with_refreshed_manifest(tmp_path: Path) -> None:
    copy = _copy_kit(tmp_path)
    css = copy / "css" / "canticle-cosmic.css"
    css.write_text(css.read_text(encoding="utf-8").replace("#ff6090", "#ffffff", 1), encoding="utf-8")
    _refresh_manifest(copy)

    errors = verify_kit(copy)

    assert f"manifest.json: differs from pinned {KIT_VERSION} contract" in errors


def test_verifier_rejects_color_drift_from_base_kit(tmp_path: Path) -> None:
    copy = _copy_kit(tmp_path)
    tokens_path = copy / "tokens.json"
    tokens = _json(tokens_path)
    tokens["color"]["primitive"]["plasma"] = "#ffffff"
    tokens_path.write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8")
    _refresh_manifest(copy)

    errors = verify_kit(copy)

    assert "tokens.json.color.primitive.plasma: must equal base token accent.pink" in errors


def test_verifier_rejects_external_preview_resources(tmp_path: Path) -> None:
    copy = _copy_kit(tmp_path)
    preview = copy / "preview" / "index.html"
    preview.write_text(
        preview.read_text(encoding="utf-8").replace(
            "</head>",
            '<script src="https://example.invalid/widget.js"></script></head>',
        ),
        encoding="utf-8",
    )
    _refresh_manifest(copy)

    errors = verify_kit(copy)

    assert "preview/index.html: scripts are forbidden" in errors
    assert any("external resource" in error for error in errors)


def test_verifier_rejects_css_imports(tmp_path: Path) -> None:
    copy = _copy_kit(tmp_path)
    css = copy / "css" / "canticle-cosmic.css"
    css.write_text('@import "https://example.invalid/theme.css";\n' + css.read_text(encoding="utf-8"), encoding="utf-8")
    _refresh_manifest(copy)

    errors = verify_kit(copy)

    assert "css/canticle-cosmic.css: imports and URL resources are forbidden" in errors


def test_verifier_rejects_tailwind_global_theme_reset(tmp_path: Path) -> None:
    copy = _copy_kit(tmp_path)
    theme = copy / "tailwind" / "theme.css"
    theme.write_text(theme.read_text(encoding="utf-8").replace("@theme {", "@theme {\n  --*: initial;", 1), encoding="utf-8")
    _refresh_manifest(copy)

    errors = verify_kit(copy)

    assert "tailwind/theme.css: must extend a Tailwind v4 theme without resetting it" in errors


def test_verifier_rejects_bare_textual_widget_selector(tmp_path: Path) -> None:
    copy = _copy_kit(tmp_path)
    theme = copy / "textual" / "canticle-cosmic.tcss"
    theme.write_text(theme.read_text(encoding="utf-8") + "\nButton { color: #ffffff; }\n", encoding="utf-8")
    _refresh_manifest(copy)

    errors = verify_kit(copy)

    assert "textual/canticle-cosmic.tcss: bare widget selectors are forbidden" in errors


def test_verifier_rejects_missing_component_adapter(tmp_path: Path) -> None:
    copy = _copy_kit(tmp_path)
    (copy / "preview" / "preview.css").unlink()

    errors = verify_kit(copy)

    assert any("kit inventory: exact file set required" in error for error in errors)
    assert any("coverage mismatch" in error for error in errors)


def test_verifier_reports_unsupported_inventory_extension_without_raising(tmp_path: Path) -> None:
    copy = _copy_kit(tmp_path)
    unexpected = copy / "unexpected.bin"
    unexpected.write_bytes(b"not part of the text kit")
    manifest_path = copy / "manifest.json"
    manifest = _json(manifest_path)
    files = manifest.get("files")
    assert isinstance(files, list)
    files.append(
        {
            "path": "unexpected.bin",
            "media_type": "application/octet-stream",
            "bytes": len(unexpected.read_bytes()),
            "sha256": hashlib.sha256(unexpected.read_bytes()).hexdigest(),
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    errors = verify_kit(copy)

    assert "unexpected.bin: unsupported kit file extension: unexpected.bin" in errors


def test_verifier_refuses_symlinked_kit_file_without_reopening_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copy = _copy_kit(tmp_path)
    target = copy / "tokens.json"
    target.unlink()
    target.symlink_to(BASE_KIT_ROOT / "tokens.json")
    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == target:
            raise AssertionError("verifier reopened a rejected tokens.json symlink")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    errors = verify_kit(copy)

    assert "tokens.json: links are forbidden" in errors


def test_verifier_does_not_reopen_rejected_adapter_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copy = _copy_kit(tmp_path)
    target = copy / "css" / "canticle-cosmic.css"
    target.unlink()
    target.symlink_to(KIT_ROOT / "css" / "canticle-cosmic.css")
    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == target:
            raise AssertionError("verifier reopened a rejected CSS adapter symlink")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    errors = verify_kit(copy)

    assert "css/canticle-cosmic.css: links are forbidden" in errors


def test_reduced_motion_contract_keeps_static_cursor_visible() -> None:
    tokens = _json(KIT_ROOT / "tokens.json")

    assert tokens["motion"]["reduced_motion"] == {
        "policy": "static-final-frame",
        "animated_distance_px": 0,
        "cursor_visible": True,
    }
    assert tokens["component"]["control_min_height_px"] == 44
