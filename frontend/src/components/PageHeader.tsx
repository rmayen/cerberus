import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import type { ReactNode } from "react";

export interface Crumb {
  label: string;
  to?: string;
}

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="breadcrumbs">
      <ol>
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <li key={`${item.label}-${index}`} style={{ display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0 }}>
              {index > 0 && <ChevronRight size={13} aria-hidden="true" />}
              {item.to && !last ? (
                <Link to={item.to}>{item.label}</Link>
              ) : (
                <span aria-current={last ? "page" : undefined}>{item.label}</span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function PageHeader({
  crumbs,
  title,
  subtitle,
  actions,
  badges,
}: {
  crumbs?: Crumb[];
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  badges?: ReactNode;
}) {
  return (
    <header className="page-header">
      {crumbs && crumbs.length > 0 && <Breadcrumbs items={crumbs} />}
      <div className="page-header-row">
        <div style={{ minWidth: 0, flex: "1 1 360px" }}>
          <h1 style={{ overflowWrap: "anywhere" }}>{title}</h1>
          {badges && <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>{badges}</div>}
          {subtitle && <p className="page-subtitle" style={{ marginTop: 6 }}>{subtitle}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
    </header>
  );
}
