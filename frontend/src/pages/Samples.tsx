import { FileSearch, Upload } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Case, type Sample, type SampleUploadResult } from "../api";
import { useAuth } from "../auth";
import { UploadDialog } from "../components/dialogs";
import { PageHeader } from "../components/PageHeader";
import { SamplesTable } from "../components/Tables";
import { EmptyState, ErrorState, LoadingBlock, Notice, Panel, Button } from "../components/ui/primitives";
import { SelectField, TextField } from "../components/ui/Fields";
import { plural } from "../lib/format";
import { SAMPLE_STATUS } from "../lib/status";
import { useResource } from "../lib/useResource";
import { useTitle } from "../lib/useTitle";

export function Samples() {
  useTitle("Samples");
  const { canAnalyze } = useAuth();
  const samples = useResource<Sample[]>((s) => api.get("/samples", s), []);
  const cases = useResource<Case[]>((s) => api.get("/cases", s), []);

  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const [caseFilter, setCaseFilter] = useState("");
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState<{ tone: "ok" | "info"; text: string; sampleId?: number } | null>(null);

  const caseNames = useMemo(() => new Map((cases.data ?? []).map((c) => [c.id, c.name])), [cases.data]);
  const types = useMemo(
    () => [...new Set((samples.data ?? []).map((s) => s.detected_type ?? "unknown"))].sort(),
    [samples.data]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (samples.data ?? []).filter((s) => {
      if (q && !s.filename.toLowerCase().includes(q) && !s.sha256.toLowerCase().includes(q)) return false;
      if (type && (s.detected_type ?? "unknown") !== type) return false;
      if (status && s.status !== status) return false;
      if (caseFilter && String(s.case_id ?? "none") !== caseFilter) return false;
      return true;
    });
  }, [samples.data, query, type, status, caseFilter]);

  const filtersActive = Boolean(query || type || status || caseFilter);

  function onUploaded(result: SampleUploadResult) {
    setUploading(false);
    setNotice(
      result.duplicate
        ? { tone: "info", text: `This file is already in the inventory as ${result.sample.filename}.`, sampleId: result.sample.id }
        : { tone: "ok", text: `Uploaded ${result.sample.filename}. Its status is ${SAMPLE_STATUS[result.sample.status]?.label ?? result.sample.status}.`, sampleId: result.sample.id }
    );
    samples.reload();
  }

  return (
    <>
      <PageHeader
        title="Samples"
        subtitle="Uploaded artifacts under analysis. Files are stored encrypted, named by hash, and never executed by the application."
        actions={
          canAnalyze ? (
            <Button variant="primary" icon={Upload} onClick={() => setUploading(true)}>
              Upload sample
            </Button>
          ) : undefined
        }
      />

      {!canAnalyze && (
        <div style={{ marginBottom: 16 }}>
          <Notice tone="info">Your viewer role can read samples and results. An analyst account is needed to upload or run analyses.</Notice>
        </div>
      )}

      {notice && (
        <div style={{ marginBottom: 16 }}>
          <Notice tone={notice.tone === "ok" ? "ok" : "info"}>
            {notice.text}{" "}
            {notice.sampleId !== undefined && (
              <Link to={`/samples/${notice.sampleId}`}>Open sample</Link>
            )}
          </Notice>
        </div>
      )}

      <Panel>
        <form
          role="search"
          aria-label="Filter samples"
          className="toolbar"
          onSubmit={(e) => e.preventDefault()}
          style={{ marginBottom: 16 }}
        >
          <TextField
            label="Search filename or hash"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="invoice, 9f3a…"
            hint="Matches as you type."
          />
          <SelectField label="Detected type" value={type} onChange={(e) => setType(e.target.value)} className="field-narrow">
            <option value="">All types</option>
            {types.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </SelectField>
          <SelectField label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="field-narrow">
            <option value="">All statuses</option>
            {Object.entries(SAMPLE_STATUS).map(([value, meta]) => (
              <option key={value} value={value}>
                {meta.label}
              </option>
            ))}
          </SelectField>
          <SelectField label="Case" value={caseFilter} onChange={(e) => setCaseFilter(e.target.value)} className="field-narrow">
            <option value="">All cases</option>
            <option value="none">No case</option>
            {(cases.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </SelectField>
          {filtersActive && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setQuery("");
                setType("");
                setStatus("");
                setCaseFilter("");
              }}
            >
              Clear filters
            </Button>
          )}
        </form>

        {samples.data && samples.data.length > 0 && (
          <div className="chip-group" role="group" aria-label="Filter by status" style={{ marginBottom: 12 }}>
            {(Object.keys(SAMPLE_STATUS) as (keyof typeof SAMPLE_STATUS)[]).map((st) => {
              const n = (samples.data ?? []).filter((s) => s.status === st).length;
              return (
                <button
                  key={st}
                  type="button"
                  className="chip"
                  aria-pressed={status === st}
                  onClick={() => setStatus(status === st ? "" : st)}
                >
                  {SAMPLE_STATUS[st].label} <span className="tab-count">{n}</span>
                </button>
              );
            })}
          </div>
        )}

        <p className="text-xs muted" role="status" aria-live="polite" style={{ marginBottom: 10 }}>
          {samples.data ? `Showing ${filtered.length} of ${plural(samples.data.length, "sample")}` : "Loading samples…"}
        </p>

        {samples.error ? (
          <ErrorState message={samples.error} onRetry={samples.reload} />
        ) : !samples.data ? (
          <LoadingBlock rows={5} />
        ) : samples.data.length === 0 ? (
          <EmptyState
            icon={FileSearch}
            title="No samples yet"
            action={
              canAnalyze ? (
                <Button variant="primary" icon={Upload} onClick={() => setUploading(true)}>
                  Upload the first sample
                </Button>
              ) : undefined
            }
          >
            Samples appear here after an analyst uploads them.
          </EmptyState>
        ) : (
          <SamplesTable
            samples={filtered}
            caseNames={caseNames}
            emptyText="No samples match these filters."
          />
        )}
      </Panel>

      {canAnalyze && <UploadDialog open={uploading} onClose={() => setUploading(false)} onDone={onUploaded} />}
    </>
  );
}
