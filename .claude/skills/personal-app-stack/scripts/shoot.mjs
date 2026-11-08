// Screenshot pages of a running app in light, dark and narrow, and report browser errors.
//   node shoot.mjs http://127.0.0.1:8770 <out-dir> "#/" "#/item/1" "#/settings"
// Needs Playwright with Chromium: a global or local `npm i playwright` (+ `npx playwright install
// chromium` if no browser is provided, e.g. Claude Code cloud sets PLAYWRIGHT_BROWSERS_PATH).
import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

async function loadPlaywright() {
  try { return await import('playwright'); } catch { /* not local: try the global install */ }
  const root = execSync('npm root -g').toString().trim();
  return createRequire(path.join(root, 'noop.js'))('playwright');
}

const [base, out, ...routes] = process.argv.slice(2);
if (!base || !out) { console.error('usage: node shoot.mjs <base-url> <out-dir> [#/route ...]'); process.exit(2); }
mkdirSync(out, { recursive: true });
const { chromium } = await loadPlaywright();
const browser = await chromium.launch();
const views = [
  ['light', { width: 1440, height: 1000 }, 'light'],
  ['dark', { width: 1440, height: 1000 }, 'dark'],
  ['narrow', { width: 390, height: 844 }, 'light'],
];
let failed = false;
for (const route of routes.length ? routes : ['#/']) {
  for (const [name, viewport, colorScheme] of views) {
    const page = await browser.newPage({ viewport, colorScheme, deviceScaleFactor: 1 });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
    await page.goto(new URL(route, base).href, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const file = path.join(out, `${route.replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '') || 'home'}-${name}.png`);
    await page.screenshot({ path: file, fullPage: true });
    console.log(`${file}${errors.length ? `  ERRORS: ${errors.join(' | ')}` : ''}`);
    failed ||= errors.length > 0;
    await page.close();
  }
}
await browser.close();
process.exit(failed ? 1 : 0);
