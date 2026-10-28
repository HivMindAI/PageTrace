import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

let server, browser, base;
const results = new URL('../test-results/', import.meta.url);
const runtimeErrors = [];

before(async () => {
  server = spawn(process.execPath, ['scripts/serve.mjs'], { cwd: new URL('../', import.meta.url), env: { ...process.env, PORT: '0' }, stdio: ['ignore', 'pipe', 'pipe'] });
  const [output] = await once(server.stdout, 'data');
  base = output.toString().match(/http:\/\/127\.0\.0\.1:\d+/)[0];
  browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
  await mkdir(results, { recursive: true });
});
after(async () => { await browser?.close(); server?.kill(); });

async function open(options = {}) {
  const context = await browser.newContext(options);
  const page = await context.newPage();
  page.on('pageerror', error => runtimeErrors.push(error.message));
  const responses = [];
  const requests = [];
  page.on('response', response => responses.push(response));
  page.on('request', request => requests.push(request));
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.locator('.status-badge').waitFor();
  return { page, context, responses, requests };
}

test('desktop interactions: answer, citation focus, page switching, and provenance', async () => {
  const { page, context } = await open({ viewport: { width: 1440, height: 1100 } });
  assert.equal(await page.locator('.status-badge').textContent(), 'answered');
  assert.match(await page.locator('.answer-quote').innerText(), /\$12\.4 million/);
  await page.getByRole('link', { name: 'View page 1' }).click();
  assert.equal(await page.evaluate(() => document.activeElement.id), 'document-page');
  assert.match(await page.locator('#page-text mark').innerText(), /Northstar FY2025 revenue/);
  await page.getByRole('button', { name: '2', exact: true }).click();
  assert.match(await page.locator('#page-text').innerText(), /operating margin/);
  assert.equal(await page.locator('[data-page="2"]').getAttribute('aria-pressed'), 'true');
  await page.locator('.provenance summary').click();
  assert.match(await page.locator('#source-digest').innerText(), /^[a-f0-9]{64}$/);
  await page.getByRole('button', { name: 'Operating margin', exact: true }).click();
  assert.equal(await page.locator('.answer-quote p').innerText(), 'Northstar FY2025 operating margin was 18 percent.');
  await page.getByRole('link', { name: 'View page 2' }).click();
  assert.equal(await page.locator('#page-text mark').innerText(), 'Northstar FY2025 operating margin was 18 percent.');
  await page.locator('.provenance summary').click();
  await page.evaluate(() => { document.activeElement.blur(); window.scrollTo({ top: 0, behavior: 'instant' }); });
  await page.screenshot({ path: fileURLToPath(new URL('desktop.png', results)), fullPage: true });
  await context.close();
});

test('no-evidence and insufficient-coverage states contain no answer or citation', async () => {
  const { page, context } = await open();
  await page.getByRole('button', { name: 'Try abstention' }).click();
  assert.equal(await page.locator('.status-badge').textContent(), 'abstained');
  assert.equal(await page.locator('.reason').innerText(), 'no_retrieval_hits');
  assert.equal(await page.locator('.citation').count(), 0);
  assert.equal(await page.locator('#page-text mark').count(), 0);
  await page.getByLabel('Search the sample document').fill('Northstar climate emissions target transition');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  assert.equal(await page.locator('.reason').innerText(), 'insufficient_query_term_coverage');
  assert.equal(await page.locator('.citation').count(), 0);
  await context.close();
});

test('query validation, Enter submission, settings, and editing invalidate old answers', async () => {
  const { page, context } = await open();
  const input = page.getByLabel('Search the sample document');
  await input.fill('?!');
  assert.equal(await page.locator('#result').isVisible(), false);
  await input.press('Enter');
  assert.match(await page.locator('#input-error').innerText(), /at least one word/);
  assert.equal(await input.getAttribute('aria-invalid'), 'true');
  await input.fill('revenue unknown');
  await input.press('Enter');
  assert.equal(await page.locator('.status-badge').textContent(), 'answered');
  await page.locator('.search-settings summary').click();
  await page.getByLabel('Minimum lexical coverage').selectOption('1');
  assert.equal(await page.locator('.status-badge').textContent(), 'abstained');
  await input.fill('revenue');
  await input.press('Enter');
  assert.equal(await page.locator('.status-badge').textContent(), 'answered');
  await input.fill('<img src=x onerror=alert(1)>');
  await input.press('Enter');
  assert.equal(await page.locator('#result img').count(), 0);
  assert.equal(await page.locator('input[type=file]').count(), 0);
  await context.close();
});

