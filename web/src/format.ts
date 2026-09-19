import type { JobStatus, JsonObject, JsonValue, WorkflowName } from "./types";

export const TERMINAL_STATUSES = new Set<JobStatus>(["succeeded", "failed", "cancelled"]);

export const WORKFLOW_LABELS: Record<WorkflowName, string> = {
  ingest_document: "Document intake",
  answer_question: "Evidence answer",
  evaluate_quality: "Quality evaluation",
};

export function compactId(value: string, visible = 12): string {
  if (value.length <= visible * 2 + 1) return value;
  return `${value.slice(0, visible)}…${value.slice(-visible)}`;
}

export function formatDate(value: string | null): string {
  if (value === null) return "Not yet";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(date);
}

export function formatNumber(value: number, digits = 2): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(value);
}

export function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

export function asRecord(value: JsonValue | undefined): JsonObject | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : null;
}

export function asArray(value: JsonValue | undefined): JsonValue[] {
  return Array.isArray(value) ? value : [];
}

export function asString(value: JsonValue | undefined, fallback = "—"): string {
  return typeof value === "string" ? value : fallback;
}

export function asNumber(value: JsonValue | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function parseJsonObject(source: string, label: string): JsonObject {
  let value: unknown;
  try {
    value = JSON.parse(source) as unknown;
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return value as JsonObject;
}
