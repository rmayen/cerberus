import { FileSearch, GitCompare, ListChecks } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, type Case, type Confidence, type Differential, type Finding, type Job, type Sample } from "../api";
import { CountBars, StatusDonut } from "../components/LazyCharts";
import type { ChartItem } from "../components/Charts";
import { PageHeader } from "../components/PageHeader";
import {
  ConfidenceMeter,
  EmptyState,
  ErrorState,
  JobStatusBadge,
  LoadingBlock,
  Panel,
  SeverityBadge,
  buttonClass,
} from "../components/ui/primitives";
import { plural, formatDateTime } from "../lib/format";
import { useResource, type Resource } from "../lib/useResource";
import { useTitle } from "../lib/useTitle";
import { useEffect, useState } from "react";
import { CONFIDENCE_ORDER, SAMPLE_STATUS, SEVERITY_ORDER, severityMeta, type Tone } from "../lib/status";

/** The API has no aggregate findings endpoint, so findings come from this many recent completed jobs. */
const RECENT_COMPLETED_FOR_FINDINGS = 10;

interface ActivityRow {
  key: string;
  when: string;
  node: ReactNode;
}

interface FindingsSnapshot {
  items: Finding[];
  failed: number;
  jobs: number;
}

/** A stat value while its request is in flight (skeleton) or failed (dash). */
function statValue<T>(res: Resource<T>, pick: (data: T) => ReactNode): ReactNode {
  if (res.data !== undefined) return pick(res.data);
  if (res.error) return "—";
  return <span className="skeleton" aria-hidden="true" style={{ display: "inline-block", width: 56, height: 28 }} />;
}