test('static assets, downloads, links, and runtime network boundary', async () => {
  const { page, context, responses, requests } = await open();
  assert.ok(responses.every(response => response.status() === 200));
  assert.ok(requests.every(request => request.url().startsWith(base)));
  const initialRequests = requests.length;
  for (const name of ['Revenue', 'Operating margin', 'Try abstention']) await page.getByRole('button', { name, exact: true }).click();
  assert.equal(requests.length, initialRequests, 'search must perform no network requests');
  assert.ok(requests.every(request => request.method() === 'GET'));
  assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
  for (const path of ['/samples/northstar-fy2025.pdf', '/samples/provenance.json', '/favicon.svg']) {
    const response = await context.request.get(base + path);
    assert.equal(response.status(), 200);
    assert.equal(response.headers()['x-content-type-options'], 'nosniff');
  }
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download synthetic sample PDF' }).click();
  assert.equal((await downloadPromise).suggestedFilename(), 'northstar-fy2025.pdf');
  const links = await page.locator('a').evaluateAll(links => links.map(link => ({ href: link.getAttribute('href'), target: link.target, rel: link.rel })));
  for (const link of links) {
    if (link.href.startsWith('#')) assert.ok(await page.locator(link.href).count(), link.href);
    if (link.target === '_blank') assert.match(link.rel, /noopener/);
  }
  assert.deepEqual(runtimeErrors, []);
  await context.close();
});

for (const width of [320, 375, 390, 768, 1024, 1440]) {
  test(`responsive layout and interactions at ${width}px`, async () => {
    const { page, context } = await open({ viewport: { width, height: 900 }, isMobile: width < 700, hasTouch: width < 700, reducedMotion: 'reduce' });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'horizontal page overflow');
    const overflowing = await page.locator('main *').evaluateAll(elements => elements.filter(element => element.getBoundingClientRect().width && element.getBoundingClientRect().right > window.innerWidth + 1).map(element => element.tagName + '.' + element.className));
    assert.deepEqual(overflowing, []);
    await page.getByRole('button', { name: 'Try abstention' }).click();
    assert.equal(await page.locator('.status-badge').textContent(), 'abstained');
    await page.getByRole('button', { name: 'Operating margin', exact: true }).click();
    await page.getByRole('link', { name: 'View page 2' }).click();
    assert.ok(await page.locator('#page-text mark').isVisible());
    if (width === 390) {
      await page.evaluate(() => { document.activeElement.blur(); window.scrollTo({ top: 0, behavior: 'instant' }); });
      await page.screenshot({ path: fileURLToPath(new URL('mobile.png', results)), fullPage: true });
    }
    await context.close();
  });
}

test('keyboard navigation and static fallback remain usable', async () => {
  const { page, context } = await open({ reducedMotion: 'reduce' });
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.textContent), 'Skip to content');
  await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'main');
  assert.equal(await page.getByRole('heading', { level: 1 }).count(), 1);
  assert.equal(await page.getByRole('main').count(), 1);
  await context.close();
  const fallback = await browser.newContext({ javaScriptEnabled: false });
  const staticPage = await fallback.newPage();
  await staticPage.goto(base);
  assert.ok(await staticPage.locator('noscript').isVisible());
  assert.ok(await staticPage.getByRole('link', { name: 'Download synthetic sample PDF' }).isVisible());
  assert.ok(await staticPage.getByRole('heading', { name: 'Built around traceability.' }).isVisible());
  await fallback.close();
});
