import type {
  Job,
  JobEvent,
  JobSubmission,
  JsonObject,
  Metrics,
  PublicError,
} from "./types";

interface ErrorEnvelope {
  error?: PublicError;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export class PageTraceClient {
  #token: string;

  constructor(token: string) {
    this.#token = token;
  }

  setToken(token: string): void {
    this.#token = token;
  }

  async ready(): Promise<boolean> {
    const response = await fetch("/readyz", {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    return response.ok;
  }

  async submit(submission: JobSubmission): Promise<{ created: boolean; job: Job }> {
    return this.#request("/v1/jobs", {
      method: "POST",
      body: JSON.stringify(submission),
    });
  }

  async job(jobId: string): Promise<{ job: Job }> {
    return this.#request(`/v1/jobs/${encodeURIComponent(jobId)}`);
  }

  async events(jobId: string, afterSequence = 0): Promise<{ events: JobEvent[] }> {
    const query = new URLSearchParams({
      after_sequence: String(afterSequence),
      limit: "100",
    });
    return this.#request(`/v1/jobs/${encodeURIComponent(jobId)}/events?${query.toString()}`);
  }

  async cancel(jobId: string): Promise<{ job: Job }> {
    return this.#request(`/v1/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
      body: "{}",
    });
  }

  async metrics(): Promise<{ metrics: Metrics }> {
    return this.#request("/v1/metrics");
  }

  async #request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    headers.set("Authorization", `Bearer ${this.#token}`);
    if (init.body !== undefined) {
      headers.set("Content-Type", "application/json; charset=utf-8");
    }
    const response = await fetch(path, { ...init, cache: "no-store", headers });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new ApiError(response.status, "invalid_response", "The backend returned invalid JSON.");
    }
    if (!response.ok) {
      const envelope = isObject(payload) ? (payload as ErrorEnvelope) : {};
      const error = envelope.error;
      throw new ApiError(
        response.status,
        typeof error?.code === "string" ? error.code : "request_failed",
        typeof error?.message === "string" ? error.message : `Request failed (${response.status}).`,
      );
    }
    return payload as T;
  }
}

export function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
