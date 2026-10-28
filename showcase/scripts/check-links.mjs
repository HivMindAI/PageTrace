// Explicit developer-only network check; never imported by the website or build.
import { readFile } from 'node:fs/promises';
const html = await readFile(new URL('../site/index.html', import.meta.url), 'utf8');
const links = [...new Set([...html.matchAll(/href="(https:[^"]+)"/g)].map(match => match[1]))];
const checks = await Promise.allSettled(links.map(async url => {
  const response = await fetch(url, { method: 'HEAD', redirect: 'follow', signal: AbortSignal.timeout(30000) });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}`);
  console.log(`HTTP ${response.status} ${url}`);
}));
const failures = checks.filter(result => result.status === 'rejected');
for (const result of failures) console.error(result.reason);
if (failures.length) process.exitCode = 1;
