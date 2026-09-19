import "./style.css";

import { ApiError, PageTraceClient } from "./api";
import {
  TERMINAL_STATUSES,
  WORKFLOW_LABELS,
  asArray,
  asNumber,
  asRecord,
  asString,
  compactId,
  formatDate,
  formatNumber,
  parseJsonObject,
  titleCase,
} from "./format";
import type {
  Job,
  JobEvent,
  JobSubmission,
  JsonObject,
  JsonValue,
  Metrics,
  WorkflowName,
} from "./types";

const shell = `
  <div class="app-shell">
    <aside class="rail" aria-label="Primary navigation">
      <a class="brand" href="#workspace" aria-label="PageTrace home">
        <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>
        <span><b>PageTrace</b><small>Evidence desk</small></span>
      </a>
      <nav class="primary-nav">
        <button class="nav-item is-active" data-view="workspace" type="button">
          <span class="nav-icon" aria-hidden="true">⌁</span><span>Workspace</span>
        </button>
        <button class="nav-item" data-view="activity" type="button">
          <span class="nav-icon" aria-hidden="true">◷</span><span>Activity</span>
          <span id="active-count" class="count-badge" hidden>0</span>
        </button>
        <button class="nav-item" data-view="system" type="button">
          <span class="nav-icon" aria-hidden="true">◎</span><span>System</span>
        </button>
      </nav>
      <div class="rail-note">
        <span class="eyebrow">Trust boundary</span>
        <p>Source text is evidence, never an instruction.</p>
      </div>
    </aside>

    <div class="page">
      <header class="topbar">
        <div class="environment">
          <span id="connection-dot" class="connection-dot" aria-hidden="true"></span>
          <span><b id="connection-label">Not connected</b><small>${window.location.host || "local server"}</small></span>
        </div>
        <form id="auth-form" class="auth-form" autocomplete="off">
          <label for="token">Backend token</label>
          <input id="token" name="token" type="password" minlength="32" maxlength="512" required
            placeholder="Paste token — kept in memory only" spellcheck="false" />
          <button class="button button-dark" type="submit">Connect</button>
        </form>
      </header>

      <main id="main-content" tabindex="-1">
        <section id="view-workspace" class="view is-active" aria-labelledby="workspace-title">
          <div class="hero">
            <div>
              <span class="eyebrow">Evidence operations / M9</span>
              <h1 id="workspace-title">Every answer should show its work.</h1>
              <p>Ingest deterministic sources, ask bounded questions, and inspect the exact text behind every claim.</p>
            </div>
            <div class="hero-stamp" aria-label="Local-first system">
              <span>Local-first</span><b>01</b><small>auditable pipeline</small>
            </div>
          </div>

          <div class="workspace-grid">
            <section class="panel workflow-panel" aria-labelledby="workflow-title">
              <div class="panel-heading">
                <div><span class="step-number">01</span><div><span class="eyebrow">Start here</span><h2 id="workflow-title">New workflow</h2></div></div>
                <span class="quiet-chip">Deterministic</span>
              </div>
              <div class="workflow-tabs" role="tablist" aria-label="Workflow type">
                <button id="tab-ingest" class="workflow-tab is-active" role="tab" aria-selected="true" aria-controls="form-ingest" data-workflow="ingest" type="button">Ingest</button>
                <button id="tab-answer" class="workflow-tab" role="tab" aria-selected="false" aria-controls="form-answer" data-workflow="answer" type="button">Ask</button>
                <button id="tab-quality" class="workflow-tab" role="tab" aria-selected="false" aria-controls="form-quality" data-workflow="quality" type="button">Evaluate</button>
              </div>

              <form id="form-ingest" class="workflow-form" data-workflow-form="ingest">
                <div class="form-intro"><b>Register a source</b><p>Use a file path inside the backend’s configured input root. The browser never uploads or copies the file.</p></div>
                <label class="field"><span>Source path</span><input name="source_path" required maxlength="4096" placeholder="incoming/annual-report.pdf" spellcheck="false" /><small>Relative paths resolve under <code>--input-root</code>.</small></label>
                <label class="field compact-field"><span>Maximum attempts</span><input name="max_attempts" type="number" min="1" max="20" value="3" required /></label>
                <button class="button button-accent submit-button" type="submit"><span>Start document intake</span><span aria-hidden="true">→</span></button>
              </form>

              <form id="form-answer" class="workflow-form" data-workflow-form="answer" hidden>
                <div class="form-intro"><b>Ask with evidence</b><p>Answers are extractive. PageTrace either returns exact source excerpts or explicitly abstains.</p></div>
                <div class="field-row">
                  <label class="field"><span>Document ID</span><input name="document_id" required maxlength="256" placeholder="sha256-…" spellcheck="false" /></label>
                  <label class="field"><span>Corpus artifact ID</span><input name="corpus_artifact_id" required maxlength="256" placeholder="corpus-sha256-…" spellcheck="false" /></label>
                </div>
                <label class="field"><span>Question</span><textarea name="question" required maxlength="10000" rows="4" placeholder="What evidence supports the reported revenue change?"></textarea></label>
                <details class="advanced">
                  <summary>Retrieval and evidence bounds</summary>
                  <div class="field-row three">
                    <label class="field"><span>Top results</span><input name="top_k" type="number" min="1" max="1000" value="10" /></label>
                    <label class="field"><span>Evidence items</span><input name="max_evidence_items" type="number" min="1" max="100" value="3" /></label>
                    <label class="field"><span>Min. coverage</span><input name="minimum_query_term_coverage" type="number" min="0.01" max="1" step="0.01" value="0.25" /></label>
                  </div>
                  <label class="field"><span>Maximum answer characters</span><input name="max_answer_characters" type="number" min="1" max="100000" value="4000" /></label>
                </details>
                <button class="button button-accent submit-button" type="submit"><span>Run evidence answer</span><span aria-hidden="true">→</span></button>
              </form>

              <form id="form-quality" class="workflow-form" data-workflow-form="quality" hidden>
                <div class="form-intro"><b>Measure the pipeline</b><p>Evaluate a canonical suite against explicit gates and, optionally, a prior baseline.</p></div>
                <label class="field"><span>Quality suite JSON</span><textarea class="code-input" name="suite" required rows="9" placeholder='{&quot;schema_version&quot;: 1, …}' spellcheck="false"></textarea></label>
                <label class="field"><span>Baseline report JSON <em>optional</em></span><textarea class="code-input" name="baseline" rows="4" placeholder="Leave empty for no baseline" spellcheck="false"></textarea></label>
                <button class="button button-accent submit-button" type="submit"><span>Evaluate quality suite</span><span aria-hidden="true">→</span></button>
              </form>
            </section>

            <aside class="panel brief-panel" aria-labelledby="brief-title">
              <div class="panel-heading compact"><div><span class="step-number coral">i</span><div><span class="eyebrow">Reading the result</span><h2 id="brief-title">Evidence brief</h2></div></div></div>
              <ol class="brief-list">
                <li><span>01</span><div><b>Identity is content-bound</b><p>Full fingerprints reveal whether you are looking at the exact source and artifact requested.</p></div></li>
                <li><span>02</span><div><b>Citations are exact slices</b><p>Each excerpt keeps its chunk, page, offsets, retrieval rank, and bounding region.</p></div></li>
                <li><span>03</span><div><b>Uncertainty is visible</b><p>Coverage is lexical—not a truth score. Failed thresholds produce an explicit abstention.</p></div></li>
              </ol>
              <div class="notice"><b>Privacy note</b><p>The access token is held only in this page’s memory and disappears on refresh.</p></div>
            </aside>
          </div>
        </section>

        <section id="view-activity" class="view" aria-labelledby="activity-title" hidden>
          <div class="section-head"><div><span class="eyebrow">Durable execution</span><h1 id="activity-title">Workflow activity</h1><p>Reopen known job IDs, inspect ordered lifecycle events, and cancel work that has not completed.</p></div>
            <form id="open-job-form" class="open-job-form"><label for="open-job-id">Open a job</label><div><input id="open-job-id" required pattern="job-[0-9a-f]{32}" placeholder="job-…" spellcheck="false" /><button class="button button-dark" type="submit">Inspect</button></div></form>
          </div>
          <div class="activity-layout">
            <section class="panel jobs-panel" aria-labelledby="jobs-title"><div class="panel-heading"><div><span class="step-number">02</span><div><span class="eyebrow">This session</span><h2 id="jobs-title">Recent jobs</h2></div></div></div><div id="job-list" class="job-list"></div></section>
            <section id="job-inspector" class="panel inspector-panel" aria-live="polite"><div class="empty-state"><span class="empty-mark">⌁</span><h2>Select a job to inspect</h2><p>Completed results reveal provenance and evidence. Active jobs refresh automatically.</p></div></section>
          </div>
        </section>

        <section id="view-system" class="view" aria-labelledby="system-title" hidden>
          <div class="section-head"><div><span class="eyebrow">Operational visibility</span><h1 id="system-title">System status</h1><p>Readiness and persistent queue counters, without exposing document content.</p></div><button id="refresh-system" class="button button-dark" type="button">Refresh metrics</button></div>
          <div id="system-content" class="system-content"><div class="panel empty-state"><span class="empty-mark">◎</span><h2>Connect to inspect the backend</h2><p>Enter the bearer token above. Readiness itself contains no document data.</p></div></div>
        </section>
      </main>
      <div id="toast-region" class="toast-region" aria-live="polite" aria-atomic="true"></div>
    </div>
  </div>
`;