/** Tracks a media query. Keeps the findings preview count in step with the viewport. */
function useMediaMatch(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

export function Overview() {
  useTitle("Overview");
  const narrow = useMediaMatch("(max-width: 639px)");
  const [showAllFindings, setShowAllFindings] = useState(false);
  const samples = useResource<Sample[]>((s) => api.get("/samples", s), []);
  const jobs = useResource<Job[]>((s) => api.get("/jobs", s), []);
  const cases = useResource<Case[]>((s) => api.get("/cases", s), []);
  const diffs = useResource<Differential[]>((s) => api.get("/differential", s), []);

  const sortedJobs = jobs.data
    ? [...jobs.data].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))
    : undefined;
  const recentCompleted = sortedJobs?.filter((j) => j.status === "completed").slice(0, RECENT_COMPLETED_FOR_FINDINGS);
  const recentIds = recentCompleted?.map((j) => j.id).join(",") ?? "";

  const findings = useResource<FindingsSnapshot | null>(
    async (signal) => {
      if (!recentCompleted) return null;
      const settled = await Promise.allSettled(
        recentCompleted.map((j) => api.get<Finding[]>(`/jobs/${j.id}/findings`, signal))
      );
      const items: Finding[] = [];
      let failed = 0;
      for (const r of settled) {
        if (r.status === "fulfilled") items.push(...r.value);
        else failed += 1;
      }
      items.sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
      return { items, failed, jobs: recentCompleted.length };
    },
    [recentIds, jobs.data === undefined]
  );

  const jobCounts = countBy(jobs.data ?? [], (j) => j.status);
  const stateItems: ChartItem[] = [
    { key: "completed", label: "Completed", value: jobCounts.completed ?? 0, tone: "ok" },
    { key: "pending", label: "Queued", value: jobCounts.pending ?? 0, tone: "warn" },
    { key: "running", label: "Running", value: jobCounts.running ?? 0, tone: "run" },
    { key: "failed", label: "Failed", value: jobCounts.failed ?? 0, tone: "err" },
    { key: "timed_out", label: "Timed out", value: jobCounts.timed_out ?? 0, tone: "err" },
    { key: "cancelled", label: "Cancelled", value: jobCounts.cancelled ?? 0, tone: "neutral" },
  ];

  const sevCounts = countBy(findings.data?.items ?? [], (f) => f.severity);
  const severityItems: ChartItem[] = SEVERITY_ORDER.map((sev) => ({
    key: sev,
    label: severityMeta(sev).label,
    value: sevCounts[sev] ?? 0,
    tone: severityMeta(sev).tone as Tone,
  }));

  const sampleCounts = countBy(samples.data ?? [], (x) => x.status);
  const sampleItems: ChartItem[] = (Object.keys(SAMPLE_STATUS) as (keyof typeof SAMPLE_STATUS)[]).map((st) => ({
    key: st,
    label: SAMPLE_STATUS[st].label,
    value: sampleCounts[st] ?? 0,
    tone: SAMPLE_STATUS[st].tone,
  }));

  const activity = buildActivity(sortedJobs ?? [], diffs.data ?? [], samples.data ?? []);
  const nothingYet = samples.data?.length === 0 && jobs.data?.length === 0;
  const firstError = samples.error ?? jobs.error ?? cases.error ?? null;

  const sampleName = new Map((samples.data ?? []).map((x) => [x.id, x.filename] as const));
  const jobSample = new Map((jobs.data ?? []).map((j) => [j.id, j.sample_id] as const));
  const sortedDiffs = [...(diffs.data ?? [])].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
  const failedCount = (jobCounts.failed ?? 0) + (jobCounts.timed_out ?? 0);

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Current state of samples, jobs and differential runs, as returned by the Cerberus API when this page loaded."
        actions={
          <>
            <Link className={buttonClass("secondary")} to="/samples">
              <FileSearch size={16} aria-hidden="true" /> Samples
            </Link>
            <Link className={buttonClass("ghost")} to="/jobs">
              <ListChecks size={16} aria-hidden="true" /> All jobs
            </Link>
          </>
        }
      />

      {firstError && (
        <div style={{ marginBottom: 16 }}>
          <ErrorState
            message={firstError}
            onRetry={() => {
              samples.reload();
              jobs.reload();
              cases.reload();
              diffs.reload();
            }}
          />
        </div>
      )}

      <section aria-label="Summary" className="ov-summary">
        <SummaryCell label="Failed or timed out" value={statValue(jobs, () => failedCount)} tone={failedCount ? "err" : undefined} />
        <SummaryCell label="Running" value={statValue(jobs, () => jobCounts.running ?? 0)} />
        <SummaryCell label="Queued" value={statValue(jobs, () => jobCounts.pending ?? 0)} />
        <SummaryCell label="Completed jobs" value={statValue(jobs, () => jobCounts.completed ?? 0)} hint={statValue(jobs, (d) => `of ${plural(d.length, "job")}`)} />
        <SummaryCell label="Samples" value={statValue(samples, (d) => d.length)} hint={statValue(cases, (c) => plural(c.length, "case"))} />
        <SummaryCell label="Differential runs" value={statValue(diffs, (d) => d.length)} />
      </section>

      {nothingYet ? (
        <div style={{ marginTop: 22 }}>
          <Panel>
            <EmptyState icon={FileSearch} title="No samples have been analyzed yet">
              Upload a sample from the Samples page to start an analysis. Viewer accounts can read results but cannot upload or run analyses.
            </EmptyState>
          </Panel>
        </div>
      ) : (
        <div className="ov-main">
          <div className="ov-center">
            <Panel
              title="Recent findings"
              description={findingsDescription(findings)}
              flush
              actions={
                <Link className="text-sm" to="/samples">
                  All samples
                </Link>
              }
            >
              {findings.error ? (
                <div className="ov-pad"><ErrorState message={findings.error} onRetry={findings.reload} /></div>
              ) : !findings.data ? (
                <div className="ov-pad"><LoadingBlock rows={4} /></div>
              ) : findings.data.items.length === 0 ? (
                <div className="ov-pad muted text-sm">
                  {findings.data.jobs === 0
                    ? "No completed jobs yet, so there are no findings to show."
                    : "The recent completed jobs produced no behavior findings."}
                </div>
              ) : (
                <>
                  <div className="ov-row ov-row-head" aria-hidden="true">
                    <span>Severity</span>
                    <span>Finding</span>
                    <span>Sample</span>
                    <span>Recorded</span>
                  </div>
                  <ul className="ov-list" aria-label="Recent findings" id="ov-findings-list">
                    {(showAllFindings ? findings.data.items : findings.data.items.slice(0, narrow ? 5 : 10)).map((f) => (
                      <li key={f.id} className="ov-row">
                        <span><SeverityBadge severity={f.severity} /></span>
                        <span className="ov-title">
                          <Link to={`/jobs/${f.job_id}#finding-${f.id}`}>{f.title}</Link>
                          <span className="ov-sub text-xs muted">{f.category}</span>
                        </span>
                        <span className="ov-sample">
                          {jobSample.get(f.job_id) != null ? (
                            <Link to={`/samples/${jobSample.get(f.job_id)}`}>
                              {sampleName.get(jobSample.get(f.job_id)!) ?? `sample #${jobSample.get(f.job_id)}`}
                            </Link>
                          ) : (
                            <span className="muted">unknown sample</span>
                          )}
                        </span>
                        <span className="ov-recorded">
                          <time className="ov-time text-xs" dateTime={f.created_at}>{formatDateTime(f.created_at)}</time>
                          <Link className="text-xs" to={`/jobs/${f.job_id}`}>Job #{f.job_id}</Link>
                        </span>
                      </li>
                    ))}
                  </ul>
                  {findings.data.items.length > (narrow ? 5 : 10) && (
                    <div className="ov-pad ov-more">
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        aria-expanded={showAllFindings}
                        aria-controls="ov-findings-list"
                        onClick={() => setShowAllFindings((v) => !v)}
                      >
                        {showAllFindings ? "Show fewer findings" : `Show all ${findings.data.items.length} findings`}
                      </button>
                    </div>
                  )}
                </>
              )}
            </Panel>

            <Panel
              title="Differential analyses"
              description="Runs that vary one condition against a baseline. Changed axes and the highest confidence come from the stored results."
              flush
              actions={
                <Link className="text-sm" to="/differential">
                  All differential runs
                </Link>
              }
            >
              {diffs.error ? (
                <div className="ov-pad"><ErrorState message={diffs.error} onRetry={diffs.reload} /></div>
              ) : !diffs.data ? (
                <div className="ov-pad"><LoadingBlock rows={3} /></div>
              ) : sortedDiffs.length === 0 ? (
                <div className="ov-pad">
                  <EmptyState icon={GitCompare} title="No differential runs yet">
                    Open a sample and start a differential analysis to compare a variant run against a baseline.
                  </EmptyState>
                </div>
              ) : (
                <>
                <div className="ov-row ov-row-head ov-row-diff" aria-hidden="true">
                  <span>Run</span>
                  <span>Sample</span>
                  <span>Status</span>
                  <span>Changed axes</span>
                  <span>Confidence</span>
                </div>
                <ul className="ov-list" aria-label="Recent differential analyses">
                  {sortedDiffs.slice(0, 6).map((d) => (
                    <li key={d.id} className="ov-row ov-row-diff">
                      <span className="ov-title">
                        <Link to={`/differential/${d.id}`}>Differential #{d.id}</Link>
                      </span>
                      <span className="ov-sample">
                        <Link to={`/samples/${d.sample_id}`}>{sampleName.get(d.sample_id) ?? `sample #${d.sample_id}`}</Link>
                      </span>
                      <span><JobStatusBadge status={d.status} /></span>
                      <span className="ov-axes">
                        {d.findings.length === 0 ? (
                          <span className="muted text-sm">No changes recorded</span>
                        ) : (
                          <>
                            {d.findings.slice(0, 3).map((f) => (
                              <span key={f.id} className="chip ov-chip">{labelAxis(f.axis)}</span>
                            ))}
                            {d.findings.length > 3 && <span className="muted text-xs">+{d.findings.length - 3} more</span>}
                          </>
                        )}
                      </span>
                      <span>{d.findings.length > 0 && <ConfidenceMeter confidence={topConfidence(d.findings.map((f) => f.confidence))} />}</span>
                    </li>
                  ))}
                </ul>
                </>
              )}
            </Panel>

          </div>

          <aside className="ov-rail" aria-label="Breakdowns">
            <Panel title="Job states" description={jobs.data ? `All ${plural(jobs.data.length, "job")} returned by the API.` : undefined}>
              {jobs.data ? (
                <div className="ov-donut">
                  <StatusDonut items={stateItems} height={120} centerLabel="jobs" emptyLabel="No jobs have been run yet." />
                </div>
              ) : jobs.error ? (
                <p className="muted text-sm">Job states are unavailable.</p>
              ) : (
                <LoadingBlock rows={3} />
              )}
            </Panel>

            <Panel title="Severity" description="Findings from the recent completed jobs.">
              {findings.error ? (
                <p className="muted text-sm">Severity data is unavailable.</p>
              ) : !findings.data ? (
                <LoadingBlock rows={3} />
              ) : (
                <CountBars items={severityItems} emptyLabel="No findings to chart yet." height={110} />
              )}
            </Panel>

            <Disclose title="Sample status" description="Every sample returned by the API." open={!narrow}>
              {samples.data ? (
                <CountBars items={sampleItems} emptyLabel="No samples uploaded yet." height={130} />
              ) : samples.error ? (
                <p className="muted text-sm">Sample status is unavailable.</p>
              ) : (
                <LoadingBlock rows={3} />
              )}
            </Disclose>

            <Disclose
              title="Cases"
              open={!narrow}
              actions={
                <Link className="text-sm" to="/cases">
                  All cases
                </Link>
              }
            >
              {cases.error ? (
                <p className="muted text-sm">Cases are unavailable.</p>
              ) : !cases.data || !samples.data ? (
                <LoadingBlock rows={3} />
              ) : cases.data.length === 0 ? (
                <p className="muted text-sm">No cases yet. Assign samples to a case when you upload them.</p>
              ) : (
                <CaseSummaries cases={cases.data} samples={samples.data} />
              )}
            </Disclose>

          </aside>
          <div className="ov-activity-panel">
              <Disclose title="Recent activity" description="Newest jobs, differential runs, and uploads." open={!narrow}>
                {!jobs.data && !jobs.error ? (
                  <LoadingBlock rows={4} />
                ) : activity.length === 0 ? (
                  <p className="muted text-sm">No activity yet.</p>
                ) : (
                  <ul className="list-plain ov-activity" aria-label="Recent activity">
                    {activity.slice(0, 10).map((row) => (
                      <li key={row.key} className="ov-activity-row">
                        <span className="ov-activity-what">{row.node}</span>
                        <time className="text-xs muted ov-time" dateTime={row.when}>
                          {formatDateTime(row.when)}
                        </time>
                      </li>
                    ))}
                  </ul>
                )}
              </Disclose>
          </div>
        </div>
      )}

      <p className="text-xs muted" style={{ marginTop: 22 }}>
        Findings describe the telemetry recorded for each run. They are observations, not a verdict on the file.
      </p>
    </>
  );
}

