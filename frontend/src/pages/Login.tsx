import { LoaderCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useAuth } from "../auth";
import { Notice } from "../components/ui/primitives";
import { TextField } from "../components/ui/Fields";
import { useTitle } from "../lib/useTitle";

/** Cerberus mark: three heads (nodes) converging on one core. Drawn as SVG, not an icon font. */
export function CerberusMark({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" focusable="false" className="cerberus-mark">
      <defs>
        <linearGradient id="cerberus-mark-fill" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#1d2228" />
          <stop offset="1" stopColor="#111418" />
        </linearGradient>
        <linearGradient id="cerberus-mark-stroke" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#8ff0e0" />
          <stop offset="1" stopColor="#3fb8a6" />
        </linearGradient>
      </defs>
      <rect x="0.5" y="0.5" width="39" height="39" rx="11" fill="url(#cerberus-mark-fill)" stroke="rgba(95,214,196,0.3)" />
      <g fill="none" stroke="url(#cerberus-mark-stroke)" strokeWidth="2" strokeLinecap="round">
        <path d="M11 14 L20 25" />
        <path d="M20 10 L20 25" />
        <path d="M29 14 L20 25" />
        <path d="M20 25 L20 31" />
      </g>
      <circle cx="11" cy="14" r="3" fill="#8ff0e0" />
      <circle cx="20" cy="10" r="3" fill="#8ff0e0" />
      <circle cx="29" cy="14" r="3" fill="#8ff0e0" />
      <circle cx="20" cy="25" r="4.2" fill="#111418" stroke="url(#cerberus-mark-stroke)" strokeWidth="2" />
      <circle cx="20" cy="25" r="1.6" fill="#5fd6c4" />
    </svg>
  );
}

/**
 * Investigation graph: a sample entry point feeds a central analysis hub; telemetry nodes sit
 * on the pathways and results fan out to report and technique nodes. Fixed layout, no data,
 * no figures. Teal only. Depth comes from a dimmer back layer of telemetry nodes.
 */
function InvestigationGraph() {
  const entry: [number, number] = [70, 250];
  const hub: [number, number] = [372, 236];
  const stages: [number, number][] = [[196, 118], [228, 356], [520, 112]];
  const outputs: [number, number][] = [[672, 214], [598, 368]];
  const path = (pts: [number, number][]) => pts.map(([x, y], i) => `${i ? "L" : "M"}${x} ${y}`).join(" ");
  const pathways = [
    [entry, stages[0], hub],
    [entry, stages[1], hub],
    [stages[2], hub],
    [hub, outputs[0]],
    [hub, outputs[1]],
  ];
  const back: [number, number][] = [
    [120, 60], [160, 180], [300, 60], [420, 60], [540, 60], [640, 110], [120, 330], [300, 420],
    [430, 400], [520, 470], [650, 440], [210, 470], [60, 400], [600, 40], [470, 300],
  ];
  return (
    <svg className="login-graph" viewBox="0 0 720 500" aria-hidden="true" focusable="false">
      <g stroke="#5fd6c4" fill="none">
        {back.map(([x, y], i) => (
          <circle key={`b${i}`} cx={x} cy={y} r="2.5" fill="#5fd6c4" fillOpacity="0.28" stroke="none" />
        ))}
      </g>
      <g fill="none" stroke="#5fd6c4" strokeWidth="1.4" strokeOpacity="0.45">
        {pathways.map((pts, i) => (
          <path key={`p${i}`} d={path(pts)} className="login-path" style={{ animationDelay: `${i * 0.7}s` }} />
        ))}
      </g>
      <circle cx={hub[0]} cy={hub[1]} r="62" fill="none" stroke="#5fd6c4" strokeOpacity="0.12" />
      <circle className="login-hub-ring" cx={hub[0]} cy={hub[1]} r="40" fill="none" stroke="#5fd6c4" strokeOpacity="0.45" />
      <circle cx={hub[0]} cy={hub[1]} r="24" fill="#15191f" stroke="#8ff0e0" strokeWidth="1.5" />
      <circle cx={hub[0]} cy={hub[1]} r="7" fill="#8ff0e0" />
      <g>
        <rect x={entry[0] - 16} y={entry[1] - 16} width="32" height="32" rx="7" fill="#15191f" stroke="#5fd6c4" strokeOpacity="0.7" />
        <circle cx={entry[0]} cy={entry[1]} r="4" fill="#8ff0e0" />
      </g>
      {stages.map(([x, y], i) => (
        <g key={`st${i}`}>
          <circle cx={x} cy={y} r="11" fill="#15191f" stroke="#5fd6c4" strokeOpacity="0.6" strokeWidth="1.25" />
          <circle cx={x} cy={y} r="3.5" fill="#5fd6c4" />
        </g>
      ))}
      {outputs.map(([x, y], i) => (
        <g key={`out${i}`}>
          <rect x={x - 12} y={y - 12} width="24" height="24" rx="6" fill="#15191f" stroke="#5fd6c4" strokeOpacity="0.5" />
          <circle cx={x} cy={y} r="3" fill="#8ff0e0" fillOpacity="0.8" />
        </g>
      ))}
    </svg>
  );
}

