import { Activity, Download, FileText, Fingerprint, GitCompare, ListChecks, Network, Pencil, Play, Shield } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  downloadFile,
  type AttackMapping,
  type Confidence,
  type Differential,
  type Finding,
  type Ioc,
  type IocType,
  type Job,
  type Sample,
  type TelemetryEvent,
} from "../../api";
import { CountBars } from "../../components/LazyCharts";
import type { ChartItem } from "../../components/Charts";
import { ReportDialog } from "../../components/dialogs";
import { AttackTable, FindingList } from "../../components/Findings";
import { JobsTable, TelemetryTable } from "../../components/Tables";
import { SelectField, TextField } from "../../components/ui/Fields";
import {
  Badge,
  Button,
  ConfidenceMeter,
  EmptyState,
  ErrorState,
  HashValue,
  JobStatusBadge,
  KeyValue,
  LoadingBlock,
  Notice,
  Panel,
  SampleStatusBadge,
} from "../../components/ui/primitives";
import { describeConditions, errorMessage, formatBytes, formatDateTime, labelize, plural } from "../../lib/format";
import { CONFIDENCE_ORDER, SEVERITY, SEVERITY_ORDER, attackUrl, type Tone } from "../../lib/status";
import { useResource } from "../../lib/useResource";

export type SampleTab = "overview" | "jobs" | "findings" | "behavior" | "iocs" | "attack" | "differential";

export const SAMPLE_TABS: { id: SampleTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "jobs", label: "Analysis jobs" },
  { id: "findings", label: "Findings" },
  { id: "behavior", label: "Behavior" },
  { id: "iocs", label: "IOCs" },
  { id: "attack", label: "ATT&CK" },
  { id: "differential", label: "Differential" },
];

export function isSampleTab(value: string | null): value is SampleTab {
  return SAMPLE_TABS.some((t) => t.id === value);
}

/** Completed runs are the ones that produce findings, telemetry, and ATT&CK mappings. */
function defaultJobId(jobs: Job[]): number | null {
  const completed = jobs.filter((j) => j.status === "completed");
  if (completed.length === 0) return null;
  return completed.reduce((latest, j) => (new Date(j.created_at) > new Date(latest.created_at) ? j : latest)).id;
}

function JobPicker({ jobs, value, onChange, label = "Analysis run" }: { jobs: Job[]; value: number | null; onChange: (id: number) => void; label?: string }) {
  return (
    <SelectField label={label} value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))} className="field-narrow" style={{ minWidth: 220 }}>
      {jobs.map((j) => (
        <option key={j.id} value={j.id}>
          Job #{j.id} · {j.status.replace("_", " ")} · {describeConditions(j.conditions)}
        </option>
      ))}
    </SelectField>
  );
}

// ---------- Overview ----------

