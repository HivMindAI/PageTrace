import { cp, mkdir, readFile, readdir, lstat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { pages } from '../site/data.js';
import { pdfSha256 } from '../site/sample-identity.js';

const source = new URL('../site/', import.meta.url);
const destination = new URL('../dist/', import.meta.url);
const provenance = JSON.parse(await readFile(new URL('samples/provenance.json', source), 'utf8'));
const pdf = await readFile(new URL('samples/northstar-fy2025.pdf', source));
const digest = createHash('sha256').update(pdf).digest('hex');
if (digest !== pdfSha256 || digest !== provenance.pdf_sha256) throw new Error('Sample fingerprint mismatch');
if (JSON.stringify(provenance.pages.map(page => page.text)) !== JSON.stringify(pages.map(page => page.text))) throw new Error('Sample text mismatch');
// Copy only explicitly allowed site assets. No package, source repo, or test data.
const expected = ['app.js', 'data.js', 'engine.js', 'favicon.svg', 'index.html', 'sample-identity.js', 'samples', 'style.css'].sort();
const actual = (await readdir(source)).sort();
if (JSON.stringify(expected) !== JSON.stringify(actual)) throw new Error('Unexpected site contents');
for (const entry of actual) {
  if ((await lstat(new URL(entry, source))).isSymbolicLink()) throw new Error('Site symlinks are not allowed');
}
const sampleNames = ['northstar-fy2025.pdf', 'provenance.json'];
if (JSON.stringify((await readdir(new URL('samples/', source))).sort()) !== JSON.stringify(sampleNames)) throw new Error('Unexpected sample contents');
for (const entry of sampleNames) {
  if (!(await lstat(new URL(`samples/${entry}`, source))).isFile()) throw new Error('Samples must be regular files');
}
await mkdir(destination, { recursive: true });
for (const entry of expected) await cp(new URL(entry, source), new URL(entry, destination), { recursive: true });
console.log('Static build ready: showcase/dist (no runtime dependencies or backend)');
