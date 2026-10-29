import {
  AlertCircle,
  Ban,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronsUp,
  Clock,
  Copy,
  Equal,
  Loader2,
  TimerOff,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { cn } from "../../lib/format";
import {
  analysisStatusMeta,
  jobStatusMeta,
  sampleStatusMeta,
  severityMeta,
  confidenceLevel,
  type Meta,
  type Tone,
} from "../../lib/status";

// ---------- Buttons ----------

type ButtonVariant = "primary" | "secondary" | "ghost" | "link";

export function buttonClass(
  variant: ButtonVariant = "secondary",
  size: "md" | "sm" = "md",
  extra?: string
): string {
  return cn("btn", `btn-${variant}`, size === "sm" && "btn-sm", extra);
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "md" | "sm";
  icon?: LucideIcon;
}

export function Button({ variant = "secondary", size = "md", icon: Icon, className, children, ...rest }: ButtonProps) {
  return (
    <button type="button" className={buttonClass(variant, size, className)} {...rest}>
      {Icon && <Icon size={16} aria-hidden="true" />}
      {children}
    </button>
  );
}

// ---------- Badges ----------

export function Badge({
  tone = "neutral",
  icon: Icon,
  children,
  className,
  title,
}: {
  tone?: Tone | "ok" | "run" | "warn" | "err" | "neutral" | "tag";
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  const toneClass = tone === "tag" ? "badge-tag" : `badge-${tone}`;
  return (
    <span className={cn("badge", toneClass, className)} title={title}>
      {Icon && <Icon size={13} aria-hidden="true" />}
      <span>{children}</span>
    </span>
  );
}

const SEVERITY_ICON: Record<string, LucideIcon> = {
  high: ChevronsUp,
  medium: Equal,
  low: ChevronDown,
};

export function SeverityBadge({ severity }: { severity: string }) {
  const meta: Meta = severityMeta(severity);
  const label = meta.label === "Unrated" ? "Unrated severity" : `${meta.label} severity`;
  return (
    <Badge tone={meta.tone} icon={SEVERITY_ICON[severity] ?? Clock}>
      {label}
    </Badge>
  );
}

const JOB_ICON: Record<string, LucideIcon> = {
  pending: Clock,
  running: Loader2,
  completed: CheckCircle2,
  failed: XCircle,
  timed_out: TimerOff,
  cancelled: Ban,
};

export function JobStatusBadge({ status }: { status: string }) {
  const meta = jobStatusMeta(status);
  return (
    <Badge tone={meta.tone} icon={JOB_ICON[status] ?? AlertCircle}>
      {meta.label}
    </Badge>
  );
}

export function SampleStatusBadge({ status }: { status: string }) {
  const meta = sampleStatusMeta(status);
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}

export function AnalysisStatusBadge({ status }: { status: string }) {
  const meta = analysisStatusMeta(status);
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}

export function ConfidenceMeter({ confidence }: { confidence: string }) {
  const level = confidenceLevel(confidence);
  const label = level === 0 ? "Unknown confidence" : `${confidence.charAt(0).toUpperCase()}${confidence.slice(1)} confidence`;
  return (
    <span className="confidence">
      <span className="confidence-meter" aria-hidden="true">
        {[1, 2, 3].map((n) => (
          <span key={n} className={n <= level ? "on" : undefined} />
        ))}
      </span>
      <span>{label}</span>
    </span>
  );
}

// ---------- Surfaces ----------

export function Panel({
  title,
  description,
  actions,
  footer,
  children,
  flush,
  className,
  id,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  children?: ReactNode;
  flush?: boolean;
  className?: string;
  id?: string;
}) {
  const headingId = useId();
  return (
    <section id={id} className={cn("panel", className)} aria-labelledby={title ? headingId : undefined}>
      {(title || actions) && (
        <div className="panel-header">
          <div style={{ minWidth: 0 }}>
            {title && (
              <h2 id={headingId} className="text-[1rem]">
                {title}
              </h2>
            )}
            {description && <p className="panel-desc">{description}</p>}
          </div>
          {actions && <div className="page-actions">{actions}</div>}
        </div>
      )}
      <div className={flush ? "panel-body-flush" : "panel-body"}>{children}</div>
      {footer && <div className="panel-footer">{footer}</div>}
    </section>
  );
}

export function StatTile({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="panel stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
      {hint && <span className="text-xs muted">{hint}</span>}
    </div>
  );
}

export function KeyValue({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="kv">
      {items.map((item) => (
        <div key={item.label} style={{ display: "contents" }}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Notice({
  tone = "info",
  children,
  icon,
  role,
}: {
  tone?: "info" | "ok" | "err" | "warn";
  children: ReactNode;
  icon?: LucideIcon;
  role?: "status" | "alert";
}) {
  const Icon = icon ?? (tone === "ok" ? Check : AlertCircle);
  return (
    <div
      className={cn("notice", tone === "ok" && "notice-ok", tone === "err" && "notice-err", tone === "warn" && "notice-warn")}
      role={role ?? (tone === "err" ? "alert" : "status")}
    >
      <Icon size={16} aria-hidden="true" style={{ flex: "none", marginTop: 2 }} />
      <div>{children}</div>
    </div>
  );
}

// ---------- States ----------

export function LoadingBlock({ label = "Loading", rows = 3, height = 18 }: { label?: string; rows?: number; height?: number }) {
  return (
    <div role="status" aria-live="polite" className="panel-body" style={{ display: "grid", gap: 10 }}>
      <span className="sr-only">{label}…</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" aria-hidden="true" style={{ height, width: `${92 - i * 14}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon: LucideIcon;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon" aria-hidden="true">
        <Icon size={18} />
      </div>
      <h3>{title}</h3>
      {children && <p className="text-sm" style={{ maxWidth: "52ch" }}>{children}</p>}
      {action && <div style={{ marginTop: 6 }}>{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={18} aria-hidden="true" style={{ flex: "none" }} />
      <div>{message}</div>
      {onRetry && (
        <Button variant="ghost" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

// ---------- Copy and hashes ----------

export function CopyButton({ value, label }: { value: string; label: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      setState("failed");
    }
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState("idle"), 1600);
  }, [value]);

  return (
    <>
      <button type="button" className="btn btn-ghost btn-sm" onClick={copy} aria-label={`Copy ${label}`}>
        {state === "copied" ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
        <span aria-hidden="true">{state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "Copy"}</span>
      </button>
      <span className="sr-only" role="status" aria-live="polite">
        {state === "copied" ? `${label} copied` : state === "failed" ? `Could not copy ${label}` : ""}
      </span>
    </>
  );
}

/** Monospace value with a copy control. Rendered as text, never as markup. */
export function HashValue({ value, label, compact }: { value: string; label: string; compact?: boolean }) {
  return (
    <span style={{ display: "inline-flex", flexWrap: "wrap", alignItems: "center", gap: 8, maxWidth: "100%" }}>
      <span className="hash" style={compact ? { wordBreak: "break-all" } : undefined}>
        {value}
      </span>
      <CopyButton value={value} label={label} />
    </span>
  );
}

// ---------- Tables ----------

export function TableScroll({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="table-scroll" role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}

export type SortDir = "ascending" | "descending";

export function useSort<K extends string>(initial: K, initialDir: SortDir = "ascending") {
  const [key, setKey] = useState<K>(initial);
  const [dir, setDir] = useState<SortDir>(initialDir);
  function toggle(next: K) {
    if (next === key) setDir(dir === "ascending" ? "descending" : "ascending");
    else {
      setKey(next);
      setDir("ascending");
    }
  }
  return { key, dir, toggle };
}

export function SortableTh<K extends string>({
  label,
  sortKey,
  active,
  dir,
  onSort,
  className,
}: {
  label: string;
  sortKey: K;
  active: K;
  dir: SortDir;
  onSort: (k: K) => void;
  className?: string;
}) {
  const isActive = active === sortKey;
  return (
    <th scope="col" className={className} aria-sort={isActive ? dir : "none"}>
      <button type="button" className="sort-btn" onClick={() => onSort(sortKey)}>
        {label}
        <span aria-hidden="true" className="muted">
          {isActive ? (dir === "ascending" ? "▲" : "▼") : "↕"}
        </span>
      </button>
    </th>
  );
}

// ---------- Icons used by several pages ----------
export { ChevronDown, Copy, Check };
