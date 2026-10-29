import {
  Briefcase,
  GitCompare,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  FileSearch,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { cn } from "../lib/format";
import { Button, LoadingBlock } from "./ui/primitives";
import { Dialog } from "./ui/Dialog";

const NAV: { to: string; label: string; icon: LucideIcon; end?: boolean }[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/samples", label: "Samples", icon: FileSearch },
  { to: "/cases", label: "Cases", icon: Briefcase },
  { to: "/jobs", label: "Jobs", icon: ListChecks },
  { to: "/differential", label: "Differential", icon: GitCompare },
];

const COLLAPSE_KEY = "cerberus.sidebarCollapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(value: boolean) {
  try {
    localStorage.setItem(COLLAPSE_KEY, value ? "1" : "0");
  } catch {
    /* preference is optional */
  }
}

function Brand({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <NavLink to="/" className="brand" onClick={onNavigate}>
      <span className="brand-mark" aria-hidden="true">
        <ShieldCheck size={17} />
      </span>
      <span className="brand-text">Cerberus</span>
    </NavLink>
  );
}

function NavItems({ idPrefix, onNavigate, collapsed }: { idPrefix: string; onNavigate?: () => void; collapsed?: boolean }) {
  return (
    <ul className="nav" id={`${idPrefix}-nav`} style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <li key={to}>
          <NavLink to={to} end={end} className="nav-link" onClick={onNavigate} title={collapsed ? label : undefined}>
            <Icon size={18} aria-hidden="true" style={{ flex: "none" }} />
            <span className="nav-label">{label}</span>
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

export function Layout() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const mainRef = useRef<HTMLElement>(null);
  const firstRender = useRef(true);

  useEffect(() => {
    setDrawerOpen(false);
    // Move focus to the new page so keyboard and screen-reader users start at its content.
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    mainRef.current?.focus();
  }, [location.pathname]);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      writeCollapsed(!prev);
      return !prev;
    });
  }

  const account = (
    <div className="sidebar-foot">
      <div style={{ minWidth: 0 }}>
        <div className="text-sm foot-text" style={{ color: "var(--color-ink)", fontWeight: 600, overflowWrap: "anywhere" }}>
          {user?.username}
        </div>
        <div className="text-xs muted foot-text">{user?.role}</div>
      </div>
      <Button variant="ghost" size="sm" icon={LogOut} onClick={logout} className="btn-block" aria-label="Sign out">
        <span className="foot-text">Sign out</span>
      </Button>
    </div>
  );

  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>

      {/* Desktop sidebar (>= 1024px). Hidden on smaller screens; the drawer covers those. */}
      <aside className={cn("sidebar", collapsed && "is-collapsed")} aria-label="Primary">
        <Brand />
        <nav aria-label="Main">
          <NavItems idPrefix="desktop" collapsed={collapsed} />
        </nav>
        <div style={{ marginTop: "auto" }}>
          <button
            type="button"
            className={cn("btn btn-ghost btn-sm", collapsed ? "btn-icon" : "btn-block")}
            style={collapsed ? { width: "100%" } : undefined}
            onClick={toggleCollapsed}
            aria-expanded={!collapsed}
            aria-controls="desktop-nav"
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          >
            {collapsed ? <PanelLeftOpen size={16} aria-hidden="true" /> : <PanelLeftClose size={16} aria-hidden="true" />}
            <span className="foot-text">Collapse</span>
          </button>
        </div>
        {account}
      </aside>

      {/* Top bar with drawer trigger (< 1024px). */}
      <header className="topbar">
        <Button
          variant="ghost"
          size="sm"
          icon={Menu}
          onClick={() => setDrawerOpen(true)}
          aria-label="Open navigation"
          aria-haspopup="dialog"
          aria-expanded={drawerOpen}
        >
          <span className="sr-only">Menu</span>
        </Button>
        <Brand />
      </header>

      <Dialog open={drawerOpen} onClose={() => setDrawerOpen(false)} title="Navigation" drawer>
        <nav aria-label="Main">
          <NavItems idPrefix="drawer" onNavigate={() => setDrawerOpen(false)} />
        </nav>
        <div style={{ marginTop: 18 }}>{account}</div>
      </Dialog>

      <div className={cn("app-main", collapsed && "is-collapsed")}>
        <main id="main" ref={mainRef} tabIndex={-1} className="page">
          <Suspense fallback={<LoadingBlock label="Loading page" rows={4} height={22} />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