const app = document.querySelector<HTMLDivElement>("#app");
if (app === null) throw new Error("PageTrace app root is missing");
app.innerHTML = shell;

const state: {
  client: PageTraceClient;
  connected: boolean;
  jobs: Map<string, Job>;
  events: Map<string, JobEvent[]>;
  selectedJobId: string | null;
  pollTimer: number | null;
} = {
  client: new PageTraceClient(""),
  connected: false,
  jobs: new Map(),
  events: new Map(),
  selectedJobId: null,
  pollTimer: null,
};

function requiredElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (element === null) throw new Error(`Required element is missing: ${selector}`);
  return element;
}

function node<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  if (className !== undefined) element.className = className;
  return element;
}

function textNode<K extends keyof HTMLElementTagNameMap>(tag: K, text: string, className?: string): HTMLElementTagNameMap[K] {
  const element = node(tag, className);
  element.textContent = text;
  return element;
}

function clear(element: Element): void {
  element.replaceChildren();
}

function showToast(message: string, tone: "info" | "error" = "info"): void {
  const region = requiredElement<HTMLDivElement>("#toast-region");
  const toast = textNode("div", message, `toast toast-${tone}`);
  region.replaceChildren(toast);
  window.setTimeout(() => toast.remove(), 5000);
}

function setConnection(connected: boolean, label: string): void {
  state.connected = connected;
  requiredElement("#connection-dot").classList.toggle("is-online", connected);
  requiredElement("#connection-label").textContent = label;
}

