// Render the poster + feature cards to crisp 2x PNGs.
//   one-time:  npm i -D playwright && npx playwright install chromium
//   run:       node assets/export.mjs
// Outputs assets/hero.png and assets/feat-*.png (what the README references).
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const fileUrl = (f) => 'file://' + path.join(dir, f);

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 2 });

await page.goto(fileUrl('poster.html'), { waitUntil: 'networkidle' });
await page.waitForTimeout(500);                       // let webfonts settle
await page.locator('.poster').screenshot({ path: path.join(dir, 'hero.png') });
console.log('  ✓ assets/hero.png');

const cards = {
  'card-timeline': 'feat-timeline', 'card-detail': 'feat-detail',
  'card-charts': 'feat-charts', 'card-activity': 'feat-activity',
};
await page.goto(fileUrl('features.html'), { waitUntil: 'networkidle' });
await page.waitForTimeout(500);
for (const [id, out] of Object.entries(cards)) {
  await page.locator('#' + id).screenshot({ path: path.join(dir, out + '.png') });
  console.log(`  ✓ assets/${out}.png`);
}

await browser.close();
console.log('Done — all assets exported at 2x.');
