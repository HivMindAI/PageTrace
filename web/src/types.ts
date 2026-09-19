export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export type WorkflowName = "ingest_document" | "answer_question" | "evaluate_quality";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface PublicError {
  code: string;
  message: string;
}

export interface Job {
  attempts: number;
  cancellation_requested: boolean;
  created_at: string;
  error?: PublicError;
  finished_at: string | null;
  job_id: string;
  max_attempts: number;
  request_fingerprint: string;
  result?: JsonValue;
  started_at: string | null;
  status: JobStatus;
  updated_at: string;
  workflow: WorkflowName;
}

export interface JobEvent {
  detail: JsonObject;
  event_type: string;
  occurred_at: string;
  sequence: number;
}

export interface Metrics {
  cancelled: number;
  failed: number;
  queued: number;
  running: number;
  succeeded: number;
  total_events: number;
}

export interface JobSubmission {
  workflow: WorkflowName;
  request: JsonObject;
  idempotency_key: string;
  max_attempts?: number;
}