function setView(view: string): void {
  document.querySelectorAll<HTMLElement>(".view").forEach((element) => {
    const active = element.id === `view-${view}`;
    element.hidden = !active;
    element.classList.toggle("is-active", active);
  });
  document.querySelectorAll<HTMLButtonElement>(".nav-item").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === view);
  });
  window.location.hash = view;
  if (view === "system" && state.connected) void refreshSystem();
}

document.querySelectorAll<HTMLButtonElement>(".nav-item").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view ?? "workspace"));
});

document.querySelectorAll<HTMLButtonElement>(".workflow-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    const workflow = tab.dataset.workflow;
    document.querySelectorAll<HTMLButtonElement>(".workflow-tab").forEach((candidate) => {
      const active = candidate === tab;
      candidate.classList.toggle("is-active", active);
      candidate.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll<HTMLFormElement>("[data-workflow-form]").forEach((form) => {
      form.hidden = form.dataset.workflowForm !== workflow;
    });
  });
});

requiredElement<HTMLFormElement>("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = requiredElement<HTMLInputElement>("#token");
  state.client.setToken(input.value);
  setConnection(false, "Checking backend…");
  try {
    const ready = await state.client.ready();
    if (!ready) throw new Error("The backend is not ready.");
    await state.client.metrics();
    setConnection(true, "Connected locally");
    input.value = "";
    showToast("Connected. The token is held in memory only.");
    await refreshSystem();
    if (state.selectedJobId !== null) await refreshJob(state.selectedJobId);
  } catch (error) {
    setConnection(false, "Connection failed");
    showToast(errorMessage(error), "error");
  }
});

requiredElement<HTMLFormElement>("#form-ingest").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!(form instanceof HTMLFormElement)) return;
  const data = new FormData(form);
  const submission: JobSubmission = {
    workflow: "ingest_document",
    request: { source_path: fieldString(data, "source_path") },
    idempotency_key: freshKey("ingest"),
    max_attempts: fieldInteger(data, "max_attempts"),
  };
  void submitJob(submission, form);
});

requiredElement<HTMLFormElement>("#form-answer").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!(form instanceof HTMLFormElement)) return;
  const data = new FormData(form);
  const submission: JobSubmission = {
    workflow: "answer_question",
    request: {
      document_id: fieldString(data, "document_id"),
      corpus_artifact_id: fieldString(data, "corpus_artifact_id"),
      question: fieldString(data, "question"),
      top_k: fieldInteger(data, "top_k"),
      max_evidence_items: fieldInteger(data, "max_evidence_items"),
      max_answer_characters: fieldInteger(data, "max_answer_characters"),
      minimum_query_term_coverage: fieldNumber(data, "minimum_query_term_coverage"),
    },
    idempotency_key: freshKey("answer"),
    max_attempts: 3,
  };
  void submitJob(submission, form);
});

requiredElement<HTMLFormElement>("#form-quality").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!(form instanceof HTMLFormElement)) return;
  try {
    const data = new FormData(form);
    const request: JsonObject = { suite: parseJsonObject(fieldString(data, "suite"), "Suite") };
    const baseline = fieldString(data, "baseline", false);
    if (baseline !== "") request.baseline = parseJsonObject(baseline, "Baseline");
    void submitJob(
      {
        workflow: "evaluate_quality",
        request,
        idempotency_key: freshKey("quality"),
        max_attempts: 3,
      },
      form,
    );
  } catch (error) {
    showToast(errorMessage(error), "error");
  }
});

