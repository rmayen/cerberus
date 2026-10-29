import { ArrowLeft, GitCompare } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api, type Differential, type DifferentialFinding, type DiffEvent, type Sample } from "../api";
import { PageHeader } from "../components/PageHeader";
import {
  ConfidenceMeter,
  EmptyState,
  ErrorState,
  JobStatusBadge,
  LoadingBlock,
  Panel,
} from "../components/ui/primitives";
import { CONFIDENCE_ORDER } from "../lib/status";
import { formatDateTime, formatValue, labelize } from "../lib/format";
import { useResource } from "../lib/useResource";
import { useTitle } from "../lib/useTitle";

/** Events shown inline before the rest move behind a disclosure. */
const INLINE_EVENTS = 4;

export function DifferentialDetail() {
  const { id = "" } = useParams();
  const diff = useResource<Differential>((s) => api.get(`/differential/${id}`, s), [id]);
  // Only request the sample once the run has told us which sample it belongs to.
  const sampleId = diff.data?.sample_id;
  const sample = useResource<Sample | null>(
    (s) => (sampleId != null ? api.get<Sample>(`/samples/${sampleId}`, s) : Promise.resolve(null)),
    [sampleId]
  );
  useTitle(diff.data ? `Differential #${diff.data.id}` : "Differential");

  if (diff.loading && diff.data === undefined) {
    return <LoadingBlock label="Loading differential analysis" rows={5} />;
  }
  if (diff.error || !diff.data) {
    return <ErrorState message={diff.error ?? "This differential analysis could not be found."} onRetry={diff.reload} />;
  }

  const d = diff.data;
  const sampleName = sample.data?.filename ?? `sample #${d.sample_id}`;
  const changedAxes = new Set(d.findings.map((f) => f.axis));
  const held = Object.entries(d.baseline_conditions).filter(([k]) => !changedAxes.has(k));
  const top = CONFIDENCE_ORDER.find((c) => d.findings.some((f) => f.confidence === c));

  return (
    <div>
      <PageHeader
        crumbs={[{ label: "Differential", to: "/differential" }, { label: `#${d.id}` }]}
        title={`Differential analysis #${d.id}`}
        badges={<JobStatusBadge status={d.status} />}
        subtitle={
          <>
            Sample <Link to={`/samples/${d.sample_id}`}>{sampleName}</Link>, executor {labelize(d.executor)}
          </>
        }
        actions={
          <Link className="btn btn-secondary" to="/differential">
            <ArrowLeft size={14} aria-hidden="true" /> All analyses
          </Link>
        }
      />

      <section aria-label="Run summary" className="diff-summary">
        <div className="diff-cell">
          <span className="diff-label">Changed conditions</span>
          <span className="diff-value">{d.findings.length}</span>
        </div>
        <div className="diff-cell">
          <span className="diff-label">Highest confidence</span>
          <span className="diff-value diff-value-sm">{top ? <ConfidenceMeter confidence={top} /> : "None recorded"}</span>
        </div>
        <div className="diff-cell">
          <span className="diff-label">Held at baseline</span>
          <span className="diff-value">{held.length}</span>
        </div>
        <div className="diff-cell">
          <span className="diff-label">Created</span>
          <span className="diff-value diff-value-sm">{formatDateTime(d.created_at)}</span>
        </div>
        <div className="diff-cell">
          <span className="diff-label">Finished</span>
          <span className="diff-value diff-value-sm">{formatDateTime(d.finished_at)}</span>
        </div>
      </section>

      <nav className="diff-links" aria-label="Related records">
        <Link to={`/samples/${d.sample_id}`}>Sample workspace</Link>
        <Link to={`/samples/${d.sample_id}?tab=differential`}>Differential runs for this sample</Link>
        <Link to={`/samples/${d.sample_id}?tab=findings`}>Findings for this sample</Link>
      </nav>

      {d.findings.length === 0 ? (
        <Panel>
          <EmptyState icon={GitCompare} title="No changes recorded">
            {d.status === "completed"
              ? "The variant run did not differ from the baseline on any recorded condition."
              : "Results appear here once the analysis finishes."}
          </EmptyState>
        </Panel>
      ) : (
        <div className="diff-findings" aria-label="Changed conditions">
          {d.findings.map((f) => (
            <FindingCard key={f.id} finding={f} />
          ))}
        </div>
      )}

      {held.length > 0 && (
        <Panel title="Held at baseline" description="Recorded conditions that were not changed in this analysis." className="diff-held">
          <ul className="diff-held-list">
            {held.map(([k, v]) => (
              <li key={k}>
                <span className="diff-label">{labelize(k)}</span>
                <span className="mono">{formatValue(v)}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}

function FindingCard({ finding: f }: { finding: DifferentialFinding }) {
  return (
    <article className="diff-finding">
      <header className="diff-finding-head">
        <div className="diff-finding-title">
          <span className="diff-label">Condition</span>
          <h3>{labelize(f.axis)}</h3>
        </div>
        <ConfidenceMeter confidence={f.confidence} />
      </header>

      <p className="diff-summary-text">{f.summary}</p>

      <div className="diff-compare">
        <div className="diff-value-pair">
          <div>
            <span className="diff-label">Baseline value</span>
            <span className="mono diff-raw">{formatValue(f.baseline_value)}</span>
          </div>
          <span className="diff-arrow" aria-hidden="true">→</span>
          <div>
            <span className="diff-label">Variant value</span>
            <span className="mono diff-raw">{formatValue(f.variant_value)}</span>
          </div>
        </div>

        <div className="diff-sides">
          <EventSide
            title="Baseline run"
            caption="Events absent in the variant"
            events={f.removed}
            tone="baseline"
          />
          <EventSide title="Variant run" caption="New events in the variant" events={f.added} tone="variant" />
        </div>
      </div>
    </article>
  );
}

function EventSide({
  title,
  caption,
  events,
  tone,
}: {
  title: string;
  caption: string;
  events: DiffEvent[];
  tone: "baseline" | "variant";
}) {
  const inline = events.slice(0, INLINE_EVENTS);
  const rest = events.slice(INLINE_EVENTS);
  return (
    <div className={`diff-side diff-side-${tone}`}>
      <div className="diff-side-head">
        <span>{title}</span>
        <span className="diff-count">{events.length}</span>
      </div>
      <p className="diff-caption">{caption}</p>
      {events.length === 0 ? (
        <p className="muted text-sm">No events in this group.</p>
      ) : (
        <>
          <ul className="diff-events">
            {inline.map((e, i) => (
              <EventRow key={i} event={e} />
            ))}
          </ul>
          {rest.length > 0 && (
            <details className="diff-more">
              <summary>
                Show {rest.length} more {rest.length === 1 ? "event" : "events"}
              </summary>
              <ul className="diff-events">
                {rest.map((e, i) => (
                  <EventRow key={i} event={e} />
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}

function EventRow({ event: e }: { event: DiffEvent }) {
  return (
    <li className="diff-event">
      <span className="diff-event-cat">{e.category}</span>
      <span className="diff-event-act">{e.action}</span>
      <span className="mono diff-event-target">{e.target}</span>
    </li>
  );
}
