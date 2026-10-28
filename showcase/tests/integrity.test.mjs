import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir, mkdir, mkdtemp, cp } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { pages, examples, SOURCE_REVISION } from '../site/data.js';
import { pdfSha256 } from '../site/sample-identity.js';

const root = new URL('../../', import.meta.url);
const site = new URL('../site/', import.meta.url);
const html = await readFile(new URL('index.html', site), 'utf8');

test('public fixture text and documented questions match the pinned original source', async () => {
  const source = execFileSync('git', ['show', `${SOURCE_REVISION}:src/pagetrace/portfolio.py`], { cwd: root, encoding: 'utf8' });
  const constants = source.match(/PORTFOLIO_PAGE_TEXTS = \(\r?\n([\s\S]*?)\r?\n\)/)[1];
  assert.deepEqual([...constants.matchAll(/"([^"\r\n]*)"/g)].map(match => match[1]), pages.map(page => page.text));
  assert.ok(source.includes(`PORTFOLIO_ANSWER_QUESTION = "${examples[0].query}"`));
  assert.ok(source.includes(`PORTFOLIO_ABSTENTION_QUESTION = "${examples[2].query}"`));
});

test('bundled PDF and page text hashes match the downloadable provenance', async () => {
  const provenance = JSON.parse(await readFile(new URL('samples/provenance.json', site), 'utf8'));
  const pdf = await readFile(new URL('samples/northstar-fy2025.pdf', site));
  assert.equal(createHash('sha256').update(pdf).digest('hex'), pdfSha256);
  assert.equal(provenance.pdf_sha256, pdfSha256);
  assert.equal(provenance.pdf_bytes, pdf.length);
  assert.equal(provenance.source_revision, SOURCE_REVISION);
  for (const page of provenance.pages) assert.equal(createHash('sha256').update(page.text).digest('hex'), page.text_sha256);
  assert.equal(provenance.synthetic, true);
});

test('documentation links point to real paths at the inspected commit', () => {
  for (const [, path] of html.matchAll(/data-doc="([^"]+)"/g)) {
    execFileSync('git', ['cat-file', '-e', `${SOURCE_REVISION}:${path}`], { cwd: root });
  }
  for (const [, href] of html.matchAll(/href="(https:[^"]+)"/g)) {
    assert.ok(href === 'https://github.com/HivMindAI/PageTrace' || href.startsWith(`https://github.com/HivMindAI/PageTrace/blob/${SOURCE_REVISION}/`));
  }
});

test('every local asset and internal anchor resolves', async () => {
  const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map(match => match[1]));
  for (const [, href] of html.matchAll(/(?:src|href)="([^"]+)"/g)) {
    if (href.startsWith('#')) assert.ok(ids.has(href.slice(1)), href);
    if (href.startsWith('./')) await readFile(new URL(href, site));
  }
});

test('static source forbids remote runtime requests, unsafe HTML insertion, and storage', async () => {
  for (const file of (await readdir(site)).filter(file => file.endsWith('.js'))) {
    const code = await readFile(new URL(file, site), 'utf8');
    assert.doesNotMatch(code, /\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon|innerHTML|outerHTML|insertAdjacentHTML|localStorage|sessionStorage|indexedDB|eval\s*\(|new Function/);
  }
  assert.match(html, /connect-src 'none'/);
  assert.match(html, /form-action 'none'/);
  assert.doesNotMatch(html, /type="file"|<iframe|<object|https?:\/\/[^" ]+\.(?:css|js)/);
});

test('build output has exactly the intended static files and matches source bytes', async () => {
  const dist = new URL('../dist/', import.meta.url);
  assert.deepEqual((await readdir(dist)).sort(), (await readdir(site)).sort());
  for (const file of await readdir(site)) {
    if (file === 'samples') continue;
    assert.deepEqual(await readFile(new URL(file, dist)), await readFile(new URL(file, site)));
  }
  assert.deepEqual((await readdir(new URL('samples/', dist))).sort(), ['northstar-fy2025.pdf', 'provenance.json']);
});

test('original tracked files and index remain unchanged', () => {
  const unstaged = execFileSync('git', ['diff', '--name-only'], { cwd: root, encoding: 'utf8' }).trim();
  const staged = execFileSync('git', ['diff', '--cached', '--name-only'], { cwd: root, encoding: 'utf8' }).trim();
  assert.equal(unstaged, '');
  assert.equal(staged, '');
});

test('Render build works from an isolated showcase root without the repo or node_modules', async () => {
  const resultDirectory = new URL('../test-results/', import.meta.url);
  await mkdir(resultDirectory, { recursive: true });
  const isolated = await mkdtemp(new URL('render-root-', resultDirectory));
  await mkdir(`${isolated}/scripts`);
  await cp(new URL('../scripts/build.mjs', import.meta.url), `${isolated}/scripts/build.mjs`);
  await cp(new URL('../package.json', import.meta.url), `${isolated}/package.json`);
  await cp(site, `${isolated}/site`, { recursive: true });
  const output = execFileSync(process.execPath, ['scripts/build.mjs'], { cwd: isolated, encoding: 'utf8' });
  assert.match(output, /Static build ready/);
  assert.deepEqual((await readdir(`${isolated}/dist`)).sort(), (await readdir(site)).sort());
});