requiredElement<HTMLFormElement>("#open-job-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const jobId = requiredElement<HTMLInputElement>("#open-job-id").value.trim();
  void selectJob(jobId);
});

requiredElement<HTMLButtonElement>("#refresh-system").addEventListener("click", () => void refreshSystem());

function fieldString(data: FormData, name: string, required = true): string {
  const value = data.get(name);
  if (typeof value !== "string") throw new Error(`${titleCase(name)} is required.`);
  const trimmed = value.trim();
  if (required && trimmed === "") throw new Error(`${titleCase(name)} is required.`);
  return trimmed;
}

function fieldInteger(data: FormData, name: string): number {
  const value = Number.parseInt(fieldString(data, name), 10);
  if (!Number.isInteger(value)) throw new Error(`${titleCase(name)} must be an integer.`);
  return value;
}

function fieldNumber(data: FormData, name: string): number {
  const value = Number(fieldString(data, name));
  if (!Number.isFinite(value)) throw new Error(`${titleCase(name)} must be a number.`);
  return value;
}

function freshKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

async function submitJob(submission: JobSubmission, form: HTMLFormElement): Promise<void> {
  if (!state.connected) {
    showToast("Connect to the backend before starting a workflow.", "error");
    requiredElement<HTMLInputElement>("#token").focus();
    return;
  }
  const button = form.querySelector<HTMLButtonElement>("button[type=submit]");
  if (button !== null) button.disabled = true;
  try {
    const { job, created } = await state.client.submit(submission);
    state.jobs.set(job.job_id, job);
    state.events.set(job.job_id, []);
    renderJobList();
    showToast(created ? "Workflow accepted into the durable queue." : "Existing idempotent job reopened.");
    setView("activity");
    await selectJob(job.job_id);
  } catch (error) {
    showToast(errorMessage(error), "error");
  } finally {
    if (button !== null) button.disabled = false;
  }
}

async function selectJob(jobId: string): Promise<void> {
  state.selectedJobId = jobId;
  setView("activity");
  renderJobList();
  renderLoadingInspector();
  await refreshJob(jobId);
}

async function refreshJob(jobId: string): Promise<void> {
  try {
    const { job } = await state.client.job(jobId);
    state.jobs.set(jobId, job);
    const known = state.events.get(jobId) ?? [];
    const after = known.at(-1)?.sequence ?? 0;
    const { events } = await state.client.events(jobId, after);
    state.events.set(jobId, [...known, ...events]);
    renderJobList();
    if (state.selectedJobId === jobId) renderInspector(job, state.events.get(jobId) ?? []);
    schedulePoll(job);
  } catch (error) {
    showToast(errorMessage(error), "error");
    renderInspectorError(errorMessage(error));
  }
}

function schedulePoll(job: Job): void {
  if (state.pollTimer !== null) window.clearTimeout(state.pollTimer);
  state.pollTimer = null;
  if (!TERMINAL_STATUSES.has(job.status) && state.selectedJobId === job.job_id) {
    state.pollTimer = window.setTimeout(() => void refreshJob(job.job_id), 1500);
  }
}

function renderJobList(): void {
  const list = requiredElement<HTMLDivElement>("#job-list");
  clear(list);
  const jobs = [...state.jobs.values()].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const active = jobs.filter((job) => !TERMINAL_STATUSES.has(job.status)).length;
  const activeCount = requiredElement<HTMLSpanElement>("#active-count");
  activeCount.hidden = active === 0;
  activeCount.textContent = String(active);
  if (jobs.length === 0) {
    const empty = node("div", "list-empty");
    empty.append(textNode("b", "No jobs in this session"), textNode("p", "Start a workflow or open a known job ID."));
    list.append(empty);
    return;
  }
  jobs.forEach((job) => {
    const button = node("button", `job-card ${state.selectedJobId === job.job_id ? "is-selected" : ""}`);
    button.type = "button";
    const top = node("span", "job-card-top");
    top.append(textNode("span", WORKFLOW_LABELS[job.workflow]), statusBadge(job.status));
    button.append(top, textNode("b", compactId(job.job_id, 8)), textNode("small", formatDate(job.updated_at)));
    button.addEventListener("click", () => void selectJob(job.job_id));
    list.append(button);
  });
}

function statusBadge(status: string): HTMLSpanElement {
  return textNode("span", titleCase(status), `status status-${status}`);
}

function renderLoadingInspector(): void {
  const inspector = requiredElement<HTMLElement>("#job-inspector");
  clear(inspector);
  const loading = node("div", "empty-state");
  loading.append(node("span", "loader"), textNode("h2", "Loading durable job"), textNode("p", "Reading the latest snapshot and ordered events."));
  inspector.append(loading);
}