function SummaryCell({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "err" }) {
  return (
    <div className={tone === "err" ? "ov-cell ov-cell-alert" : "ov-cell"}>
      <div className="text-xs muted">{label}</div>
      <div className="ov-value">{value}</div>
      {hint && <div className="text-xs muted">{hint}</div>}
    </div>
  );
}

/** Turns a stored axis key such as "dns_resolver" into readable text. */
function labelAxis(axis: string): string {
  return axis.replace(/_/g, " ");
}

/** Highest confidence present in the stored results, using the API's own confidence values. */
function topConfidence(values: Confidence[]): Confidence {
  return CONFIDENCE_ORDER.find((c) => values.includes(c)) ?? "low";
}

/**
 * Secondary panel that can collapse. Open by default on wide screens and closed on phones,
 * so the primary findings and differential panels come first. Native details: keyboard and
 * screen-reader behavior come from the browser.
 */
function Disclose({
  title,
  description,
  actions,
  open,
  children,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  open: boolean;
  children: ReactNode;
}) {
  return (
    <details className="ov-disclose panel" open={open}>
      <summary className="ov-disclose-sum">
        <span className="ov-disclose-head">
          <h2 className="ov-disclose-title">{title}</h2>
          {description && <span className="panel-desc">{description}</span>}
        </span>
        <span className="ov-chev" aria-hidden="true" />
      </summary>
      <div className="panel-body">
        {actions && <div className="ov-disclose-actions">{actions}</div>}
        {children}
      </div>
    </details>
  );
}