export function OverviewTab({
  sample,
  jobs,
  iocs,
  diffs,
  caseName,
  canAnalyze,
  onEditTags,
}: {
  sample: Sample;
  jobs: Job[];
  iocs: Ioc[];
  diffs: Differential[];
  caseName: string | null;
  canAnalyze: boolean;
  onEditTags: () => void;
}) {
  const latest = jobs.length ? [...jobs].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))[0] : null;
  const completed = jobs.filter((j) => j.status === "completed").length;
  const failed = jobs.filter((j) => j.status === "failed" || j.status === "timed_out").length;
  return (
    <div className="split split-2">
      <Panel
        title="Metadata"
        actions={
          canAnalyze ? (
            <Button size="sm" variant="ghost" icon={Pencil} onClick={onEditTags}>
              Edit tags
            </Button>
          ) : undefined
        }
      >
        <KeyValue
          items={[
            { label: "SHA-256", value: <HashValue value={sample.sha256} label="SHA-256" /> },
            { label: "Size", value: `${formatBytes(sample.size_bytes)} (${sample.size_bytes.toLocaleString()} bytes)` },
            { label: "Detected type", value: sample.detected_type ?? "Unknown" },
            { label: "Content type", value: sample.content_type ?? "Not provided on upload" },
            { label: "Uploaded", value: formatDateTime(sample.created_at) },
            { label: "Uploaded by", value: sample.uploaded_by != null ? `User #${sample.uploaded_by}` : "Unknown" },
            {
              label: "Case",
              value:
                sample.case_id != null ? (
                  <Link to={`/cases/${sample.case_id}`}>{caseName ?? `Case #${sample.case_id}`}</Link>
                ) : (
                  <span className="muted">Not assigned</span>
                ),
            },
            {
              label: "Tags",
              value: sample.tags.length ? (
                <span style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {sample.tags.map((t) => (
                    <Badge key={t} tone="tag">
                      {t}
                    </Badge>
                  ))}
                </span>
              ) : (
                <span className="muted">None</span>
              ),
            },
          ]}
        />
      </Panel>

      <div style={{ display: "grid", gap: 16, alignContent: "start", minWidth: 0 }}>
        <Panel title="Quarantine" description="Status as reported by the API.">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", marginBottom: 10 }}>
            <SampleStatusBadge status={sample.status} />
            <span className="text-sm muted">Stored encrypted at rest; never executed by the application.</span>
          </div>
          <p className="text-sm muted">
            The API exposes the sample status but no approval workflow yet, so the status above is the only quarantine state Cerberus
            can report.
          </p>
        </Panel>

        <Panel title="Summary">
          <KeyValue
            items={[
              { label: "Analysis runs", value: `${plural(jobs.length, "run")} (${completed} completed, ${failed} failed or timed out)` },
              { label: "Latest run", value: latest ? <Link to={`/jobs/${latest.id}`}>Job #{latest.id}</Link> : <span className="muted">None yet</span> },
              { label: "Indicators", value: plural(iocs.length, "indicator") },
              { label: "Differential analyses", value: plural(diffs.length, "analysis", "analyses") },
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}

// ---------- Jobs ----------

export function JobsHistoryTab({ jobs, canAnalyze, onRun }: { jobs: Job[]; canAnalyze: boolean; onRun: () => void }) {
  const [reportJob, setReportJob] = useState<number | null>(null);
  if (jobs.length === 0) {
    return (
      <EmptyState
        icon={ListChecks}
        title="No analysis runs yet"
        action={
          canAnalyze ? (
            <Button variant="primary" icon={Play} onClick={onRun}>
              Run analysis
            </Button>
          ) : undefined
        }
      >
        Each run executes this sample under one set of conditions. Results appear on the job page when the run finishes.
      </EmptyState>
    );
  }
  return (
    <>
      <JobsTable
        jobs={jobs}
        showSample={false}
        caption="Analysis run history for this sample"
        renderActions={(j) => (
          <Button size="sm" variant="ghost" icon={FileText} onClick={() => setReportJob(j.id)}>
            Report
          </Button>
        )}
      />
      {reportJob !== null && (
        <ReportDialog jobId={reportJob} open onClose={() => setReportJob(null)} />
      )}
    </>
  );
}

// ---------- Findings ----------

export function FindingsTab({ jobs }: { jobs: Job[] }) {
  const completed = useMemo(() => jobs.filter((j) => j.status === "completed"), [jobs]);
  const [picked, setPicked] = useState<number | null>(null);
  const jobId = picked ?? defaultJobId(jobs);
  const [severity, setSeverity] = useState<string>("all");

  const findings = useResource<Finding[]>((s) => api.get(`/jobs/${jobId}/findings`, s), [jobId]);
  if (completed.length === 0) {
    return <EmptyState icon={Shield} title="No completed run to read findings from">Findings are produced when a run completes. Start a run from the Overview or Analysis jobs tab.</EmptyState>;
  }
  const data = findings.data ?? [];
  const counts = SEVERITY_ORDER.map((sev) => ({ sev, n: data.filter((f) => f.severity === sev).length }));
  const visible = severity === "all" ? data : data.filter((f) => f.severity === severity);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="toolbar">
        <JobPicker jobs={completed} value={jobId} onChange={setPicked} />
        <div className="chip-group" role="group" aria-label="Filter findings by severity">
          <button type="button" className="chip" aria-pressed={severity === "all"} onClick={() => setSeverity("all")}>
            All <span className="tab-count">{data.length}</span>
          </button>
          {counts.map(({ sev, n }) => (
            <button key={sev} type="button" className="chip" aria-pressed={severity === sev} onClick={() => setSeverity(sev)}>
              {SEVERITY[sev].label} <span className="tab-count">{n}</span>
            </button>
          ))}
        </div>
      </div>
      <Panel>
        {findings.error ? (
          <ErrorState message={findings.error} onRetry={findings.reload} />
        ) : !findings.data ? (
          <LoadingBlock rows={4} />
        ) : (
          <>
            <p className="text-xs muted" aria-live="polite" style={{ marginBottom: 10 }}>
              Showing {plural(visible.length, "finding")} from job #{jobId}
            </p>
            <FindingList findings={visible} emptyText="No findings match this filter for the selected run." />
          </>
        )}
      </Panel>
    </div>
  );
}

// ---------- Behavior (telemetry) ----------

export function BehaviorTab({ jobs }: { jobs: Job[] }) {
  const completed = jobs.filter((j) => j.status === "completed");
  const [picked, setPicked] = useState<number | null>(null);
  const jobId = picked ?? defaultJobId(jobs);
  const telemetry = useResource<TelemetryEvent[]>((s) => api.get(`/jobs/${jobId}/telemetry`, s), [jobId]);

  if (completed.length === 0) {
    return <EmptyState icon={Activity} title="No completed run to show behavior for">Telemetry is recorded when a run completes.</EmptyState>;
  }

  const categories = countCategories(telemetry.data ?? []);
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="toolbar">
        <JobPicker jobs={completed} value={jobId} onChange={setPicked} />
      </div>
      <div className="split split-main-side">
        <Panel title="Observed behavior" description={`Normalized telemetry from job #${jobId}.`}>
          {telemetry.error ? (
            <ErrorState message={telemetry.error} onRetry={telemetry.reload} />
          ) : !telemetry.data ? (
            <LoadingBlock rows={5} />
          ) : (
            <TelemetryTable events={telemetry.data} />
          )}
        </Panel>
        <Panel title="Events by category" description="Counts from the table.">
          {telemetry.data ? <CountBars items={categories} emptyLabel="No events recorded." height={Math.max(120, categories.length * 30)} /> : <LoadingBlock rows={3} />}
        </Panel>
      </div>
    </div>
  );
}

function countCategories(events: TelemetryEvent[]): ChartItem[] {
  const map = new Map<string, number>();
  for (const e of events) map.set(e.category, (map.get(e.category) ?? 0) + 1);
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([cat, n]) => ({ key: cat, label: labelize(cat), value: n, tone: "run" as Tone }));
}

