import { GitCompare } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Differential, type Sample } from "../api";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, JobStatusBadge, LoadingBlock, Panel, StatTile, TableScroll } from "../components/ui/primitives";
import { describeConditions, formatDateTime, labelize } from "../lib/format";
import { useResource } from "../lib/useResource";
import { useTitle } from "../lib/useTitle";

export function Differential() {
  useTitle("Differential");
  const diffs = useResource<Differential[]>((s) => api.get("/differential", s), []);
  const samples = useResource<Sample[]>((s) => api.get("/samples", s), []);
  const [query, setQuery] = useState("");

  const sampleNames = useMemo(() => {
    const map = new Map<number, string>();
    for (const s of samples.data ?? []) map.set(s.id, s.filename);
    return map;
  }, [samples.data]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (diffs.data ?? []).filter((d) => {
      if (!q) return true;
      return `${d.id} ${d.sample_id} ${sampleNames.get(d.sample_id) ?? ""} ${d.executor}`.toLowerCase().includes(q);
    });
  }, [diffs.data, query, sampleNames]);

  const all = diffs.data ?? [];
  const withChanges = all.filter((d) => d.findings.length > 0).length;
  const running = all.filter((d) => d.status === "running" || d.status === "pending").length;

  return (
    <div>
      <PageHeader
        title="Differential analysis"
        subtitle="Behavior comparisons between a baseline run and a variant run of the same sample. Only recorded results are shown."
      />

      <div className="grid-auto" style={{ marginBottom: 20 }}>
        <StatTile label="Analyses" value={diffs.data ? all.length : "—"} />
        <StatTile label="With recorded changes" value={diffs.data ? withChanges : "—"} />
        <StatTile label="Pending or running" value={diffs.data ? running : "—"} />
      </div>

      <Panel
        title="Analyses"
        actions={
          <input
            className="input"
            type="search"
            placeholder="Filter by id, sample or executor"
            aria-label="Filter differential analyses"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ maxWidth: 280 }}
          />
        }
        flush
      >
        {diffs.loading && diffs.data === undefined ? (
          <div style={{ padding: 16 }}>
            <LoadingBlock label="Loading differential analyses" rows={4} />
          </div>
        ) : diffs.error ? (
          <div style={{ padding: 16 }}>
            <ErrorState message={diffs.error} onRetry={diffs.reload} />
          </div>
        ) : all.length === 0 ? (
          <EmptyState icon={GitCompare} title="No differential analyses yet">
            Run a differential analysis from a sample's workspace to compare a variant run against a baseline.
          </EmptyState>
        ) : rows.length === 0 ? (
          <EmptyState icon={GitCompare} title="No matches">
            No analysis matches "{query}".
          </EmptyState>
        ) : (
          <TableScroll label="Differential analyses">
            <table>
              <thead>
                <tr>
                  <th scope="col">Analysis</th>
                  <th scope="col">Sample</th>
                  <th scope="col">Executor</th>
                  <th scope="col">Baseline conditions</th>
                  <th scope="col">Status</th>
                  <th scope="col">Changes</th>
                  <th scope="col">Created</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <Link to={`/differential/${d.id}`}>#{d.id}</Link>
                    </td>
                    <td>
                      <Link to={`/samples/${d.sample_id}`}>{sampleNames.get(d.sample_id) ?? `sample #${d.sample_id}`}</Link>
                    </td>
                    <td className="mono">{labelize(d.executor)}</td>
                    <td className="mono text-sm">{describeConditions(d.baseline_conditions)}</td>
                    <td>
                      <JobStatusBadge status={d.status} />
                    </td>
                    <td>{d.findings.length}</td>
                    <td className="text-sm">{formatDateTime(d.created_at)}</td>
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
