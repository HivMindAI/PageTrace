# PageTrace public showcase

A separate, responsive, static Evidence Desk demonstration for Open Doors scholarship reviewers.
All implementation, assets, configuration, and tests live in `showcase/`. Nothing in the Python
package, original backend, original web application, or original tests is changed.

## Run locally

Requires Node 22.12+ or Node 24. The tested runtime is Node 24.19.0.

```sh
cd showcase
node scripts/build.mjs
node scripts/serve.mjs
```

Open `http://127.0.0.1:4173`. The preview server binds only to loopback and serves the standalone
`dist/` directory. It never imports or starts the PageTrace backend. Stop it with Ctrl+C.

The build has **no third-party dependencies**. TypeScript and Playwright are development tools
only; they are not needed by Render or shipped to visitors.

## Reviewer experience

- Overview of the documented project and its traceability principles.
- Browser search over the exact two public synthetic portfolio page texts.
- Exact-slice answers, page links, character offsets, retrieval rank, and matched query terms.
- Citation links focus the sample reader and highlight the cited source characters.
- Revenue and operating-margin examples, plus the documented no-evidence carbon question.
- Explicit abstention both for no search hits and insufficient lexical coverage.
- Downloadable synthetic PDF and provenance JSON with real SHA-256 fingerprints.
- Architecture, scope limitations, and documentation pinned to the inspected source revision.
- Keyboard navigation, reduced-motion support, small-screen layouts, and a static no-JavaScript
  fallback with document and documentation links.

## Evidence and claim boundaries

Source revision: `0de8da3556406c0b12d135fce806d1936e3cd9f6`.

