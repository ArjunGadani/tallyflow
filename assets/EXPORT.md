# Rendering the README visuals

Three steps: **populate data → capture screenshots → export framed assets.**

## 1. Populate the app (so shots look real & full)
Drag all 7 invoices from `realistic_invoices/` into the dashboard **Upload** box (multi-file). You'll get a rich, multi-currency dataset (USD/GBP/EUR/INR) across the views.

## 2. Capture screenshots (macOS Retina = already 2×)
Chrome at ~1440px width. `Cmd+Shift+4 → Space → click the window`. Save into `assets/screenshots/` with these exact names:

| File | Screen / state |
|---|---|
| `hero-invoices.png` | **Invoices** list — several rows, confidence rings, mixed currencies, statuses |
| `feat-timeline.png` | **Invoice detail → Processing flow** card (or an Upload result card) |
| `feat-detail.png` | **Invoice detail** — fields grid + confidence ring + line items + tax |
| `feat-charts.png` | **Overview** — category/vendor charts |
| `feat-activity.png` | **Activity** — the live feed card |
| `feat-review.png` | **Review queue** — a needs-review item + dead-letter row |

Tip: crop reasonably tight; the templates add the browser frame + padding.

## 3. Export the framed assets at 2×

**Option A — no install, pixel-exact (recommended):**
1. Open `assets/poster.html` in Chrome.
2. DevTools (`Cmd+Opt+I`) → in Elements, select the `<div class="poster">` node → right-click → **Capture node screenshot** → save as `assets/hero.png`.
3. Open `assets/features.html`; repeat for each `<div class="card" id="card-…">` → save as the matching `assets/feat-*.png` (`card-timeline` → `feat-timeline.png`, etc.).

(On a Retina Mac the capture is 2× automatically and pixel-exact to the frame.)

**Option B — one command (Playwright):**
```bash
cd assets && npm init -y && npm i -D playwright && npx playwright install chromium
node export.mjs
```
Produces `assets/hero.png` and `assets/feat-*.png` in one go — exactly what `README.md` references.
