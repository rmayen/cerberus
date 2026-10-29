/** Join class names, skipping falsy values. */
export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/**
 * The API returns naive timestamps for SQLite-backed records (no zone suffix).
 * Backend timestamps are UTC, so treat a zone-less value as UTC before formatting.
 */
export function parseApiDate(value: string): Date {
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasZone ? value : `${value}Z`);
}

const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = parseApiDate(value);
  return Number.isNaN(d.getTime()) ? "—" : dateTimeFormat.format(d);
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}

/** Turn snake_case API identifiers into readable labels, for example file_hash -> File hash. */
export function labelize(value: string): string {
  const text = value.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Readable rendering of a conditions object. Values are shown as text only. */
export function describeConditions(conditions: Record<string, unknown>): string {
  const entries = Object.entries(conditions);
  if (entries.length === 0) return "Executor defaults";
  return entries.map(([k, v]) => `${k}=${formatValue(v)}`).join(", ");
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "not set";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return JSON.stringify(value);
}

/** Stable JSON for comparing condition objects regardless of key order. */
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>).sort();
    return `{${keys
      .map((k) => `${JSON.stringify(k)}:${canonicalJson((value as Record<string, unknown>)[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value ?? null);
}

export function plural(n: number, singular: string, pluralForm = `${singular}s`): string {
  return `${n} ${n === 1 ? singular : pluralForm}`;
}

/** Message for an unknown thrown value, without leaking internals. */
export function errorMessage(err: unknown, fallback = "The request failed. Try again."): string {
  if (err instanceof Error && err.name === "AbortError") return "";
  if (err instanceof Error && err.name === "ApiError") return err.message;
  if (err instanceof TypeError) return "Cannot reach the server. Check your connection.";
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}
