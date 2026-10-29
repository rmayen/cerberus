import { Briefcase, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Case, type Sample } from "../api";
import { useAuth } from "../auth";
import { PageHeader } from "../components/PageHeader";
import { Button, EmptyState, ErrorState, LoadingBlock, Notice, Panel } from "../components/ui/primitives";
import { formatDateTime, errorMessage } from "../lib/format";
import { useResource } from "../lib/useResource";
import { useTitle } from "../lib/useTitle";

export function Cases() {
  useTitle("Cases");
  const { user } = useAuth();
  const cases = useResource<Case[]>((s) => api.get("/cases", s), []);
  const samples = useResource<Sample[]>((s) => api.get("/samples", s), []);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const canCreate = user?.role === "analyst" || user?.role === "administrator";

  const countByCase = useMemo(() => {
    const map = new Map<number, number>();
    for (const s of samples.data ?? []) {
      if (s.case_id != null) map.set(s.case_id, (map.get(s.case_id) ?? 0) + 1);
    }
    return map;
  }, [samples.data]);

  async function create() {
    if (!name.trim()) return;
    setError("");
    setSaving(true);
    try {
      await api.post("/cases", { name, description: description || null });
      setName("");
      setDescription("");
      cases.reload();
    } catch (e) {
      setError(errorMessage(e, "The case could not be created."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHeader title="Cases" subtitle="Groups of related samples, their analysis jobs and reports." />

      {canCreate && (
        <Panel title="New case" >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void create();
            }}
            style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", alignItems: "end" }}
          >
            <label style={{ display: "grid", gap: 4 }}>
              <span className="text-sm">Name</span>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
            </label>
            <label style={{ display: "grid", gap: 4 }}>
              <span className="text-sm">Description (optional)</span>
              <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
            </label>
            <div>
              <Button type="submit" variant="primary" icon={Plus} disabled={saving || !name.trim()}>
                {saving ? "Creating…" : "Create case"}
              </Button>
            </div>
          </form>
          {error && (
            <div style={{ marginTop: 12 }}>
              <Notice tone="err">{error}</Notice>
            </div>
          )}
        </Panel>
      )}

      {cases.loading && cases.data === undefined ? (
        <LoadingBlock label="Loading cases" rows={3} />
      ) : cases.error ? (
        <ErrorState message={cases.error} onRetry={cases.reload} />
      ) : (cases.data ?? []).length === 0 ? (
        <EmptyState icon={Briefcase} title="No cases yet">
          {canCreate ? "Create a case above to group related samples." : "Cases created by analysts will appear here."}
        </EmptyState>
      ) : (
        <ul className="case-grid" style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
          {(cases.data ?? []).map((c) => (
            <li key={c.id}>
              <Link to={`/cases/${c.id}`} className="panel" style={{ display: "block", padding: 16, height: "100%", textDecoration: "none", color: "inherit" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <Briefcase size={16} aria-hidden="true" />
                  <strong style={{ overflowWrap: "anywhere" }}>{c.name}</strong>
                </div>
                <p className="text-sm muted" style={{ margin: "8px 0", minHeight: "2.6em" }}>
                  {c.description || "No description."}
                </p>
                <div className="text-sm">
                  {samples.data ? `${countByCase.get(c.id) ?? 0} sample(s)` : "Samples loading"} · created {formatDateTime(c.created_at)}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
