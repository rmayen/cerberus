import { FileSearch, GitCompare, Play } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type Case, type Differential, type Ioc, type Job, type Sample } from "../api";
import { useAuth } from "../auth";
import { DifferentialDialog, RunAnalysisDialog, TagsDialog } from "../components/dialogs";
import { PageHeader } from "../components/PageHeader";
import { Tabs, TabPanel } from "../components/ui/Tabs";
import { AnalysisStatusBadge, Button, ErrorState, LoadingBlock, Notice, SampleStatusBadge, EmptyState, Badge, HashValue } from "../components/ui/primitives";
import { formatBytes } from "../lib/format";
import { useResource } from "../lib/useResource";
import { useTitle } from "../lib/useTitle";
import {
  AttackTab,
  BehaviorTab,
  DifferentialTab,
  FindingsTab,
  IocsTab,
  isSampleTab,
  JobsHistoryTab,
  OverviewTab,
  SAMPLE_TABS,
  type SampleTab,
} from "./sample/SampleTabs";

export function SampleDetail() {
  const { id } = useParams();
  const sampleId = Number(id);
  const validId = Number.isInteger(sampleId) && sampleId > 0;
  const { canAnalyze } = useAuth();
  const [params, setParams] = useSearchParams();
  const tabParam = params.get("tab");
  const tab: SampleTab = isSampleTab(tabParam) ? tabParam : "overview";
  const tabsBase = useId();

  const sample = useResource<Sample>((s) => api.get(`/samples/${sampleId}`, s), [sampleId]);
  const jobs = useResource<Job[]>((s) => api.get(`/jobs?sample_id=${sampleId}`, s), [sampleId]);
  const iocs = useResource<Ioc[]>((s) => api.get(`/samples/${sampleId}/iocs`, s), [sampleId]);
  const diffs = useResource<Differential[]>((s) => api.get(`/differential?sample_id=${sampleId}`, s), [sampleId]);
  const cases = useResource<Case[]>((s) => api.get("/cases", s), []);

  const [runOpen, setRunOpen] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const [tagsOpen, setTagsOpen] = useState(false);
  const [notice, setNotice] = useState<{ tone: "ok" | "err"; text: string; href?: string; label?: string } | null>(null);

  const reloadAll = () => {
    sample.reload();
    jobs.reload();
    iocs.reload();
    diffs.reload();
  };

  const current = sample.data;
  const caseId = current?.case_id;
  useTitle(current?.filename);

  const caseName = useMemo(
    () => (caseId != null ? cases.data?.find((c) => c.id === caseId)?.name ?? null : null),
    [caseId, cases.data]
  );

  if (!validId) {
    return (
      <>
        <PageHeader crumbs={[{ label: "Samples", to: "/samples" }, { label: "Unknown sample" }]} title="Sample not found" />
        <EmptyState icon={FileSearch} title="This sample link is not valid">
          <Link to="/samples">Return to the sample list</Link>
        </EmptyState>
      </>
    );
  }

  if (sample.error && !sample.data) {
    return (
      <>
        <PageHeader crumbs={[{ label: "Samples", to: "/samples" }, { label: `Sample #${sampleId}` }]} title={`Sample #${sampleId}`} />
        <ErrorState message={sample.error} onRetry={sample.reload} />
      </>
    );
  }

  if (!current) {
    return (
      <>
        <PageHeader crumbs={[{ label: "Samples", to: "/samples" }, { label: `Sample #${sampleId}` }]} title={`Sample #${sampleId}`} />
        <LoadingBlock label="Loading sample" rows={5} />
      </>
    );
  }

  const jobList = jobs.data ?? [];

  function selectTab(next: SampleTab) {
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next === "overview") p.delete("tab");
        else p.set("tab", next);
        return p;
      },
      { replace: true }
    );
  }

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Samples", to: "/samples" }, { label: current.filename }]}
        title={current.filename}
        badges={
          <>
            <SampleStatusBadge status={current.status} />
            <AnalysisStatusBadge status={current.analysis_status} />
            <Badge tone="tag">{current.detected_type ?? "unknown type"}</Badge>
            <Badge tone="neutral">{formatBytes(current.size_bytes)}</Badge>
          </>
        }
        subtitle={
          <span className="sample-hash-line">
            <span className="diff-label">SHA-256</span>
            <HashValue value={current.sha256} label="SHA-256" />
          </span>
        }
        actions={
          canAnalyze ? (
            <>
              <Button variant="primary" icon={Play} onClick={() => setRunOpen(true)}>
                Run analysis
              </Button>
              <Button variant="secondary" icon={GitCompare} onClick={() => setDiffOpen(true)}>
                Differential
              </Button>
            </>
          ) : undefined
        }
      />

      {!canAnalyze && (
        <div style={{ marginBottom: 16 }}>
          <Notice tone="info">Viewer accounts can read this sample. An analyst account is needed to run analyses.</Notice>
        </div>
      )}

      {notice && (
        <div style={{ marginBottom: 16 }}>
          <Notice tone={notice.tone === "ok" ? "ok" : "err"}>
            {notice.text} {notice.href && <Link to={notice.href}>{notice.label ?? "Open"}</Link>}
          </Notice>
        </div>
      )}

      <Tabs
        idBase={tabsBase}
        label="Sample sections"
        value={tab}
        onChange={selectTab}
        tabs={SAMPLE_TABS.map((t) => ({
          ...t,
          count:
            t.id === "jobs"
              ? jobs.data?.length
              : t.id === "iocs"
                ? iocs.data?.length
                : t.id === "differential"
                  ? diffs.data?.length
                  : undefined,
        }))}
      />

      <TabPanel idBase={tabsBase} id="overview" value={tab}>
        {jobs.error || iocs.error ? (
          <div style={{ marginBottom: 16 }}>
            <ErrorState message={jobs.error ?? iocs.error ?? ""} onRetry={reloadAll} />
          </div>
        ) : null}
        {jobs.data && iocs.data && diffs.data ? (
          <OverviewTab
            sample={current}
            jobs={jobList}
            iocs={iocs.data}
            diffs={diffs.data}
            caseName={caseName}
            canAnalyze={canAnalyze}
            onEditTags={() => setTagsOpen(true)}
          />
        ) : (
          <LoadingBlock rows={5} />
        )}
      </TabPanel>

      <TabPanel idBase={tabsBase} id="jobs" value={tab}>
        {jobs.error ? (
          <ErrorState message={jobs.error} onRetry={jobs.reload} />
        ) : !jobs.data ? (
          <LoadingBlock rows={4} />
        ) : (
          <JobsHistoryTab jobs={jobList} canAnalyze={canAnalyze} onRun={() => setRunOpen(true)} />
        )}
      </TabPanel>

      <TabPanel idBase={tabsBase} id="findings" value={tab}>
        {jobs.data ? <FindingsTab jobs={jobList} /> : <LoadingBlock rows={4} />}
      </TabPanel>

      <TabPanel idBase={tabsBase} id="behavior" value={tab}>
        {jobs.data ? <BehaviorTab jobs={jobList} /> : <LoadingBlock rows={4} />}
      </TabPanel>

      <TabPanel idBase={tabsBase} id="iocs" value={tab}>
        <IocsTab sampleId={sampleId} iocs={iocs.data} iocsError={iocs.error} reloadIocs={iocs.reload} />
      </TabPanel>

      <TabPanel idBase={tabsBase} id="attack" value={tab}>
        {jobs.data ? <AttackTab jobs={jobList} /> : <LoadingBlock rows={4} />}
      </TabPanel>

      <TabPanel idBase={tabsBase} id="differential" value={tab}>
        {diffs.error ? (
          <ErrorState message={diffs.error} onRetry={diffs.reload} />
        ) : !diffs.data ? (
          <LoadingBlock rows={4} />
        ) : (
          <DifferentialTab diffs={diffs.data} canAnalyze={canAnalyze} onRun={() => setDiffOpen(true)} />
        )}
      </TabPanel>

      {canAnalyze && (
        <>
          <RunAnalysisDialog
            open={runOpen}
            onClose={() => setRunOpen(false)}
            sampleId={sampleId}
            onDone={(job) => {
              setRunOpen(false);
              setNotice({
                tone: job.status === "completed" ? "ok" : "err",
                text:
                  job.status === "completed"
                    ? `Job #${job.id} completed.`
                    : `Job #${job.id} finished as ${job.status.replace("_", " ")}${job.error ? `: ${job.error}` : "."}`,
                href: `/jobs/${job.id}`,
                label: "View job",
              });
              reloadAll();
            }}
          />
          <DifferentialDialog open={diffOpen} onClose={() => setDiffOpen(false)} sample={current} />
          <TagsDialog
            open={tagsOpen}
            onClose={() => setTagsOpen(false)}
            sample={current}
            onDone={() => {
              setTagsOpen(false);
              sample.reload();
            }}
          />
        </>
      )}

    </>
  );
}