/** Capabilities as described in the project README. No figures. */
const CAPABILITIES: { title: string; text: string }[] = [
  { title: "Behavior analysis", text: "Explainable findings with severity and the evidence behind each one." },
  { title: "Differential analysis", text: "Runs that vary one condition at a time, compared into dependencies with a confidence level." },
  { title: "IOC extraction", text: "Typed indicators with JSON and CSV export." },
  { title: "MITRE ATT&CK mapping", text: "Observed behaviors mapped to techniques, each with its explanation." },
  { title: "Reports", text: "HTML and PDF reports with timeline, findings, IOCs, and containment recommendations." },
];

/** Text set by the auth provider on sign-out. Shown as a neutral confirmation, not a warning. */
const SIGNED_OUT_NOTICE = "You have signed out.";

export function Login() {
  const { login, notice } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useTitle("Sign in");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(username, password);
    } catch (err) {
      const rateLimited = err instanceof Error && "status" in err && (err as { status: number }).status === 401;
      setError(
        rateLimited
          ? "Incorrect username or password, or the account is temporarily locked after repeated failures."
          : "Sign-in failed. Check your connection and try again."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <section className="login-visual" aria-label="About Cerberus">
        <div className="login-brand">
          <CerberusMark size={44} />
          <div>
            <div className="login-wordmark">Cerberus</div>
            <div className="login-kicker">Defensive malware analysis</div>
          </div>
        </div>

        <div className="login-headline">
          <h2>Watch what a sample does under controlled conditions.</h2>
          <p>
            Cerberus records normalized behavioral telemetry and turns it into explainable findings, indicators, and
            reports. Results are observations, not a verdict on the file.
          </p>
        </div>

        <InvestigationGraph />

        <ul className="login-capabilities">
          {CAPABILITIES.map((c) => (
            <li key={c.title}>
              <span className="login-cap-title">{c.title}</span>
              <span className="login-cap-text">{c.text}</span>
            </li>
          ))}
        </ul>
      </section>

      <main className="login-form-col" id="main">
        <div className="login-form-brand">
          <CerberusMark size={36} />
          <span className="login-wordmark">Cerberus</span>
        </div>

        <form className="login-card" onSubmit={onSubmit} aria-labelledby="signin-title" noValidate>
          <div className="login-card-head">
            <h1 id="signin-title">Sign in</h1>
            <p>For authorized laboratory use.</p>
          </div>

          {notice && (
            <div style={{ marginBottom: 16 }}>
              <Notice tone={notice === SIGNED_OUT_NOTICE ? "info" : "warn"}>{notice}</Notice>
            </div>
          )}

          <div className="login-fields">
            <TextField
              label="Username"
              name="username"
              autoComplete="username"
              autoFocus
              required
              maxLength={64}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
            <TextField
              label="Password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={128}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          <button
            type="submit"
            className="login-submit"
            disabled={busy || !username || !password}
            aria-busy={busy}
          >
            {busy && <LoaderCircle size={17} className="login-spin" aria-hidden="true" />}
            <span>{busy ? "Signing in…" : "Sign in"}</span>
          </button>

          {error && (
            <div role="alert" style={{ marginTop: 16 }}>
              <Notice tone="err">{error}</Notice>
            </div>
          )}
        </form>
      </main>
    </div>
  );
}
