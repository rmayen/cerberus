import { lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { Layout } from "./components/Layout";
import { LoadingBlock } from "./components/ui/primitives";
import { Login } from "./pages/Login";

// Each page is its own chunk so the sign-in screen does not download investigation code.
const Overview = lazy(() => import("./pages/Overview").then((m) => ({ default: m.Overview })));
const Samples = lazy(() => import("./pages/Samples").then((m) => ({ default: m.Samples })));
const SampleDetail = lazy(() => import("./pages/SampleDetail").then((m) => ({ default: m.SampleDetail })));
const Cases = lazy(() => import("./pages/Cases").then((m) => ({ default: m.Cases })));
const CaseDetail = lazy(() => import("./pages/CaseDetail").then((m) => ({ default: m.CaseDetail })));
const Jobs = lazy(() => import("./pages/Jobs").then((m) => ({ default: m.Jobs })));
const JobDetail = lazy(() => import("./pages/JobDetail").then((m) => ({ default: m.JobDetail })));
const Differential = lazy(() => import("./pages/Differential").then((m) => ({ default: m.Differential })));
const DifferentialDetail = lazy(() => import("./pages/DifferentialDetail").then((m) => ({ default: m.DifferentialDetail })));

export function App() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="login-wrap">
        <div style={{ width: "min(360px, 100%)" }}>
          <LoadingBlock label="Checking your session" rows={2} height={20} />
        </div>
      </div>
    );
  }
  if (!user) return <Login />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Overview />} />
        <Route path="/samples" element={<Samples />} />
        <Route path="/samples/:id" element={<SampleDetail />} />
        <Route path="/cases" element={<Cases />} />
        <Route path="/cases/:id" element={<CaseDetail />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/jobs/:id" element={<JobDetail />} />
        <Route path="/differential" element={<Differential />} />
        <Route path="/differential/:id" element={<DifferentialDetail />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
