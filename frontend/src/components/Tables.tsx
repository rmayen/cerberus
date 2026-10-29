import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Job, Sample, TelemetryEvent } from "../api";
import { describeConditions, formatBytes, formatDateTime, formatDuration, labelize, plural } from "../lib/format";
import { jobStatusMeta } from "../lib/status";
import { AnalysisStatusBadge, Badge, HashValue, JobStatusBadge, SampleStatusBadge, SortableTh, TableScroll, useSort } from "./ui/primitives";

// ---------- Telemetry ----------

export function TelemetryTable({ events, emptyText = "No telemetry was recorded for this run." }: { events: TelemetryEvent[]; emptyText?: string }) {
  const [category, setCategory] = useState<string>("all");
  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const e of events) map.set(e.category, (map.get(e.category) ?? 0) + 1);
    return [...map.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [events]);
  const visible = category === "all" ? events : events.filter((e) => e.category === category);

  if (events.length === 0) {
    return <p className="muted text-sm">{emptyText}</p>;
  }

  return (
    <div>
      <div className="chip-group" role="group" aria-label="Filter events by category" style={{ marginBottom: 12 }}>
        <button type="button" className="chip" aria-pressed={category === "all"} onClick={() => setCategory("all")}>
          All <span className="tab-count">{events.length}</span>
        </button>
        {counts.map(([cat, n]) => (
          <button key={cat} type="button" className="chip" aria-pressed={category === cat} onClick={() => setCategory(cat)}>
            {labelize(cat)} <span className="tab-count">{n}</span>
          </button>
        ))}
      </div>
      <p className="text-xs muted" aria-live="polite" style={{ marginBottom: 8 }}>
        Showing {plural(visible.length, "event")}
      </p>
      <TableScroll label="Normalized telemetry events">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col" className="num">#</th>
              <th scope="col">Category</th>
              <th scope="col">Action</th>
              <th scope="col" className="cell-wrap">Target</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((t) => (
              <tr key={t.id}>
                <td className="num">{t.sequence}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <Badge tone="tag">{t.category}</Badge>
                </td>
                <td style={{ whiteSpace: "nowrap" }}>{t.action}</td>
                <td className="cell-wrap mono" style={{ fontSize: "0.8125rem" }}>
                  {t.target}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </div>
  );
}

// ---------- Jobs ----------

type JobSortKey = "id" | "status" | "duration" | "created";

export function JobsTable({
  jobs,
  showSample = true,
  sampleNames,
  caption,
  renderActions,
}: {
  jobs: Job[];
  showSample?: boolean;
  sampleNames?: Map<number, string>;
  caption?: string;
  renderActions?: (job: Job) => ReactNode;
}) {
  const { key, dir, toggle } = useSort<JobSortKey>("created", "descending");

  const sorted = useMemo(() => {
    const list = [...jobs];
    const factor = dir === "ascending" ? 1 : -1;
    list.sort((a, b) => {
      switch (key) {
        case "id":
          return (a.id - b.id) * factor;
        case "status":
          return jobStatusMeta(a.status).label.localeCompare(jobStatusMeta(b.status).label) * factor || a.id - b.id;
        case "duration":
          return ((a.duration_ms ?? -1) - (b.duration_ms ?? -1)) * factor;
        case "created":
        default:
          return (new Date(a.created_at).getTime() - new Date(b.created_at).getTime()) * factor;
      }
    });
    return list;
  }, [jobs, key, dir]);

  if (jobs.length === 0) return null;

  return (
    <TableScroll label="Analysis jobs">
      <table className="data-table">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            <SortableTh label="Job" sortKey="id" active={key} dir={dir} onSort={toggle} />
            {showSample && <th scope="col">Sample</th>}
            <th scope="col" className="cell-wrap">Conditions</th>
            <SortableTh label="Status" sortKey="status" active={key} dir={dir} onSort={toggle} />
            <SortableTh label="Duration" sortKey="duration" active={key} dir={dir} onSort={toggle} className="num" />
            <SortableTh label="Created" sortKey="created" active={key} dir={dir} onSort={toggle} />
            {renderActions && <th scope="col">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {sorted.map((j) => (
            <tr key={j.id}>
              <td style={{ whiteSpace: "nowrap" }}>
                <Link to={`/jobs/${j.id}`}>Job #{j.id}</Link>
              </td>
              {showSample && (
                <td className="cell-wrap">
                  <Link to={`/samples/${j.sample_id}`}>{sampleNames?.get(j.sample_id) ?? `Sample #${j.sample_id}`}</Link>
                </td>
              )}
              <td className="cell-wrap mono" style={{ fontSize: "0.8125rem" }}>
                {describeConditions(j.conditions)}
              </td>
              <td className="cell-wrap">
                <JobStatusBadge status={j.status} />
                {j.error && (
                  <div className="text-xs" style={{ color: "var(--color-err-fg)", marginTop: 6, overflowWrap: "anywhere" }}>
                    {j.error}
                  </div>
                )}
              </td>
              <td className="num" style={{ whiteSpace: "nowrap" }}>
                {formatDuration(j.duration_ms)}
              </td>
              <td style={{ whiteSpace: "nowrap" }}>{formatDateTime(j.created_at)}</td>
              {renderActions && <td style={{ whiteSpace: "nowrap" }}>{renderActions(j)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}

// ---------- Samples ----------

export function SamplesTable({
  samples,
  caseNames,
  emptyText = "No samples match the current filters.",
}: {
  samples: Sample[];
  caseNames?: Map<number, string>;
  emptyText?: string;
}) {
  if (samples.length === 0) return <p className="muted text-sm">{emptyText}</p>;
  return (
    <TableScroll label="Samples">
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col" className="cell-wrap">Filename</th>
            <th scope="col">Type</th>
            <th scope="col" className="num">Size</th>
            <th scope="col">Status</th>
            <th scope="col">Analysis</th>
            <th scope="col" className="cell-wrap">Case</th>
            <th scope="col">Uploaded</th>
            <th scope="col">SHA-256</th>
          </tr>
        </thead>
        <tbody>
          {samples.map((s) => (
            <tr key={s.id}>
              <td className="cell-wrap">
                <Link to={`/samples/${s.id}`} style={{ overflowWrap: "anywhere" }}>
                  {s.filename}
                </Link>
                {s.tags.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                    {s.tags.map((t) => (
                      <Badge key={t} tone="tag">
                        {t}
                      </Badge>
                    ))}
                  </div>
                )}
              </td>
              <td style={{ whiteSpace: "nowrap" }}>{s.detected_type ?? "Unknown"}</td>
              <td className="num" style={{ whiteSpace: "nowrap" }}>
                {formatBytes(s.size_bytes)}
              </td>
              <td>
                <SampleStatusBadge status={s.status} />
              </td>
              <td>
                <AnalysisStatusBadge status={s.analysis_status} />
              </td>
              <td className="cell-wrap">
                {s.case_id != null ? (
                  <Link to={`/cases/${s.case_id}`}>{caseNames?.get(s.case_id) ?? `Case #${s.case_id}`}</Link>
                ) : (
                  <span className="muted">None</span>
                )}
              </td>
              <td style={{ whiteSpace: "nowrap" }}>{formatDateTime(s.created_at)}</td>
              <td style={{ minWidth: 200 }}>
                <HashValue value={s.sha256} label="SHA-256" compact />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}
