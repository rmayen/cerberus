import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { TONE_HEX, type Tone } from "../lib/status";

export interface ChartItem {
  key: string;
  label: string;
  value: number;
  tone: Tone;
}

/**
 * Horizontal bar chart of real counts. The chart is decorative for sighted users;
 * the legend beside it repeats every value as text so color is never the only channel.
 */
export function CountBars({ items, height = 180, emptyLabel = "No data yet" }: { items: ChartItem[]; height?: number; emptyLabel?: string }) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  if (total === 0) {
    return <p className="muted text-sm">{emptyLabel}</p>;
  }
  return (
    <div>
      <div aria-hidden="true" style={{ width: "100%", height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart accessibilityLayer={false} data={items} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
            <XAxis type="number" hide allowDecimals={false} />
            <YAxis
              type="category"
              dataKey="label"
              width={92}
              tickLine={false}
              axisLine={false}
              tick={{ fill: "#c3c8d4", fontSize: 12 }}
            />
            <Tooltip
              cursor={{ fill: "rgba(141,180,255,0.06)" }}
              contentStyle={{ background: "#181b22", border: "1px solid #363d4d", borderRadius: 8, color: "#e9ebf1", fontSize: 12 }}
              formatter={(value) => [String(value), "count"]}
            />
            <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={14} isAnimationActive={false}>
              {items.map((item) => (
                <Cell key={item.key} fill={TONE_HEX[item.tone]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="chart-legend" aria-label="Chart values">
        {items.map((item) => (
          <li key={item.key}>
            <span className="swatch" style={{ background: TONE_HEX[item.tone] }} aria-hidden="true" />
            <span>{item.label}</span>
            <span className="count">{item.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Donut of real counts with the total in the center. Zero-value segments are dropped so a
 * single non-zero state reads as a full ring. The text legend carries every value.
 */
export function StatusDonut({
  items,
  height = 180,
  emptyLabel = "No data yet",
  centerLabel,
}: {
  items: ChartItem[];
  height?: number;
  emptyLabel?: string;
  centerLabel?: string;
}) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  if (total === 0) {
    return <p className="muted text-sm">{emptyLabel}</p>;
  }
  const plotted = items.filter((item) => item.value > 0);
  return (
    <div className="donut-wrap">
      <div className="donut-chart" aria-hidden="true" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart accessibilityLayer={false}>
            <Pie
              rootTabIndex={-1}
              data={plotted}
              dataKey="value"
              nameKey="label"
              innerRadius="62%"
              outerRadius="92%"
              stroke="none"
              isAnimationActive={false}
            >
              {plotted.map((item) => (
                <Cell key={item.key} fill={TONE_HEX[item.tone]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{ background: "#181b22", border: "1px solid #363d4d", borderRadius: 8, color: "#e9ebf1", fontSize: 12 }}
              formatter={(value) => [String(value), "count"]}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="donut-center">
          <strong>{total}</strong>
          {centerLabel && <span>{centerLabel}</span>}
        </div>
      </div>
      <ul className="chart-legend" aria-label="Chart values">
        {items.map((item) => (
          <li key={item.key}>
            <span className="swatch" style={{ background: TONE_HEX[item.tone] }} aria-hidden="true" />
            <span>{item.label}</span>
            <span className="count">{item.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
