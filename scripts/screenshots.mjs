// Takes the README screenshots and the demo GIF from a real run.
//
//   python -m automation_finder serve --port 8765            (the web app)
//   n8n start on port 5691 with results/acme-plumbing/workflows imported (for the n8n canvas shot)
//   DOCS_KIT=<folder with gif.mjs> node scripts/screenshots.mjs
//
// gif.mjs (from the docs kit) provides a Chrome session with a visible pointer and the GIF encoder.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(ROOT, 'docs', 'screenshots');
const APP = process.env.APP_URL || 'http://127.0.0.1:8765';
const N8N = process.env.N8N_URL || 'http://localhost:5691';
const KIT = process.env.DOCS_KIT || resolve(ROOT, '..', '..', 'tools', 'docs-kit');
const { launch, GifRecorder, clickVisibly, smoothScroll } = await import(pathToFileURL(join(KIT, 'gif.mjs')).href);
const OWNER = { email: 'sarah@acmeplumbing.example', firstName: 'Sarah', lastName: 'Mitchell', password: 'Demo-Pass-2026' };
const only = process.argv.slice(2);
const want = (name) => !only.length || only.includes(name);

// Static shots hide the demo pointer that gif.mjs draws.
const still = (page) => page.evaluate(() => document.getElementById('__cursor')?.remove());

async function appShots() {
  const { browser, page } = await launch({ width: 1280, height: 860 });
  await page.goto(APP);
  await page.waitForTimeout(800);
  const sample = join(ROOT, 'data', 'acme-plumbing');
  await page.setInputFiles('#picker', ['emails.csv', 'tickets.csv', 'calendar.ics', 'activity.csv'].map((f) => join(sample, f)));
  await page.waitForSelector('.file');
  await page.fill('#business', 'Acme Plumbing');
  await page.waitForTimeout(500);
  await still(page);
  await page.screenshot({ path: join(OUT, 'app-upload.png') });
  await page.click('#go');
  await page.waitForSelector('tr.opp');
  await page.waitForTimeout(600);
  await page.evaluate(() => document.querySelector('#results').scrollIntoView());
  await page.waitForTimeout(400);
  await still(page);
  await page.screenshot({ path: join(OUT, 'app-results.png') });
  await page.click('tr.opp[data-id="O4"] .title');
  await page.waitForTimeout(300);
  await page.evaluate(() => document.querySelector('tr.opp[data-id="O4"]').scrollIntoView());
  await page.waitForTimeout(400);
  await still(page);
  await page.screenshot({ path: join(OUT, 'app-detail.png') });
  await browser.close();
}

async function reportShot() {
  const { browser, page } = await launch({ width: 1100, height: 1300 });
  await page.goto(pathToFileURL(join(ROOT, 'results', 'acme-plumbing', 'report.html')).href);
  await page.waitForTimeout(500);
  await still(page);
  await page.screenshot({ path: join(OUT, 'report.png') });
  await browser.close();
}

async function n8nShot() {
  const dir = join(ROOT, 'results', 'acme-plumbing', 'workflows');
  const file = readdirSync(dir).find((f) => f.startsWith('O4-'));
  const wf = JSON.parse(readFileSync(join(dir, file), 'utf8'));
  const { browser, page } = await launch({ width: 1600, height: 900 });
  await page.goto(`${N8N}/`);
  await page.waitForTimeout(4000);
  if (page.url().includes('/setup')) {
    for (const [name, value] of Object.entries(OWNER)) await page.fill(`input[name="${name}"]`, value);
    await page.getByRole('button', { name: 'Next' }).click();
    await page.waitForTimeout(4000);
  }
  if (page.url().includes('/signin')) {
    await page.fill('input[name="emailOrLdapLoginId"], input[name="email"]', OWNER.email);
    await page.fill('input[name="password"]', OWNER.password);
    await page.getByRole('button', { name: /sign in/i }).click();
    await page.waitForTimeout(4000);
  }
  for (let i = 0; i < 3; i++) await page.keyboard.press('Escape');
  for (const text of ['Skip', 'Get started', 'Close', 'Dismiss']) {
    const b = page.getByRole('button', { name: text, exact: true });
    if (await b.count()) await b.first().click().catch(() => {});
  }
  await page.goto(`${N8N}/workflow/${wf.id}`);
  await page.waitForSelector('[data-test-id="canvas-node"]', { timeout: 60000 });
  await page.waitForTimeout(2000);
  for (let i = 0; i < 3; i++) await page.keyboard.press('Escape');
  const fit = page.locator('[data-test-id="zoom-to-fit"]');
  if (await fit.count()) await fit.first().click();
  else await page.keyboard.press('1');
  await page.waitForTimeout(1200);
  await still(page);
  await page.screenshot({ path: join(OUT, 'n8n-workflow.png') });
  await browser.close();
}

async function demoGif() {
  const { browser, page } = await launch({ width: 1180, height: 760 });
  await page.goto(APP);
  await page.waitForTimeout(600);
  const rec = new GifRecorder(page, { fps: 5 });
  rec.start();
  await rec.hold(1200);
  await clickVisibly(page, page.locator('#sample'));
  await page.waitForSelector('tr.opp');
  await page.waitForTimeout(500);
  await smoothScroll(page, null, 330, { steps: 14 });
  await rec.hold(2200);
  const mins = page.locator('input.mins[data-id="O2"]');
  await clickVisibly(page, mins);
  await mins.fill('2');
  await mins.press('Tab');
  await page.waitForTimeout(900);
  await rec.hold(1800);
  await clickVisibly(page, page.locator('tr.opp[data-id="O4"] .title'));
  await page.waitForTimeout(400);
  await smoothScroll(page, null, 300, { steps: 14 });
  await rec.hold(2600);
  await smoothScroll(page, null, 900, { steps: 18 });
  await page.locator('#dl-html').hover();
  await rec.hold(1800);
  await rec.stop();
  const info = rec.save(join(OUT, 'demo.gif'), { dumpDir: process.env.GIF_FRAMES || null, every: 5 });
  console.log('demo.gif', info);
  await browser.close();
}

if (want('app')) await appShots();
if (want('report')) await reportShot();
if (want('n8n')) await n8nShot();
if (want('gif')) await demoGif();