function findingsDescription(res: Resource<FindingsSnapshot | null>): string {
  if (!res.data) return "Findings from recent completed jobs.";
  const { jobs, failed } = res.data;
  const base = `From the ${jobs === 1 ? "most recent completed job" : `${jobs} most recent completed jobs`}.`;
  return failed ? `${base} ${plural(failed, "job")} could not be read.` : base;
}

function countBy<T>(items: T[], key: (item: T) => string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const item of items) {
    const k = key(item);
    out[k] = (out[k] ?? 0) + 1;
  }
  return out;
}

function buildActivity(jobs: Job[], diffs: Differential[], samples: Sample[]): ActivityRow[] {
  const rows: ActivityRow[] = [];
  for (const j of jobs.slice(0, 8)) {
    rows.push({
      key: `job-${j.id}`,
      when: j.finished_at ?? j.created_at,
      node: (
        <>
          <Link to={`/jobs/${j.id}`}>Job #{j.id}</Link> on <Link to={`/samples/${j.sample_id}`}>sample #{j.sample_id}</Link>{" "}
          <JobStatusBadge status={j.status} />
        </>
      ),
    });
  }
  for (const d of [...diffs].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at)).slice(0, 4)) {
    rows.push({
      key: `diff-${d.id}`,
      when: d.created_at,
      node: (
        <>
          Differential <Link to={`/differential/${d.id}`}>#{d.id}</Link> on sample #{d.sample_id} (
          {plural(d.findings.length, "dependency", "dependencies")})
        </>
      ),
    });
  }
  for (const s of [...samples].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at)).slice(0, 4)) {
    rows.push({
      key: `sample-${s.id}`,
      when: s.created_at,
      node: (
        <>
          Uploaded <Link to={`/samples/${s.id}`}>{s.filename}</Link>
        </>
      ),
    });
  }
  return rows.sort((a, b) => +new Date(b.when) - +new Date(a.when));
}

function CaseSummaries({ cases, samples }: { cases: Case[]; samples: Sample[] }) {
  const perCase = countBy(samples.filter((s) => s.case_id != null), (s) => String(s.case_id));
  return (
    <ul className="list-plain" aria-label="Case summaries">
      {cases.slice(0, 6).map((c) => (
        <li key={c.id} style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
          <Link to={`/cases/${c.id}`} style={{ overflowWrap: "anywhere", minWidth: 0 }}>
            {c.name}
          </Link>
          <span className="text-xs muted" style={{ whiteSpace: "nowrap" }}>
            {plural(perCase[String(c.id)] ?? 0, "sample")}
          </span>
        </li>
      ))}
    </ul>
  );
}
