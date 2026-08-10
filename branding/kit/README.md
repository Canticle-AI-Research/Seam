# Canticle / SEAM brand kit

This directory is the canonical, source-controlled visual contract for the
Canticle company identity and the SEAM product identity. Both identities share
one signature: a terminal prompt and live cursor inside a dark bordered square.
The word beside that mark establishes the hierarchy:

- **Canticle** is the company lockup.
- **SEAM** is the product lockup.

Do not replace `Canticle` with `SEAM` when a surface is meant to show the
company identity. A SEAM surface may place the company lockup first and show
`SEAM` separately as its product or runtime context.

## Contents

- `tokens.json` — exact Canticle palette, font stacks, lockup geometry, and
  motion timing, plus semantic aliases for consumers.
- `marks/*.svg` — accessible, static first-frame company and product lockups.
- `terminal/*.txt` — cell-grid translations for terminal surfaces.
- `provenance.json` — the pinned Canticle source commit, blob IDs, source line
  ranges, and audited excerpt hashes.
- `manifest.json` — stable asset IDs, media types, and content hashes.

The SVGs are static and self-contained: they contain no processing
instructions, event handlers, scripts, style blocks, CSS URLs, or relative or
external resources. Capable consumers may adopt the applicable motion tokens
from `tokens.json`; static exports remain predictable, and reduced-motion
consumers can hold the first frame with the cursor visible.
Font binaries are not bundled. Consumers should provide the recorded font
stacks or create reviewed outlined exports when font-independent artwork is
required.

## Consumer mapping

The signature maps to terminal cells without inventing a second mark:

```text
╭────╮
│ ❯ █│ Canticle
╰────╯
```

Apply `color.semantic.brand_prompt` to `❯`. The border, cursor, and word begin
at `color.semantic.brand_live`. Capable animated consumers may cycle those
targets with `motion.rgb_cycle`; RGB cycling is an optional adoption, not a
claim about every consumer. The cursor may follow `motion.cursor_blink`. Keep
`motion.reduced_motion` as the no-animation fallback.

The current SEAM TUI adopts the exact static first-frame palette and semantic
mapping, cursor blink, product type-on, and reduced/off behavior. It does not
currently implement `motion.rgb_cycle`.

On launch, a SEAM product surface may reveal the product name with
`motion.product_type_on`: advance through the recorded prefix frames every
120 ms, hold `SEAM` for 360 ms, and run once. Reduced-motion consumers render
the recorded final frame immediately.

The root `branding/` directory contains older SEAM concepts and references.
They are not inputs to this kit. Likewise, Canticle's existing `favicon.svg`
is a separate historical terminal-window glyph, not the website's current
top-left lockup.

## Verify

Run from the repository root:

```bash
python -m tools.branding.verify_brand_kit
```

The verifier checks the pinned source contract, manifest coverage and hashes,
independently pinned version digests, safe SVG structure, and exact terminal
lockups. Any intentional identity change must issue a reviewed kit version and
update the tokens, assets, provenance, manifest hashes, verifier contract, and
tests together.
