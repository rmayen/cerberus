import { lazy, Suspense, type ComponentProps } from "react";

// recharts is large. Charts load on first render, so pages without charts never download it.
const CountBarsChart = lazy(() => import("./Charts").then((m) => ({ default: m.CountBars })));
const StatusDonutChart = lazy(() => import("./Charts").then((m) => ({ default: m.StatusDonut })));

function ChartSkeleton({ height }: { height: number }) {
  return <div className="skeleton" aria-hidden="true" style={{ height, width: "100%" }} />;
}

export function CountBars({ height = 180, ...props }: ComponentProps<typeof CountBarsChart>) {
  return (
    <Suspense fallback={<ChartSkeleton height={height} />}>
      <CountBarsChart height={height} {...props} />
    </Suspense>
  );
}

export function StatusDonut({ height = 180, ...props }: ComponentProps<typeof StatusDonutChart>) {
  return (
    <Suspense fallback={<ChartSkeleton height={height} />}>
      <StatusDonutChart height={height} {...props} />
    </Suspense>
  );
}
