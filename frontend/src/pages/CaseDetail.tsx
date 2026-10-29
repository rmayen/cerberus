import { ArrowLeft, Briefcase, FileSearch } from "lucide-react";
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Case, type Job, type Sample } from "../api";
import { PageHeader } from "../components/PageHeader";
import {
  EmptyState,
  ErrorState,
  JobStatusBadge,
  KeyValue,
  LoadingBlock,
  Panel,
  SampleStatusBadge,
  StatTile,
  TableScroll,
} from "../components/ui/primitives";
import { formatBytes, formatDateTime } from "../lib/format";
import { useResource } from "../lib/useResource";
import { useTitle } from "../lib/useTitle";

export function CaseDetail() {
  const { id = "" } = useParams();
  const kase = useResource<Case[]>((s) => api.get("/cases", s), []);
  const samples = useResource<Sample[]>((s) => api.get("/samples", s), []);
  const jobs = useResource<Job[]>((s) => api.get("/jobs", s), []);

  const caseId = Number(id);
  const current = kase.data?.find((c) => c.id === caseId);
  useTitle(current ? current.name : "Case");

  const caseSamples = useMemo(
    () => (samples.data ?? []).filter((s) => s.case_id === caseId),
    [samples.data, caseId]
  );
  const jobsBySample = useMemo(() => {
    const map = new Map<number, Job[]>();
    for (const j of jobs.data ?? []) {
      const list = map.get(j.sample_id) ?? [];
      list.push(j);
      map.set(j.sample_id, list);
    }
    return map;
  }, [jobs.data]);

  const loading = kase.loading && kase.data === undefined;
  if (loading) return <LoadingBlock label="Loading case" rows={4} />;
  if (kase.error) return <ErrorState message={kase.error} onRetry={kase.reload} />;
  if (!current) {
    return (
      <EmptyState icon={Briefcase} title="Case not found">
        <Link to="/cases">Back to cases</Link>
      </EmptyState>
    );
  }

  const allJobs = caseSamples.flatMap((s) => jobsBySample.get(s.id) ?? []);
  const countStatus = (status: string) => allJobs.filter((j) => j.status === status).length;

  return (
    <div>
      <PageHeader
        crumbs={[{ label: "Cases", to: "/cases" }, { label: current.name }]}
        title={current.name}
        subtitle={current.description || "No description."}
        actions={
          <Link className="btn btn-secondary" to="/cases">
            <ArrowLeft size={14} aria-hidden="true" /> All cases
          </Link>
        }
      />

      <div className="grid-auto" style={{ marginBottom: 20 }}>
        <StatTile label="Samples" value={caseSamples.length} />
        <StatTile label="Jobs" value={samples.data && jobs.data ? allJobs.length : "—"} />
        <StatTile label="Completed jobs" value={jobs.data ? countStatus("completed") : "—"} />
        <StatTile label="Failed jobs" value={jobs.data ? countStatus("failed") : "—"} />
      </div>

      <div className="split-2" style={{ marginBottom: 20 }}>
        <Panel title="Case details">
          <KeyValue
            items={[
              { label: "Case id", value: <span className="mono">#{current.id}</span> },
              { label: "Created", value: formatDateTime(current.created_at) },
            ]}
          />
        </Panel>
        <Panel title="Report" description="Per-job reports are generated from each job's page.">
          <p className="text-sm muted">Open a sample below, then a job, to generate its HTML or PDF report.</p>
        </Panel>
      </div>

      <Panel title="Evidence" description="Samples assigned to this case and their analysis jobs." flush>
        {samples.loading && samples.data === undefined ? (
          <div style={{ padding: 16 }}>
            <LoadingBlock label="Loading evidence" rows={3} />
          </div>
        ) : samples.error ? (
          <div style={{ padding: 16 }}>
            <ErrorState message={samples.error} onRetry={samples.reload} />
          </div>
        ) : caseSamples.length === 0 ? (
          <EmptyState icon={FileSearch} title="No evidence in this case">
            Assign samples to this case from the sample workspace to group them here.
          </EmptyState>
        ) : (
          <TableScroll label="Case evidence">
            <table>
              <thead>
                <tr>
                  <th scope="col">Sample</th>
                  <th scope="col">Status</th>
                  <th scope="col">Size</th>
                  <th scope="col">Jobs</th>
                  <th scope="col">Latest job</th>
                  <th scope="col">Uploaded</th>
                </tr>
              </thead>
              <tbody>
                {caseSamples.map((s) => {
                  const sj = jobsBySample.get(s.id) ?? [];
                  const latest = sj[sj.length - 1];
                  return (
                    <tr key={s.id}>
                      <td>
                        <Link to={`/samples/${s.id}`}>{s.filename}</Link>
                        <div className="mono text-sm muted">{s.sha256.slice(0, 16)}…</div>
                      </td>
                      <td>
                        <SampleStatusBadge status={s.status} />
                      </td>
                      <td>{formatBytes(s.size_bytes)}</td>
                      <td>{jobs.data ? sj.length : "—"}</td>
                      <td>{latest ? <JobStatusBadge status={latest.status} /> : <span className="muted">none</span>}</td>
                      <td className="text-sm">{formatDateTime(s.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableScroll>
        )}
      </Panel>
    </div>
  );
}
