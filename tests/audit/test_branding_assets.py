"""Regressions for the brand asset toolkit.

Two classes of defect are pinned here, both found while building it:

* ``color.semantic.*`` entries hold token *paths*, not literals. Flattening
  without resolving them emits CSS like ``--semantic-canvas: color.base.bg``,
  which renders as nothing and fails silently.
* Pillow's ICO writer downscales from the base image, so passing the smallest
  render as base clamps every requested size down to it. The first cut produced
  a 337-byte 16x16-only favicon that looked like a success.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.branding.assets import (
    BrandError,
    _flatten_colors,
    _split_frontmatter,
    check_fonts,
    document_shell,
    html_shell,
    load_tokens,
    render_ico,
    render_pdf,
    render_png,
    render_report,
    tokens_to_css,
)

MARK = Path(__file__).resolve().parents[2] / "branding" / "kit" / "marks" / "seam-product-lockup.svg"


@pytest.fixture(scope="module")
def tokens():
    return load_tokens()


def test_semantic_aliases_resolve_to_literal_colors(tokens):
    assert tokens.color("semantic.canvas") == tokens.color("base.bg")
    assert tokens.color("semantic.brand_live") == tokens.color("accent.pink")
    for name, value in tokens.colors.items():
        assert not value.startswith("color."), f"{name} left unresolved as {value}"


def test_unresolvable_alias_is_dropped_not_passed_through():
    flat = _flatten_colors({
        "base": {"bg": "#111111"},
        "semantic": {"good": "color.base.bg", "bad": "color.base.nope"},
    })
    assert flat["semantic.good"] == "#111111"
    assert "semantic.bad" not in flat


def test_unknown_color_token_raises(tokens):
    with pytest.raises(BrandError):
        tokens.color("accent.chartreuse")


def test_css_emits_every_color_and_font(tokens):
    css = tokens_to_css(tokens)
    assert "--accent-pink: #ff6090;" in css
    assert "--font-mono:" in css and "--font-sans:" in css
    assert "color." not in css.split(":root")[1], "an unresolved alias leaked into CSS"


def test_html_shell_carries_brand_ground(tokens):
    doc = html_shell("<p>x</p>", tokens, width=800, height=400)
    assert "--base-bg" in doc and "width:800px" in doc
    assert doc.startswith("<!doctype html>")


def test_font_stack_quotes_multiword_families(tokens):
    assert "'Fira Code'" in tokens.font_stack("mono")
    with pytest.raises(BrandError):
        tokens.font_stack("cursive")


def test_check_fonts_ignores_fallbacks(tokens):
    """Only the first face in a stack is the brand face; the rest are fallbacks."""
    status = check_fonts(tokens)
    if not status:
        pytest.fail("fc-match unavailable; the toolkit cannot verify brand faces")
    assert "Cascadia Mono" not in status, "a fallback face was treated as required"
    assert "Fira Code" in status


def test_render_png_produces_a_real_image(tmp_path, tokens):
    from PIL import Image

    out = render_png(MARK, tmp_path / "m.png", width=400, height=100)
    im = Image.open(out)
    assert im.format == "PNG" and im.size == (400, 100)
    assert im.getbbox() is not None, "rendered a blank canvas"


def test_render_ico_contains_every_requested_size(tmp_path):
    from PIL import Image

    out = render_ico(MARK, tmp_path / "f.ico", sizes=(16, 32, 64))
    got = sorted(Image.open(out).info.get("sizes", []))
    assert got == [(16, 16), (32, 32), (64, 64)]


def test_render_pdf_writes_a_pdf(tmp_path, tokens):
    src = tmp_path / "r.html"
    src.write_text(html_shell("<h1>Report</h1>", tokens, width=816, height=1056))
    out = render_pdf(src, tmp_path / "r.pdf")
    assert out.read_bytes().startswith(b"%PDF-")


def test_missing_source_raises(tmp_path):
    with pytest.raises(BrandError):
        render_png(tmp_path / "nope.svg", tmp_path / "o.png")


REPORT_MD = """---
schema: seam-audit/v1
date: 2026-08-15
---

# Deep audit

## Findings

| # | Finding | Sev |
|---|---|---|
| 1 | a real defect | HIGH |

Some prose with `inline code`.

```python
x = 1
```
"""


def test_frontmatter_is_lifted_out_not_rendered_as_a_rule():
    meta, body = _split_frontmatter(REPORT_MD)
    assert meta == {"schema": "seam-audit/v1", "date": "2026-08-15"}
    assert body.lstrip().startswith("# Deep audit")


def test_frontmatter_split_leaves_plain_documents_untouched():
    meta, body = _split_frontmatter("# Title\n\ntext\n")
    assert meta == {}
    assert body == "# Title\n\ntext\n"


def test_document_shell_flows_instead_of_clipping(tokens):
    """html_shell pins height and hides overflow; a report must not."""
    doc = document_shell("<p>x</p>", tokens, title="T")
    # Scope to the layout rules: the :root block legitimately carries a
    # --lockup-square-height design token.
    body_rules = doc.split("</style>")[0].split(":root {")[1].split("}", 1)[1]
    assert "overflow:hidden" not in body_rules
    assert "height:" not in body_rules.replace("line-height", "")
    assert "print-color-adjust: exact" in body_rules
    assert doc.count("<title>T</title>") == 1


def test_document_shell_uses_semantic_tokens_not_raw_hexes(tokens):
    doc = document_shell("<p>x</p>", tokens, title="T")
    style = doc.split("</style>")[0]
    body_rules = style.split(":root {")[1].split("}", 1)[1]
    assert "#" not in body_rules, "a hardcoded hex bypasses the token contract"
    assert "var(--semantic-canvas)" in body_rules


def test_render_report_html_renders_tables(tmp_path, tokens):
    """The commonmark preset drops tables; a findings table is the report."""
    src = tmp_path / "audit.md"
    src.write_text(REPORT_MD)
    out = render_report(src, tmp_path / "audit.html", tokens)
    html = out.read_text()
    assert "<table>" in html and "<th>Sev</th>" in html
    assert "<td>a real defect</td>" in html
    assert "schema: seam-audit/v1" in html
    assert "<pre>" in html


def test_render_report_titles_from_the_first_heading(tmp_path, tokens):
    src = tmp_path / "audit.md"
    src.write_text(REPORT_MD)
    out = render_report(src, tmp_path / "audit.html", tokens)
    assert "<title>Deep audit</title>" in out.read_text()


def test_render_report_writes_a_pdf(tmp_path, tokens):
    src = tmp_path / "audit.md"
    src.write_text(REPORT_MD)
    out = render_report(src, tmp_path / "audit.pdf", tokens)
    assert out.read_bytes().startswith(b"%PDF-")
    assert out.stat().st_size > 1000


def test_render_report_rejects_an_unsupported_extension(tmp_path, tokens):
    src = tmp_path / "audit.md"
    src.write_text(REPORT_MD)
    with pytest.raises(BrandError, match="must be .html or .pdf"):
        render_report(src, tmp_path / "audit.docx", tokens)