function renderInspectorError(message: string): void {
  const inspector = requiredElement<HTMLElement>("#job-inspector");
  clear(inspector);
  const error = node("div", "empty-state error-state");
  error.append(textNode("span", "!", "empty-mark"), textNode("h2", "Job could not be opened"), textNode("p", message));
  inspector.append(error);
}

function renderInspector(job: Job, events: JobEvent[]): void {
  const inspector = requiredElement<HTMLElement>("#job-inspector");
  clear(inspector);
  const header = node("div", "inspector-head");
  const title = node("div");
  const eyebrow = textNode("span", WORKFLOW_LABELS[job.workflow], "eyebrow");
  const heading = textNode("h2", compactId(job.job_id, 11));
  heading.title = job.job_id;
  title.append(eyebrow, heading);
  const actions = node("div", "inspector-actions");
  actions.append(statusBadge(job.status));
  if (!TERMINAL_STATUSES.has(job.status)) {
    const cancel = textNode("button", "Cancel job", "button button-ghost");
    cancel.type = "button";
    cancel.addEventListener("click", async () => {
      cancel.disabled = true;
      try {
        const response = await state.client.cancel(job.job_id);
        state.jobs.set(job.job_id, response.job);
        await refreshJob(job.job_id);
      } catch (error) {
        showToast(errorMessage(error), "error");
        cancel.disabled = false;
      }
    });
    actions.append(cancel);
  }
  header.append(title, actions);
  inspector.append(header, renderJobFacts(job));

  if (job.status === "succeeded" && job.result !== undefined) {
    inspector.append(renderResult(job.workflow, job.result));
  } else if (job.status === "failed" && job.error !== undefined) {
    const failure = node("section", "result-section failure-callout");
    failure.append(textNode("span", job.error.code, "eyebrow"), textNode("h3", "Workflow failed"), textNode("p", job.error.message));
    inspector.append(failure);
  } else if (job.status === "cancelled") {
    const cancelled = node("section", "result-section neutral-callout");
    cancelled.append(textNode("h3", "Workflow cancelled"), textNode("p", "No result was produced. Existing source artifacts are not deleted."));
    inspector.append(cancelled);
  } else {
    const pending = node("section", "result-section pending-callout");
    pending.append(node("span", "loader"), textNode("div", job.status === "queued" ? "Waiting for a worker" : "Processing inside the local worker", "pending-title"), textNode("p", `Attempt ${job.attempts} of ${job.max_attempts}. This view refreshes automatically.`));
    inspector.append(pending);
  }
  inspector.append(renderEvents(events));
}

function renderJobFacts(job: Job): HTMLElement {
  const facts = node("dl", "fact-strip");
  addFact(facts, "Created", formatDate(job.created_at));
  addFact(facts, "Attempts", `${job.attempts} / ${job.max_attempts}`);
  addFact(facts, "Request fingerprint", compactId(job.request_fingerprint, 8), job.request_fingerprint);
  return facts;
}

function addFact(container: HTMLElement, label: string, value: string, title?: string): void {
  const wrapper = node("div");
  wrapper.append(textNode("dt", label), textNode("dd", value));
  if (title !== undefined) wrapper.title = title;
  container.append(wrapper);
}

function renderResult(workflow: WorkflowName, result: JsonValue): HTMLElement {
  if (workflow === "ingest_document") return renderManifest(result);
  if (workflow === "answer_question") return renderAnswer(result);
  if (workflow === "evaluate_quality") return renderQuality(result);
  return renderRawResult(result);
}

function renderManifest(value: JsonValue): HTMLElement {
  const result = asRecord(value);
  if (result === null) return renderRawResult(value);
  const section = node("section", "result-section");
  section.append(sectionHeading("Source inspection", "Verified document identity and normalized page geometry."));
  const identity = node("div", "identity-card");
  const identityCopy = node("div");
  identityCopy.append(textNode("span", asString(result.media_type), "eyebrow"), textNode("h3", compactId(asString(result.document_id), 14)), textNode("p", `${formatNumber(asNumber(result.byte_size) ?? 0, 0)} bytes · ${formatNumber(asNumber(result.page_count) ?? 0, 0)} pages`));
  identityCopy.title = asString(result.document_id);
  const verified = node("div", "verified-seal");
  verified.append(textNode("span", "✓"), textNode("b", "Verified"), textNode("small", asString(result.fingerprint_algorithm, "SHA-256")));
  identity.append(identityCopy, verified);
  section.append(identity);

  const pages = asArray(result.pages);
  const tableWrap = node("div", "table-wrap");
  const table = node("table", "data-table");
  const head = node("thead");
  const headRow = node("tr");
  ["Page", "Page identity", "Dimensions", "Rotation"].forEach((label) => headRow.append(textNode("th", label)));
  head.append(headRow);
  const body = node("tbody");
  pages.forEach((item) => {
    const page = asRecord(item);
    if (page === null) return;
    const row = node("tr");
    row.append(
      textNode("td", String(asNumber(page.page_number) ?? "—")),
      titledText("td", compactId(asString(page.page_id), 8), asString(page.page_id)),
      textNode("td", `${formatNumber(asNumber(page.width) ?? 0)} × ${formatNumber(asNumber(page.height) ?? 0)} ${asString(page.dimension_unit, asString(page.unit, ""))}`),
      textNode("td", `${formatNumber(asNumber(page.rotation_degrees) ?? asNumber(page.rotation) ?? 0, 0)}°`),
    );
    body.append(row);
  });
  table.append(head, body);
  tableWrap.append(table);
  section.append(tableWrap, rawDetails(value));
  return section;
}

