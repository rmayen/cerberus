import { FileText } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type AttackMapping, type Finding, type Job, type Sample, type TelemetryEvent } from "../api";
import { ReportDialog } from "../components/dialogs";
import { AttackTable, FindingList } from "../components/Findings";
import { PageHeader } from "../components/PageHeader";
import { TelemetryTable } from "../components/Tables";
import {
  Button,
  EmptyState,
  ErrorState,
  JobStatusBadge,
  KeyValue,
  LoadingBlock,
  Notice,
  Panel,
} from "../components/ui/primitives";
import { describeConditions, formatDateTime, formatDuration, formatValue, labelize } from "../lib/format";
import { useResource } from "../lib/useResource";
import { useTitle } from "../lib/useTitle";

export function JobDetail() {
  const { id = "" } = useParams();
  const jobId = Number(id);
  const validId = Number.isInteger(jobId) && jobId > 0;
  const [reportOpen, setReportOpen] = useState(false);

  const job = useResource<Job>((s) => api.get(`/jobs/${jobId}`, s), [jobId]);
  const jobSampleId = job.data?.sample_id;
  const sample = useResource<Sample | null>(
    (s) => (jobSampleId != null ? api.get<Sample>(`/samples/${jobSampleId}`, s) : Promise.resolve(null)),
    [jobSampleId]
  );
  const findings = useResource<Finding[]>((s) => api.get(`/jobs/${jobId}/findings`, s), [jobId]);
  const attack = useResource<AttackMapping[]>((s) => api.get(`/jobs/${jobId}/attack`, s), [jobId]);
  const telemetry = useResource<TelemetryEvent[]>((s) => api.get(`/jobs/${jobId}/telemetry`, s), [jobId]);

  const j = job.data;
  useTitle(j ? `Job #${j.id}` : "Job");

  if (!validId) {
    return (
      <EmptyState icon={FileText} title="This job link is not valid">
        <Link to="/jobs">Return to the job list</Link>
      </EmptyState>
    );
  }
  if (job.loading && !j) return <LoadingBlock label="Loading job" rows={5} />;
  if (job.error && !j) return <ErrorState message={job.error} onRetry={job.reload} />;
  if (!j) return <LoadingBlock label="Loading job" rows={5} />;

  return (
    <div>
      <PageHeader
        crumbs={[{ label: "Jobs", to: "/jobs" }, { label: `#${j.id}` }]}
        title={`Job #${j.id}`}
        badges={<JobStatusBadge status={j.status} />}
        subtitle={
          <>
            Sample <Link to={`/samples/${j.sample_id}`}>{sample.data?.filename ?? `#${j.sample_id}`}</Link>, executor{" "}
            {labelize(j.executor)}
          </>
        }
        actions={
          <Button variant="secondary" icon={FileText} onClick={() => setReportOpen(true)}>
            Report
          </Button>
        }
      />

      {j.error && (
        <div style={{ marginBottom: 16 }}>
          <Notice tone="err">
            <span style={{ display: "block", fontWeight: 600 }}>Backend error</span>
            <span style={{ overflowWrap: "anywhere", whiteSpace: "pre-wrap" }}>{j.error}</span>
          </Notice>
        </div>
      )}

      <div className="split split-2" style={{ marginBottom: 20 }}>
        <Panel title="Run state">
          <KeyValue
            items={[
              { label: "Status", value: <JobStatusBadge status={j.status} /> },
              { label: "Executor", value: <span className="mono">{j.executor}</span> },
              { label: "Submitted", value: formatDateTime(j.created_at) },
              { label: "Started", value: formatDateTime(j.started_at) },
              { label: "Finished", value: formatDateTime(j.finished_at) },
              { label: "Duration", value: formatDuration(j.duration_ms) },
            ]}
          />
        </Panel>
        <Panel title="Conditions" description={describeConditions(j.conditions)}>
          {Object.keys(j.conditions).length === 0 ? (
            <p className="muted text-sm">No conditions were recorded for this run.</p>
          ) : (
            <KeyValue
              items={Object.entries(j.conditions).map(([k, v]) => ({
                label: labelize(k),
                value: <span className="mono">{formatValue(v)}</span>,
              }))}
            />
          )}
        </Panel>
      </div>

      {j.result && (
        <Panel title="Result" description="The result object returned by the API for this run.">
          <pre className="pre" tabIndex={0} role="region" aria-label="Result JSON">{JSON.stringify(j.result, null, 2)}</pre>
        </Panel>
      )}

      <div style={{ display: "grid", gap: 20, marginTop: 20 }}>
        <Panel title="Behavior findings" description="Each finding names its severity and the evidence it was derived from.">
          {findings.error ? (
            <ErrorState message={findings.error} onRetry={findings.reload} />
          ) : !findings.data ? (
            <LoadingBlock rows={3} />
          ) : (
            <FindingList findings={findings.data} emptyText="No findings were produced for this run." />
          )}
        </Panel>

        <Panel title="MITRE ATT&CK" description="Techniques mapped from the observed behavior.">
          {attack.error ? (
            <ErrorState message={attack.error} onRetry={attack.reload} />
          ) : !attack.data ? (
            <LoadingBlock rows={3} />
          ) : (
            <AttackTable mappings={attack.data} />
          )}
        </Panel>

        <Panel title="Telemetry log" description="Recorded events in sequence order, as returned by the API." flush>
          {telemetry.error ? (
            <div style={{ padding: 16 }}>
              <ErrorState message={telemetry.error} onRetry={telemetry.reload} />
            </div>
          ) : !telemetry.data ? (
            <div style={{ padding: 16 }}>
              <LoadingBlock rows={4} />
            </div>
          ) : (
            <TelemetryTable events={telemetry.data} />
          )}
        </Panel>
      </div>

      {reportOpen && <ReportDialog jobId={j.id} open onClose={() => setReportOpen(false)} />}
    </div>
  );
}