The sample paragraphs come verbatim from `PORTFOLIO_PAGE_TEXTS` in
[`src/pagetrace/portfolio.py`](https://github.com/HivMindAI/PageTrace/blob/0de8da3556406c0b12d135fce806d1936e3cd9f6/src/pagetrace/portfolio.py).
The revenue and carbon questions match that file's documented constants. The bundled PDF is a
byte-format port of its pure `_portfolio_pdf_bytes` helper, independently compared against that
original function by `tests/verify_fixture.py` without importing the Python package.

The downloaded PDF SHA-256 is:

```text
abc4c11eb5f49b2280288dc80ad0e0c87bc166247625e016a71d3e9810804e85
```

The browser engine illustrates the documented BM25 formula (`k1=1.2`, `b=0.75`) over **two page
texts**, then considers sentences from **one top-ranked page** and returns **one exact excerpt**
with minimum unique query-term coverage `0.5` (optionally `1.0`). Decimal punctuation is preserved.
This is not a port of the canonical Python artifact validation system. JavaScript NFKC/lowercase
normalization is not identical to Python NFKC/casefolding. Browser rankings and scores are
illustrative; they are not serialized Python results or evaluation metrics.

References such as `sample-page-1` are demo-local. Character offsets are zero-based and
end-exclusive in the bundled page text. No canonical corpus/chunk IDs, PDF bounding boxes, OCR
confidence values, test counts from the original project, performance measurements, or accuracy
results are invented. Reader headings and layout are explicitly labeled as presentation additions.

This small synthetic fixture is not representative evaluation. Lexical overlap can select
irrelevant text, and source-exact text need not be true, complete, or semantically answer the
question. The demo cannot synthesize across evidence or documents.

## Public-demo boundary

There are no uploads, user accounts, credentials, APIs, analytics, remote fonts, CDN scripts,
database, service worker, browser persistence, or external model calls. Queries stay in page memory;
search and answer interactions make no network requests. Runtime scripts use DOM text nodes.
The CSP blocks fetch connections, forms, objects, and third-party executable resources. Normal
visits request static assets from the host; GitHub links navigate to GitHub when selected.

No Python, PDF parser, or OCR engine runs in the browser or on Render. The PDF and its texts are
bundled in advance. The real product remains an authenticated, loopback-only application for a
trusted local operator; see the original
[security policy](https://github.com/HivMindAI/PageTrace/blob/0de8da3556406c0b12d135fce806d1936e3cd9f6/SECURITY.md)
and [portfolio scope](https://github.com/HivMindAI/PageTrace/blob/0de8da3556406c0b12d135fce806d1936e3cd9f6/docs/PORTFOLIO.md).

## Checks

From `showcase/`, install the pinned development tools using pnpm 11.25.0:

```sh
pnpm install --frozen-lockfile
pnpm check
pnpm build
pnpm test
pnpm exec playwright install chromium
pnpm test:ui
python tests/verify_fixture.py
```

Optional read-only public-link verification: `node scripts/check-links.mjs` (requires network).

The final command needs Python 3.11+ but no package dependencies. It reads the original pure
fixture helper for byte comparison, so it runs from the repository checkout, not the Render build.
The unit/integrity suite also reads the original Git revision to verify documentation paths and
unchanged tracked files. These developer checks are deliberately separate from the deployment
build, which works with only the contents of `showcase/` available.

UI tests start and stop their own loopback server. They cover answers, both abstention reasons,
threshold changes, invalid/edited questions, literal handling of markup, page navigation, source
focus/highlights, downloads, anchors, asset responses, keyboard navigation, no-JavaScript fallback,
no runtime search requests, and layouts at 320, 375, 390, 768, 1024, and 1440 pixels. Chromium
screenshots are written to ignored `test-results/desktop.png` and `test-results/mobile.png`.
These tests do not claim full accessibility compliance or cross-browser certification.

When a sandbox redirects the browser cache, use the same `PLAYWRIGHT_BROWSERS_PATH` during
Playwright installation and UI tests. For example, set it to `showcase/node_modules/.browsers`
(absolute path) to keep the browser in the ignored demo dependency directory.

The original project suite is outside the scope of this isolated static addition. Do not start
the original backend or install/refactor its Python or frontend dependencies to preview this site.

## Implementation verification — October 28, 2026

- Strict TypeScript checking and dependency-free static build: passed on Node 24.19.0.
- Unit/integrity checks: 19 passed, including an isolated Render-root build without dependencies.
- UI checks: all 11 passed in installed Chrome and in Playwright's pinned Chromium 151.0.7922.34.
- Responsive interaction checks: 320, 375, 390, 768, 1024, and 1440 px; no horizontal overflow found.
- Desktop and mobile screenshots: visually inspected; saved in ignored `test-results/`.
- Six unique public repository/documentation URLs: all returned HTTP 200.
- Bundled PDF: all 996 bytes match the original pure generator; source hash matches provenance.
- Search interactions: no additional network requests; no uploads or browser persistence.
- Original tracked working-tree files and Git index: unchanged; HEAD remains `0de8da3`.
- No commit, push, merge, remote service creation, or deployment performed. Render hosting and
  response headers have not been tested on a live deployment.

## Render Static Site settings — for use after approval

No commit, push, deployment, or remote resource creation is performed by the build scripts.
The branch must be approved, committed, and pushed before Render can access these new files.

| Setting | Exact value |
| --- | --- |
| Service type | **Static Site** (not Web Service) |
| Repository | `https://github.com/HivMindAI/PageTrace` |
| Branch | `feature/pagetrace-render-demo` |
| Root Directory | `showcase` |
| Build Command | `node scripts/build.mjs` |
| Publish Directory | `dist` |
| `NODE_VERSION` | `24.19.0` |
| `SKIP_INSTALL_DEPS` | `true` |
| Auto-Deploy | **Off** |
| Start command | None |
| Rewrites/redirects | None needed; navigation uses same-page anchors |
| Credentials / API keys / database | None |

Render's [Static Sites guide](https://render.com/docs/static-sites) documents free static hosting,
subject to workspace bandwidth and pipeline-minute allowances, and the `SKIP_INSTALL_DEPS` setting.
Its [monorepo guide](https://render.com/docs/monorepo-support) confirms commands and the publish
directory are relative to the configured root. No parent repository files are needed at build time.

An optional, unsubmitted Blueprint is provided at `showcase/render.yaml`. To use it after approval,
select that custom Blueprint path. The YAML declares one static site, turns automatic deploys off,
and supplies security headers. See the [Blueprint reference](https://render.com/docs/blueprint-spec).
Creating a site or syncing a new Blueprint triggers an initial deployment even when subsequent
automatic deploys are disabled; wait for explicit approval before either action.

For manual dashboard setup, add the same headers listed in `render.yaml`, including CSP
`frame-ancestors 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, restricted `Permissions-Policy`, and revalidation caching.
The HTML includes its own CSP; framing controls require response headers.

## Files

- `site/index.html`, `site/style.css`, `site/favicon.svg`: standalone interface and visual assets.
- `site/app.js`, `site/engine.js`: accessible interactions and illustrative retrieval/answer logic.
- `site/data.js`, `site/sample-identity.js`: fixture text, pinned source revision, actual PDF hash.
- `site/samples/northstar-fy2025.pdf`, `site/samples/provenance.json`: public sample and provenance.
- `scripts/build.mjs`, `scripts/serve.mjs`: dependency-free build and loopback preview.
- `scripts/generate-sample.mjs`: explicit development-time fixture-generation utility.
- `scripts/check-links.mjs`: optional HTTP verification of public GitHub/documentation links.
- `tests/engine.test.mjs`, `tests/integrity.test.mjs`, `tests/ui.test.mjs`,
  `tests/verify_fixture.py`: behavior, integrity, browser, and original-fixture byte checks.
- `package.json`, `pnpm-lock.yaml`, `tsconfig.json`: pinned checks and strict JS type checking.
- `render.yaml`, `.node-version`, `.gitignore`: reviewed hosting settings, Node pin, generated-file exclusions.
- `README.md`: usage, evidence boundaries, testing, file inventory, and deployment instructions.

`dist/`, `node_modules/`, and `test-results/` are generated locally and ignored. Render publishes
only `dist/`. The original repository's files and ignore rules remain untouched.