function renderAnswer(value: JsonValue): HTMLElement {
  const result = asRecord(value);
  if (result === null) return renderRawResult(value);
  const section = node("section", "result-section answer-result");
  const status = asString(result.status, "unknown");
  const intro = sectionHeading("Evidence answer", "Extractive output assembled only from the cited source slices.");
  intro.append(statusBadge(status));
  section.append(intro);

  const answerBox = node("div", status === "answered" ? "answer-box" : "answer-box abstained");
  answerBox.append(textNode("span", status === "answered" ? "Supported answer" : "Explicit abstention", "eyebrow"));
  if (status === "answered") {
    answerBox.append(textNode("blockquote", asString(result.answer, "No answer text returned.")));
  } else {
    answerBox.append(textNode("h3", "The evidence threshold was not met"), textNode("p", titleCase(asString(result.abstention_reason, "No supported excerpt"))));
  }
  section.append(answerBox);

  const retrieval = asRecord(result.retrieval);
  const hits = retrieval === null ? [] : asArray(retrieval.hits);
  const citations = asArray(result.citations);
  const evidenceHead = node("div", "subsection-head");
  evidenceHead.append(textNode("div", `${citations.length} cited source ${citations.length === 1 ? "slice" : "slices"}`, "subsection-title"), textNode("p", "Coverage measures matched query terms; it does not certify truth or completeness."));
  section.append(evidenceHead);
  const stack = node("div", "evidence-stack");
  citations.forEach((item, index) => {
    const citation = asRecord(item);
    if (citation === null) return;
    const rank = asNumber(citation.retrieval_rank);
    const matchedHit = hits.map(asRecord).find((hit) => hit !== null && asNumber(hit.rank) === rank) ?? null;
    stack.append(renderCitation(citation, matchedHit, index));
  });
  if (citations.length === 0) {
    const empty = node("div", "evidence-empty");
    empty.append(textNode("b", "No citation passed the configured threshold"), textNode("p", "Inspect retrieval candidates below to understand what was found."));
    stack.append(empty);
  }
  section.append(stack);
  if (retrieval !== null) section.append(renderRetrieval(retrieval));
  section.append(rawDetails(value));
  return section;
}

function renderCitation(citation: JsonObject, hit: JsonObject | null, index: number): HTMLElement {
  const card = node("article", "citation-card");
  const head = node("header");
  const label = node("div", "citation-label");
  label.append(textNode("span", String(index + 1), "citation-number"), textNode("div", `Evidence ${index + 1}`, "citation-title"));
  const coverage = asNumber(citation.query_term_coverage);
  head.append(label, textNode("span", coverage === null ? "Coverage —" : `${formatNumber(coverage * 100, 0)}% term coverage`, "coverage-chip"));
  const quote = textNode("blockquote", asString(citation.excerpt));
  const meta = node("dl", "evidence-meta");
  addFact(meta, "Page", String(hit === null ? "—" : (asNumber(hit.page_number) ?? "—")));
  addFact(meta, "Retrieval rank", String(asNumber(citation.retrieval_rank) ?? "—"));
  addFact(meta, "Character slice", `${asNumber(citation.excerpt_start) ?? "—"}–${asNumber(citation.excerpt_end) ?? "—"}`);
  addFact(meta, "Matched terms", asArray(citation.matched_terms).map(String).join(", ") || "None");
  card.append(head, quote, meta);
  if (hit !== null) {
    const provenance = node("details", "provenance");
    provenance.append(textNode("summary", "Page region and source provenance"));
    const body = node("div", "provenance-body");
    const box = asRecord(hit.bounding_box);
    body.append(
      detailLine("Chunk", asString(hit.chunk_id)),
      detailLine("Page ID", asString(hit.page_id)),
      detailLine("Coordinates", box === null ? "Unavailable" : `x ${asNumber(box.x0) ?? "—"}–${asNumber(box.x1) ?? "—"}, y ${asNumber(box.top) ?? "—"}–${asNumber(box.bottom) ?? "—"} ${asString(hit.dimension_unit)}`),
      detailLine("Origin", asString(hit.coordinate_origin)),
    );
    provenance.append(body);
    card.append(provenance);
  }
  return card;
}

