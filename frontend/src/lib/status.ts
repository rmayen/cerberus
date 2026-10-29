import type { AnalysisStatus, Confidence, JobStatus, SampleStatus, Severity } from "../api";

/**
 * Visual tones. Every tone is paired with a text label and an icon at the call site,
 * so meaning never depends on color alone.
 */
export type Tone =
  | "ok"
  | "run"
  | "warn"
  | "err"
  | "neutral"
  | "sev-high"
  | "sev-medium"
  | "sev-low"
  | "sev-none";

export interface Meta {
  label: string;
  tone: Tone;
}

export const JOB_STATUS: Record<JobStatus, Meta> = {
  pending: { label: "Queued", tone: "warn" },
  running: { label: "Running", tone: "run" },
  completed: { label: "Completed", tone: "ok" },
  failed: { label: "Failed", tone: "err" },
  timed_out: { label: "Timed out", tone: "err" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export const SAMPLE_STATUS: Record<SampleStatus, Meta> = {
  quarantined: { label: "Quarantined", tone: "warn" },
  approved: { label: "Approved", tone: "run" },
  analyzing: { label: "Analyzing", tone: "run" },
  analyzed: { label: "Analyzed", tone: "ok" },
  failed: { label: "Failed", tone: "err" },
};

export const ANALYSIS_STATUS: Record<AnalysisStatus, Meta> = {
  not_analyzed: { label: "Not analyzed", tone: "neutral" },
  analyzing: { label: "Analyzing", tone: "run" },
  analyzed: { label: "Analyzed", tone: "ok" },
  failed: { label: "Failed", tone: "err" },
};

export const SEVERITY: Record<Severity, Meta> = {
  high: { label: "High", tone: "sev-high" },
  medium: { label: "Medium", tone: "sev-medium" },
  low: { label: "Low", tone: "sev-low" },
};

export const SEVERITY_ORDER: Severity[] = ["high", "medium", "low"];

export const CONFIDENCE_ORDER: Confidence[] = ["high", "medium", "low"];

/** Fallbacks for values the API may add later; shown neutrally instead of guessed. */
export function jobStatusMeta(status: string): Meta {
  return (JOB_STATUS as Record<string, Meta>)[status] ?? { label: status, tone: "neutral" };
}

export function sampleStatusMeta(status: string): Meta {
  return (SAMPLE_STATUS as Record<string, Meta>)[status] ?? { label: status, tone: "neutral" };
}

export function analysisStatusMeta(status: string): Meta {
  return (ANALYSIS_STATUS as Record<string, Meta>)[status] ?? { label: status, tone: "neutral" };
}

export function severityMeta(severity: string): Meta {
  return (SEVERITY as Record<string, Meta>)[severity] ?? { label: "Unrated", tone: "sev-none" };
}

/** 3 = high, 2 = medium, 1 = low, 0 = unknown. */
export function confidenceLevel(confidence: string): number {
  const index = CONFIDENCE_ORDER.indexOf(confidence as Confidence);
  return index < 0 ? 0 : CONFIDENCE_ORDER.length - index;
}

/** Hex values for charts. Keep in step with the severity and status tokens in styles.css. */
export const TONE_HEX: Record<Tone, string> = {
  ok: "#6fd69a",
  run: "#8db4ff",
  warn: "#f2c26b",
  err: "#ff9a9a",
  neutral: "#8b93a5",
  "sev-high": "#ff8f8f",
  "sev-medium": "#f2c26b",
  "sev-low": "#6fd3c0",
  "sev-none": "#8b93a5",
};

/** Only ATT&CK technique ids (T1234 or T1234.567) become links to the public ATT&CK site. */
export function attackUrl(techniqueId: string): string | null {
  if (!/^T\d{4}(\.\d{3})?$/.test(techniqueId)) return null;
  return `https://attack.mitre.org/techniques/${techniqueId.replace(".", "/")}/`;
}
