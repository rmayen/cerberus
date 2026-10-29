import { ListChecks } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Job, type JobStatus } from "../api";
import { PageHeader } from "../components/PageHeader";
import {
  EmptyState,
  ErrorState,
  JobStatusBadge,
  LoadingBlock,
  Panel,
  SortableTh,
  StatTile,
  TableScroll,
  useSort,
} from "../components/ui/primitives";
import { JOB_STATUS, jobStatusMeta } from "../lib/status";
import { describeConditions, formatDateTime, formatDuration } from "../lib/format";
import { useResource } from "../lib/useResource";
import { useTitle } from "../lib/useTitle";

type SortKey = "id" | "status" | "created" | "duration";
const STATUSES = Object.keys(JOB_STATUS) as JobStatus[];

export function Jobs() {
  useTitle("Jobs");
  const jobs = useResource<Job[]>((s) => api.get("/jobs", s), []);
  const [statusFilter, setStatusFilter] = useState<JobStatus | "all">("all");
  const [query, setQuery] = useState("");
  const sort = useSort<SortKey>("created", "descending");
  const { key: sortKey, dir: sortDir, toggle } = sort;

  const all = useMemo(() => jobs.data ?? [], [jobs.data]);
  const counts = useMemo(() => {
    const c: Partial<Record<JobStatus, number>> = {};
    for (const j of all) c[j.status] = (c[j.status] ?? 0) + 1;
    return c;
  }, [all]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = all.filter(
      (j) =>
        (statusFilter === "all" || j.status === statusFilter) &&
        (!q || `${j.id} ${j.sample_id} ${j.executor}`.toLowerCase().includes(q))
    );
    const dir = sortDir === "ascending" ? 1 : -1;
    const value = (j: Job): number | string => {
      switch (sortKey) {
        case "id": return j.id;
        case "status": return jobStatusMeta(j.status).label;
        case "duration": return j.duration_ms ?? -1;
        default: return new Date(j.created_at).getTime();
      }
    };
    return [...filtered].sort((a, b) => {
      const va = value(a);
      const vb = value(b);
      return va < vb ? -dir : va > vb ? dir : 0;
    });
  }, [all, statusFilter, query, sortKey, sortDir]);

  return (
    <div>
      <PageHeader title="Analysis jobs" subtitle="Each run of a sample under a set of conditions. Statuses are reported by the server." />

      <div className="grid-auto" style={{ marginBottom: 20 }}>
        <StatTile label="Total" value={jobs.data ? all.length : "—"} />
        <StatTile label="Running" value={jobs.data ? (counts.running ?? 0) : "—"} />
        <StatTile label="Completed" value={jobs.data ? (counts.completed ?? 0) : "—"} />
        <StatTile label="Failed or timed out" value={jobs.data ? (counts.failed ?? 0) + (counts.timed_out ?? 0) : "—"} />
      </div>

      <Panel
        title="Jobs"
        flush
        actions={
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <label className="sr-only" htmlFor="job-status">Filter by status</label>
            <select id="job-status" className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as JobStatus | "all")}>
              <option value="all">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {jobStatusMeta(s).label} ({counts[s] ?? 0})
                </option>
              ))}
            </select>
            <input
              className="input"
              type="search"
              placeholder="Search id, sample or executor"
              aria-label="Search jobs"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ minWidth: 200 }}
            />
          </div>
        }
      >
        {jobs.loading && jobs.data === undefined ? (
          <div style={{ padding: 16 }}>
            <LoadingBlock label="Loading jobs" rows={4} />
          </div>
        ) : jobs.error ? (
          <div style={{ padding: 16 }}>
            <ErrorState message={jobs.error} onRetry={jobs.reload} />
          </div>
        ) : all.length === 0 ? (
          <EmptyState icon={ListChecks} title="No jobs yet">
            Run an analysis from a sample's workspace to create the first job.
          </EmptyState>
        ) : rows.length === 0 ? (
          <EmptyState icon={ListChecks} title="No jobs match these filters">
            Clear the status or search filter to see all jobs.
          </EmptyState>
        ) : (
          <TableScroll label="Analysis jobs">
            <table>
              <thead>
                <tr>
                  <SortableTh label="Job" sortKey="id" active={sortKey} dir={sortDir} onSort={toggle} />
                  <th scope="col">Sample</th>
                  <th scope="col">Conditions</th>
                  <SortableTh label="Status" sortKey="status" active={sortKey} dir={sortDir} onSort={toggle} />
                  <SortableTh label="Duration" sortKey="duration" active={sortKey} dir={sortDir} onSort={toggle} />
                  <SortableTh label="Created" sortKey="created" active={sortKey} dir={sortDir} onSort={toggle} />
                </tr>
              </thead>
              <tbody>
                {rows.map((j) => (
                  <tr key={j.id}>
                    <td>
                      <Link to={`/jobs/${j.id}`}>#{j.id}</Link>
                    </td>
                    <td>
                      <Link to={`/samples/${j.sample_id}`}>sample #{j.sample_id}</Link>
                    </td>
                    <td className="text-sm" style={{ maxWidth: 320, overflowWrap: "anywhere" }}>
                      {describeConditions(j.conditions)}
                    </td>
                    <td>
                      <JobStatusBadge status={j.status} />
                    </td>
                    <td>{formatDuration(j.duration_ms)}</td>
                    <td className="text-sm">{formatDateTime(j.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        )}
      </Panel>
    </div>
  );
}