function renderRetrieval(retrieval: JsonObject): HTMLElement {
  const details = node("details", "retrieval-details");
  const hits = asArray(retrieval.hits);
  details.append(textNode("summary", `Inspect ${hits.length} ranked retrieval ${hits.length === 1 ? "hit" : "hits"}`));
  const content = node("div", "retrieval-list");
  hits.forEach((item) => {
    const hit = asRecord(item);
    if (hit === null) return;
    const card = node("article", "retrieval-hit");
    const top = node("div", "retrieval-hit-top");
    top.append(textNode("b", `Rank ${asNumber(hit.rank) ?? "—"} · Page ${asNumber(hit.page_number) ?? "—"}`), textNode("span", `Score ${formatNumber(asNumber(hit.score) ?? 0, 4)}`, "score-chip"));
    card.append(top, textNode("p", asString(hit.text)), detailLine("Matched", asArray(hit.matched_terms).map(String).join(", ") || "None"));
    content.append(card);
  });
  details.append(content);
  return details;
}

function renderQuality(value: JsonValue): HTMLElement {
  const result = asRecord(value);
  if (result === null) return renderRawResult(value);
  const section = node("section", "result-section quality-result");
  const status = asString(result.status, "unknown");
  const intro = sectionHeading("Quality report", "Measured fixtures, explicit gates, and directional comparisons.");
  intro.append(statusBadge(status));
  section.append(intro);
  const summary = node("div", "quality-summary");
  summary.append(
    summaryDatum("Report", compactId(asString(result.report_id), 9), asString(result.report_id)),
    summaryDatum("Suite", compactId(asString(result.suite_id), 9), asString(result.suite_id)),
    summaryDatum("Baseline", result.baseline_report_id === null ? "Not supplied" : compactId(asString(result.baseline_report_id), 9), asString(result.baseline_report_id, "")),
  );
  section.append(summary);
  const metrics = asRecord(result.metrics);
  if (metrics !== null) section.append(renderMetricGroups(metrics));
  section.append(renderFindingGroup("Policy gates", asArray(result.gates), "No static gates were evaluated."));
  section.append(renderFindingGroup("Regressions", asArray(result.regressions), "No directional regressions were recorded."));
  section.append(renderFindingGroup("Findings", asArray(result.findings), "No findings were recorded."));
  section.append(rawDetails(value));
  return section;
}

function renderMetricGroups(metrics: JsonObject): HTMLElement {
  const wrapper = node("div", "metric-groups");
  wrapper.append(textNode("h3", "Measured signals"));
  Object.entries(metrics).forEach(([name, value]) => {
    const record = asRecord(value);
    const group = node("section", "metric-group");
    group.append(textNode("h4", titleCase(name)));
    const grid = node("div", "metric-grid");
    const entries = record === null ? [[name, value] as const] : Object.entries(record);
    entries.forEach(([key, metric]) => {
      if (typeof metric !== "number" && typeof metric !== "string" && typeof metric !== "boolean" && metric !== null) return;
      const item = node("div", "metric-card");
      const rendered = typeof metric === "number" ? formatNumber(metric, 4) : metric === null ? "—" : String(metric);
      item.append(textNode("span", titleCase(key)), textNode("b", rendered));
      grid.append(item);
    });
    group.append(grid);
    wrapper.append(group);
  });
  return wrapper;
}

function renderFindingGroup(title: string, items: JsonValue[], emptyText: string): HTMLElement {
  const section = node("section", "finding-group");
  section.append(textNode("h3", `${title} · ${items.length}`));
  if (items.length === 0) {
    section.append(textNode("p", emptyText, "muted"));
    return section;
  }
  const list = node("div", "finding-list");
  items.forEach((item) => {
    const record = asRecord(item);
    const card = node("article", "finding-card");
    if (record === null) {
      card.append(textNode("p", JSON.stringify(item)));
    } else {
      const labelValue = record.name ?? record.metric ?? record.code ?? record.status;
      card.append(textNode("b", typeof labelValue === "string" ? titleCase(labelValue) : "Recorded check"));
      const message = record.message ?? record.reason ?? record.detail;
      if (typeof message === "string") card.append(textNode("p", message));
      card.append(rawDetails(record, "Inspect check data"));
    }
    list.append(card);
  });
  section.append(list);
  return section;
}

function renderRawResult(value: JsonValue): HTMLElement {
  const section = node("section", "result-section");
  section.append(sectionHeading("Workflow result", "Canonical backend output."), rawDetails(value, "Inspect raw result", true));
  return section;
}