// ---------- IOCs ----------

const IOC_TYPES: IocType[] = ["domain", "ip", "url", "file_hash", "registry_key", "mutex", "service", "file_path"];

export function IocsTab({ sampleId, iocs, reloadIocs, iocsError }: { sampleId: number; iocs: Ioc[] | undefined; reloadIocs: () => void; iocsError: string | null }) {
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [exporting, setExporting] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (iocs ?? []).filter((i) => (!type || i.type === type) && (!q || i.value.toLowerCase().includes(q)));
  }, [iocs, query, type]);

  async function exportAs(format: "csv" | "json") {
    setExporting(format);
    setExportError(null);
    try {
      await downloadFile(`/samples/${sampleId}/iocs/export?format=${format}`, `iocs_${sampleId}.${format}`);
    } catch (err) {
      setExportError(`The export could not be downloaded. ${errorMessage(err, "Try again.")}`);
    } finally {
      setExporting(null);
    }
  }

  if (iocsError) return <ErrorState message={iocsError} onRetry={reloadIocs} />;
  if (!iocs) return <LoadingBlock rows={5} />;

  return (
    <Panel
      title="Indicators of compromise"
      description="Extracted from each run's raw telemetry. Values are shown as text."
      actions={
        iocs.length > 0 ? (
          <>
            <Button size="sm" variant="secondary" icon={Download} onClick={() => exportAs("csv")} disabled={exporting !== null}>
              {exporting === "csv" ? "Preparing…" : "Export CSV"}
            </Button>
            <Button size="sm" variant="secondary" icon={Download} onClick={() => exportAs("json")} disabled={exporting !== null}>
              {exporting === "json" ? "Preparing…" : "Export JSON"}
            </Button>
          </>
        ) : undefined
      }
    >
      {exportError && (
        <div style={{ marginBottom: 12 }}>
          <Notice tone="err">{exportError}</Notice>
        </div>
      )}
      {iocs.length === 0 ? (
        <EmptyState icon={Fingerprint} title="No indicators yet">
          Indicators are extracted when a run completes. Domains, IPs, mutexes, and file paths from telemetry appear here.
        </EmptyState>
      ) : (
        <>
          <div className="toolbar" style={{ marginBottom: 12 }}>
            <TextField
              label="Search indicator values"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="example.test, Global\\…"
              style={{ maxWidth: 420 }}
            />
            <SelectField label="Type" value={type} onChange={(e) => setType(e.target.value)} className="field-narrow">
              <option value="">All types</option>
              {IOC_TYPES.map((t) => (
                <option key={t} value={t}>
                  {labelize(t)}
                </option>
              ))}
            </SelectField>
          </div>
          <p className="text-xs muted" aria-live="polite" style={{ marginBottom: 8 }}>
            Showing {filtered.length} of {plural(iocs.length, "indicator")}
          </p>
          {filtered.length === 0 ? (
            <p className="muted text-sm">No indicators match this search.</p>
          ) : (
            <div className="table-scroll" role="region" aria-label="Indicators of compromise" tabIndex={0}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Type</th>
                    <th scope="col" className="cell-wrap">Value</th>
                    <th scope="col">First seen</th>
                    <th scope="col">Source run</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((i) => (
                    <tr key={i.id}>
                      <td style={{ whiteSpace: "nowrap" }}>
                        <Badge tone="tag">{labelize(i.type)}</Badge>
                      </td>
                      <td className="cell-wrap">
                        <HashValue value={i.value} label={`${labelize(i.type)} indicator`} compact />
                      </td>
                      <td style={{ whiteSpace: "nowrap" }}>{formatDateTime(i.first_seen)}</td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {i.source_job_id != null ? <Link to={`/jobs/${i.source_job_id}`}>Job #{i.source_job_id}</Link> : <span className="muted">Sample hash</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

// ---------- ATT&CK ----------

export function AttackTab({ jobs }: { jobs: Job[] }) {
  const completed = jobs.filter((j) => j.status === "completed");
  const [picked, setPicked] = useState<number | null>(null);
  const jobId = picked ?? defaultJobId(jobs);
  const mappings = useResource<AttackMapping[]>((s) => api.get(`/jobs/${jobId}/attack`, s), [jobId]);
  if (completed.length === 0) {
    return <EmptyState icon={Network} title="No completed run to map">ATT&CK mappings come from a completed run's findings.</EmptyState>;
  }
  const byTactic = new Map<string, number>();
  for (const m of mappings.data ?? []) byTactic.set(m.tactic, (byTactic.get(m.tactic) ?? 0) + 1);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="toolbar">
        <JobPicker jobs={completed} value={jobId} onChange={setPicked} />
      </div>
      <Panel
        title="Techniques observed"
        description={`Mapped from job #${jobId}. Technique IDs link to the public MITRE ATT&CK site.`}
        footer={
          byTactic.size > 0 ? (
            <span>
              By tactic:{" "}
              {[...byTactic.entries()].map(([t, n], i) => (
                <span key={t}>
                  {i > 0 && " · "}
                  {t} ({n})
                </span>
              ))}
            </span>
          ) : undefined
        }
      >
        {mappings.error ? (
          <ErrorState message={mappings.error} onRetry={mappings.reload} />
        ) : !mappings.data ? (
          <LoadingBlock rows={4} />
        ) : (
          <AttackTable mappings={mappings.data} />
        )}
      </Panel>
      {mappings.data?.some((m) => !attackUrl(m.technique_id)) && (
        <p className="text-xs muted">Some technique IDs are not in the standard format and are shown without a link.</p>
      )}
    </div>
  );
}

// ---------- Differential ----------

export function DifferentialTab({ diffs, canAnalyze, onRun }: { diffs: Differential[]; canAnalyze: boolean; onRun: () => void }) {
  if (diffs.length === 0) {
    return (
      <EmptyState
        icon={GitCompare}
        title="No differential analyses yet"
        action={
          canAnalyze ? (
            <Button variant="primary" icon={GitCompare} onClick={onRun}>
              Run differential analysis
            </Button>
          ) : undefined
        }
      >
        A differential analysis runs a baseline and one variant per changed condition, then reports which behavior depended on the condition.
      </EmptyState>
    );
  }
  return (
    <Panel title="Differential analyses" description="Each analysis compares runs that differ by one condition.">
      <div className="table-scroll" role="region" aria-label="Differential analyses" tabIndex={0}>
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Analysis</th>
              <th scope="col">Created</th>
              <th scope="col">Status</th>
              <th scope="col" className="cell-wrap">Dependencies by confidence</th>
            </tr>
          </thead>
          <tbody>
            {diffs.map((d) => (
              <tr key={d.id}>
                <td style={{ whiteSpace: "nowrap" }}>
                  <Link to={`/differential/${d.id}`}>Analysis #{d.id}</Link>
                </td>
                <td style={{ whiteSpace: "nowrap" }}>{formatDateTime(d.created_at)}</td>
                <td>
                  <JobStatusBadge status={d.status} />
                </td>
                <td className="cell-wrap">
                  <ConfidenceSummary findings={d.findings} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export function ConfidenceSummary({ findings }: { findings: { confidence: Confidence }[] }) {
  if (findings.length === 0) return <span className="muted">No behavioral dependencies observed</span>;
  return (
    <span style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
      {CONFIDENCE_ORDER.map((c) => {
        const n = findings.filter((f) => f.confidence === c).length;
        return n ? (
          <span key={c} style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
            <ConfidenceMeter confidence={c} /> <span>{n}</span>
          </span>
        ) : null;
      })}
    </span>
  );
}
