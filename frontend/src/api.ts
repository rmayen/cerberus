const TOKEN_KEY = "cerberus_token";
export const SESSION_EXPIRED_EVENT = "cerberus:session-expired";

// localStorage can throw (private windows, blocked storage); the app must still render.
export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* session lasts only for this page */
  }
}
export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* nothing to clear */
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const FALLBACK_BY_STATUS: Record<number, string> = {
  400: "The server rejected the request.",
  401: "Your session is no longer valid. Sign in again.",
  403: "Your role does not allow this action.",
  404: "The requested item was not found.",
  409: "This conflicts with an existing item.",
  413: "The file exceeds the maximum allowed size.",
  422: "The server could not accept this input.",
  500: "The server failed while handling the request.",
  503: "The service is temporarily unavailable.",
};

function messageFromDetail(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return FALLBACK_BY_STATUS[status] ?? `Request failed (${status}).`;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
}

async function rawFetch(path: string, opts: RequestOptions): Promise<Response> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }

  const res = await fetch(`/api/v1${path}`, {
    method: opts.method ?? "GET",
    headers,
    body,
    signal: opts.signal,
  });

  if (res.status === 401 && !path.startsWith("/auth/login") && token) {
    clearToken();
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(res.status, messageFromDetail(detail, res.status));
  }
  return res;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await rawFetch(path, opts);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Save an authenticated download (IOC export, PDF) without putting the token in a URL. */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const res = await rawFetch(path, {});
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = match ? match[1] : fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Fetch a text document (for example the HTML report) with the bearer token. */
export async function fetchText(path: string, signal?: AbortSignal): Promise<string> {
  // rawFetch already throws on error responses, so an error body is never returned as content.
  const res = await rawFetch(path, { signal });
  return res.text();
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", form }),
};

// --- Domain types (mirror backend/app/schemas.py and models.py) ---

export type Role = "viewer" | "analyst" | "administrator";
export type JobStatus = "pending" | "running" | "completed" | "failed" | "timed_out" | "cancelled";
export type SampleStatus = "quarantined" | "approved" | "analyzing" | "analyzed" | "failed";
// Derived by the API from the sample's latest analysis job. Separate from SampleStatus.
export type AnalysisStatus = "not_analyzed" | "analyzing" | "analyzed" | "failed";
export type Severity = "low" | "medium" | "high";
export type Confidence = "low" | "medium" | "high";
export type IocType =
  | "domain"
  | "ip"
  | "url"
  | "file_hash"
  | "registry_key"
  | "mutex"
  | "service"
  | "file_path";
export type TelemetryCategory =
  | "process"
  | "file"
  | "registry"
  | "service"
  | "scheduled_task"
  | "dll"
  | "dns"
  | "network"
  | "http"
  | "tls"
  | "mutex"
  | "persistence";

export interface User {
  id: number;
  username: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface Sample {
  id: number;
  sha256: string;
  filename: string;
  size_bytes: number;
  content_type: string | null;
  detected_type: string | null;
  status: SampleStatus;
  analysis_status: AnalysisStatus;
  tags: string[];
  case_id: number | null;
  uploaded_by: number | null;
  created_at: string;
}

export interface SampleUploadResult {
  sample: Sample;
  duplicate: boolean;
}

export interface Case {
  id: number;
  name: string;
  description: string | null;
  created_by: number | null;
  created_at: string;
}

export interface Job {
  id: number;
  sample_id: number;
  executor: string;
  conditions: Record<string, unknown>;
  status: JobStatus;
  result: Record<string, unknown> | null;
  error: string | null;
  duration_ms: number | null;
  submitted_by: number | null;
  // Set on jobs that belong to a differential analysis.
  differential_id: number | null;
  differential_role: "baseline" | "variant" | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface TelemetryEvent {
  id: number;
  job_id: number;
  sequence: number;
  category: TelemetryCategory;
  action: string;
  target: string;
  raw: Record<string, unknown>;
  created_at: string;
}

export interface Finding {
  id: number;
  job_id: number;
  category: string;
  title: string;
  severity: Severity;
  explanation: string;
  evidence: Record<string, unknown>[];
  created_at: string;
}

export interface AttackMapping {
  id: number;
  job_id: number;
  technique_id: string;
  technique_name: string;
  tactic: string;
  explanation: string;
  evidence: Record<string, unknown>[];
  created_at: string;
}

export interface Ioc {
  id: number;
  type: IocType;
  value: string;
  source_job_id: number | null;
  first_seen: string;
}

export interface DiffEvent {
  category: string;
  action: string;
  target: string;
}

export interface DifferentialFinding {
  id: number;
  axis: string;
  baseline_value: unknown;
  variant_value: unknown;
  summary: string;
  confidence: Confidence;
  added: DiffEvent[];
  removed: DiffEvent[];
  created_at: string;
}

export interface Differential {
  id: number;
  sample_id: number;
  executor: string;
  baseline_conditions: Record<string, unknown>;
  status: JobStatus;
  created_by: number | null;
  created_at: string;
  finished_at: string | null;
  error_message: string | null;
  findings: DifferentialFinding[];
}