function rawDetails(value: JsonValue | JsonObject, label = "Inspect canonical JSON", open = false): HTMLDetailsElement {
  const details = node("details", "raw-details");
  details.open = open;
  details.append(textNode("summary", label));
  const pre = node("pre");
  pre.textContent = JSON.stringify(value, null, 2);
  details.append(pre);
  return details;
}

function sectionHeading(title: string, description: string): HTMLElement {
  const heading = node("div", "result-heading");
  const copy = node("div");
  copy.append(textNode("span", "Result", "eyebrow"), textNode("h3", title), textNode("p", description));
  heading.append(copy);
  return heading;
}

function summaryDatum(label: string, value: string, title?: string): HTMLElement {
  const item = node("div");
  item.append(textNode("span", label), textNode("b", value));
  if (title !== undefined) item.title = title;
  return item;
}

function titledText<K extends keyof HTMLElementTagNameMap>(tag: K, value: string, title: string): HTMLElementTagNameMap[K] {
  const element = textNode(tag, value);
  element.title = title;
  return element;
}

function detailLine(label: string, value: string): HTMLElement {
  const line = node("p", "detail-line");
  line.append(textNode("b", label), document.createTextNode(value));
  return line;
}

function renderEvents(events: JobEvent[]): HTMLElement {
  const section = node("section", "events-section");
  const heading = node("div", "subsection-head");
  heading.append(textNode("div", "Lifecycle events", "subsection-title"), textNode("p", `${events.length} ordered event${events.length === 1 ? "" : "s"}`));
  section.append(heading);
  const timeline = node("ol", "timeline");
  events.forEach((event) => {
    const item = node("li");
    const marker = textNode("span", String(event.sequence), "timeline-marker");
    const copy = node("div");
    copy.append(textNode("b", titleCase(event.event_type)), textNode("time", formatDate(event.occurred_at)));
    const details = Object.keys(event.detail).length > 0 ? rawDetails(event.detail, "Event detail") : null;
    item.append(marker, copy);
    if (details !== null) copy.append(details);
    timeline.append(item);
  });
  if (events.length === 0) timeline.append(textNode("li", "No lifecycle events returned yet.", "muted"));
  section.append(timeline);
  return section;
}

async function refreshSystem(): Promise<void> {
  const content = requiredElement<HTMLDivElement>("#system-content");
  if (!state.connected) return;
  clear(content);
  const loading = node("div", "panel empty-state");
  loading.append(node("span", "loader"), textNode("h2", "Reading system counters"));
  content.append(loading);
  try {
    const [ready, response] = await Promise.all([state.client.ready(), state.client.metrics()]);
    renderSystem(ready, response.metrics);
  } catch (error) {
    clear(content);
    const failure = node("div", "panel empty-state error-state");
    failure.append(textNode("span", "!", "empty-mark"), textNode("h2", "System status unavailable"), textNode("p", errorMessage(error)));
    content.append(failure);
  }
}

function renderSystem(ready: boolean, metrics: Metrics): void {
  const content = requiredElement<HTMLDivElement>("#system-content");
  clear(content);
  const readiness = node("section", "panel readiness-card");
  readiness.append(textNode("span", "Readiness", "eyebrow"), textNode("h2", ready ? "Backend ready" : "Backend unavailable"), textNode("p", ready ? "Persistence and workflow handlers are prepared." : "The service did not report ready."), statusBadge(ready ? "ready" : "unavailable"));
  const counters = node("section", "panel counters-panel");
  counters.append(textNode("span", "Persistent queue", "eyebrow"), textNode("h2", "Job outcomes"));
  const grid = node("div", "counter-grid");
  (["queued", "running", "succeeded", "failed", "cancelled", "total_events"] as const).forEach((key) => {
    const item = node("div", "counter-card");
    item.append(textNode("span", titleCase(key)), textNode("b", formatNumber(metrics[key], 0)));
    grid.append(item);
  });
  counters.append(grid);
  const boundary = node("section", "panel boundary-panel");
  boundary.append(textNode("span", "Deployment boundary", "eyebrow"), textNode("h2", "Loopback only"), textNode("p", "The built-in server is designed for one local host. It does not provide TLS, user accounts, per-user authorization, or process isolation."));
  content.append(readiness, counters, boundary);
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return `${error.message} (${error.code})`;
  if (error instanceof Error) return error.message;
  return "An unexpected error occurred.";
}

const initialView = window.location.hash.slice(1);
if (["workspace", "activity", "system"].includes(initialView)) setView(initialView);
renderJobList();
void state.client.ready().then(
  (ready) => setConnection(false, ready ? "Backend found · token required" : "Backend unavailable"),
  () => setConnection(false, "Backend unavailable"),
);
