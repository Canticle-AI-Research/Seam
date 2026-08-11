# Canticle Cosmic UI Kit

`canticle-cosmic-ui@1.0.0` is the reusable expression layer for Canticle and
SEAM surfaces. It turns the canonical terminal identity into a more playful
cosmic-arcade system: inflated panels, sticker shadows, bright orbit accents,
and small elastic interactions over the established Canticle palette.

This is original Canticle design work. It does not fork Bubble Tea, Bubbles,
Lip Gloss, or any Charm component source. Charm's tools remain optional
rendering targets; the visual contract lives here.

## Contract boundary

- [`../kit/`](../kit/README.md) remains the identity authority for names,
  colors, lockup geometry, source provenance, and logo assets.
- This directory owns component shape, spacing, effects, interaction states,
  and framework adapters.
- A consumer must use the exact `canticle-seam@1.0.0` dependency recorded in
  `tokens.json`. The verifier checks that dependency and its logo hashes.
- This kit does not change a running WebUI or TUI by existing in the repo.
  Surface adoption is a separate reviewed change.

## Signature

The memorable element is the **memory bubble**: a dark, rounded panel with a
bright edge, one glossy highlight, and a hard offset shadow. Small bubbles may
orbit it as decorative wayfinding. They never imply a graph relationship by
proximity; data visualizations must continue to draw only real, typed edges.

The design uses one expressive move—the inflated sticker silhouette—and keeps
type, data rows, and terminal chrome disciplined around it.

## Contents

- `tokens.json` — versioned, framework-neutral design tokens.
- `css/canticle-cosmic.css` — namespaced CSS components and motion policy.
- `preview/index.html` + `preview/preview.css` — responsive component gallery.
- `tailwind/theme.css` — Tailwind v4 `@theme` variable adapter.
- `textual/canticle-cosmic.tcss` — opt-in Textual class adapter.
- `go/canticlecosmic/theme.go` — Lip Gloss v2 palette and style constructors.
- `manifest.json` — exact file inventory and SHA-256 values.

## CSS and HTML

Load the stylesheet and place `cc-cosmic` on the owned application root:

```html
<link rel="stylesheet" href="canticle-cosmic.css">

<main class="cc-cosmic cc-sky">
  <section class="cc-bubble-card">
    <span class="cc-sticker">Memory</span>
    <h2 class="cc-bubble-title">Keep the meaning. Keep the trail.</h2>
    <button class="cc-button cc-button--primary">Remember this</button>
  </section>
</main>
```

All reusable selectors use the `cc-` prefix. The stylesheet does not reset the
host page globally, fetch fonts, or require JavaScript.

## Tailwind v4

Import `tailwind/theme.css` after Tailwind. It adds `canticle-*` colors,
`cosmic-*` radii and shadows, and Canticle font-family utilities without
replacing Tailwind's default theme:

```css
@import "tailwindcss";
@import "./branding/canticle-cosmic-kit/tailwind/theme.css";
```

## Textual

Copy or import the declarations from `textual/canticle-cosmic.tcss`, then add
the opt-in classes to widgets. The file intentionally does not target bare
`Screen`, `Button`, `DataTable`, or `Input` selectors, so it cannot silently
restyle an entire application.

## Go / Lip Gloss

Copy `go/canticlecosmic` into an existing Go module using Lip Gloss v2. The
adapter imports `charm.land/lipgloss/v2` and exposes a `Theme` with constructors
for panels, stickers, buttons, inputs, and selected table rows. Bubble Tea owns
state and updates; this package only renders Canticle styles.

## Motion and accessibility

- Keyboard focus always has a high-contrast indicator. Web CSS uses the
  double-ring focus token; terminal adapters use a strong orbit border.
- Controls maintain a 44 px web target floor.
- Animation is decorative and bounded. `prefers-reduced-motion: reduce`
  disables float, orbit, blink, and elastic transitions.
- `forced-colors: active` removes painted shadows and restores system colors.
- Status never depends on color alone; pair it with text or an icon.

## Preview and verification

From the repository root:

```bash
.venv/bin/python -m tools.branding.verify_cosmic_ui_kit
.venv/bin/python -m pytest tests/audit/test_cosmic_ui_kit.py -q
.venv/bin/python -m http.server 8787
```

Then open
`http://127.0.0.1:8787/branding/canticle-cosmic-kit/preview/`.

Any intentional contract change must bump the kit version and use the
verifier's explicit `--print-manifest` output to refresh the reviewed manifest.
The verifier never rewrites files.
