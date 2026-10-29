import { Link } from "react-router-dom";
import type { AttackMapping, Finding } from "../api";
import { formatDateTime, formatValue, labelize, plural } from "../lib/format";
import { attackUrl } from "../lib/status";
import { SeverityBadge, Badge, TableScroll } from "./ui/primitives";

/** Evidence is an array of objects from the analysis engine. Render every field as text. */
export function EvidenceList({ evidence }: { evidence: Record<string, unknown>[] }) {
  if (evidence.length === 0) {
    return <p className="muted text-sm">No evidence recorded for this item.</p>;
  }
  return (
    <ol className="evidence-list" style={{ listStyle: "none" }}>
      {evidence.map((item, index) => (
        <li key={index}>
          {Object.entries(item).map(([key, value]) => (
            <div key={key} style={{ display: "contents" }}>
              <span className="k">{labelize(key)}</span>
              <span className="v">{formatValue(value)}</span>
            </div>
          ))}
        </li>
      ))}
    </ol>
  );
}

export function FindingList({
  findings,
  showJob,
  emptyText = "No findings were produced for this run.",
}: {
  findings: Finding[];
  showJob?: boolean;
  emptyText?: string;
}) {
  if (findings.length === 0) {
    return <p className="muted text-sm">{emptyText}</p>;
  }
  return (
    <ul className="list-plain" aria-label="Behavior findings">
      {findings.map((f) => (
        <li key={f.id} id={`finding-${f.id}`} style={{ scrollMarginTop: 80 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <SeverityBadge severity={f.severity} />
            <Badge tone="tag">{f.category}</Badge>
            {showJob && (
              <Link to={`/jobs/${f.job_id}`} className="text-sm">
                Job #{f.job_id}
              </Link>
            )}
          </div>
          <h3 style={{ marginTop: 8, overflowWrap: "anywhere" }}>{f.title}</h3>
          <p className="text-sm muted" style={{ marginTop: 4, overflowWrap: "anywhere" }}>
            {f.explanation}
          </p>
          <details className="details" style={{ marginTop: 10 }}>
            <summary>
              Evidence ({plural(f.evidence.length, "item")})
            </summary>
            <div className="details-body">
              <EvidenceList evidence={f.evidence} />
            </div>
          </details>
          <p className="text-xs muted" style={{ marginTop: 6 }}>
            Recorded {formatDateTime(f.created_at)}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function AttackTable({ mappings, emptyText = "No ATT&CK techniques were mapped for this run." }: { mappings: AttackMapping[]; emptyText?: string }) {
  if (mappings.length === 0) {
    return <p className="muted text-sm">{emptyText}</p>;
  }
  return (
    <TableScroll label="MITRE ATT&CK techniques">
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">Technique</th>
            <th scope="col">Name</th>
            <th scope="col">Tactic</th>
            <th scope="col" className="cell-wrap">Why it was mapped</th>
          </tr>
        </thead>
        <tbody>
          {mappings.map((m) => {
            const url = attackUrl(m.technique_id);
            return (
              <tr key={m.id}>
                <td className="mono" style={{ whiteSpace: "nowrap" }}>
                  {url ? (
                    <a href={url} target="_blank" rel="noopener noreferrer">
                      {m.technique_id}
                      <span className="sr-only"> (opens MITRE ATT&amp;CK in a new tab)</span>
                    </a>
                  ) : (
                    m.technique_id
                  )}
                </td>
                <td className="cell-wrap" style={{ color: "var(--color-ink)" }}>
                  {m.technique_name}
                </td>
                <td style={{ whiteSpace: "nowrap" }}>{m.tactic}</td>
                <td className="cell-wrap">{m.explanation}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableScroll>
  );
}
