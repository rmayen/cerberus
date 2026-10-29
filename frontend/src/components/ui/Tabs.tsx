import { useRef, type KeyboardEvent, type ReactNode } from "react";

export interface TabDef<T extends string> {
  id: T;
  label: string;
  count?: number;
}

/**
 * Accessible tab list. Arrow keys, Home and End move between tabs (roving tabindex).
 * The parent renders the active panel with TabPanel so ids and labels stay linked.
 */
export function Tabs<T extends string>({
  idBase,
  label,
  tabs,
  value,
  onChange,
}: {
  /** Shared with TabPanel so the ARIA ids match. Create it with useId() in the parent. */
  idBase: string;
  label: string;
  tabs: TabDef<T>[];
  value: T;
  onChange: (id: T) => void;
}) {
  const base = idBase;
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function focusTab(index: number) {
    const next = tabs[(index + tabs.length) % tabs.length];
    refs.current[next.id]?.focus();
    onChange(next.id);
  }

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      focusTab(index + 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      focusTab(index - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      focusTab(0);
    } else if (e.key === "End") {
      e.preventDefault();
      focusTab(tabs.length - 1);
    }
  }

  return (
    <div role="tablist" aria-label={label} className="tablist">
      {tabs.map((tab, index) => {
        const selected = tab.id === value;
        return (
          <button
            key={tab.id}
            ref={(el) => {
              refs.current[tab.id] = el;
            }}
            type="button"
            role="tab"
            id={tabId(base, tab.id)}
            aria-selected={selected}
            aria-controls={tabPanelId(base, tab.id)}
            tabIndex={selected ? 0 : -1}
            className="tab"
            onClick={() => onChange(tab.id)}
            onKeyDown={(e) => onKeyDown(e, index)}
          >
            {tab.label}
            {tab.count !== undefined && <span className="tab-count">{tab.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

function tabId(base: string, id: string) {
  return `${base}-tab-${id}`;
}
function tabPanelId(base: string, id: string) {
  return `${base}-panel-${id}`;
}

/** Renders only the active tab's content, labelled by its tab. */
export function TabPanel<T extends string>({
  idBase,
  id,
  value,
  children,
}: {
  idBase: string;
  id: T;
  value: T;
  children: ReactNode;
}) {
  if (id !== value) return null;
  return (
    <div role="tabpanel" id={tabPanelId(idBase, id)} aria-labelledby={tabId(idBase, id)} tabIndex={-1}>
      {children}
    </div>
  );
}
