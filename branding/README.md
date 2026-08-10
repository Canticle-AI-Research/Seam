# Canticle / SEAM branding

The canonical reusable visual contract is [`branding/kit/`](kit/README.md).
It separates the company and product identities while sharing one signature:
the Canticle terminal-square prompt/cursor mark.

- **Canticle** is the company lockup.
- **SEAM** is the product lockup.
- `kit/tokens.json` is the source for palette, typography, geometry, and motion.
- `kit/marks/` contains static SVG exports.
- `kit/terminal/` contains cell-grid lockups.
- `kit/provenance.json` pins the audited Canticle source.

Verify the kit from the repository root:

```bash
python -m tools.branding.verify_brand_kit
python -m pytest tests/audit/test_brand_kit.py -q
```

The Textual TUI is the first consumer. Browser/WebUI adoption is intentionally
deferred until an operator-present surface design session; the kit does not by
itself authorize changing those surfaces.

## Historical concepts

The SVGs, screenshots, previews, and `assets/mature/` material elsewhere in
this directory are retained as design history. They are not current identity
inputs and must not be copied into a new surface without a fresh review:

- `seam-mark-retro.svg`, `seam-mark-join.svg`, `seam-mark-stack.svg`, and
  `seam-mark-terminal.svg`
- `seam-retro-preview.html` and `seam_terminal_preview.py`
- `retro-direction.md`, `screenshots/`, and `assets/mature/`

Those explorations used older phosphor, amber, blue, and glitch directions.
The kit supersedes them; they remain only so the design history is auditable.
