/**
 * 查询结果图表组件
 * 根据数据特征自动选择图表类型，支持手动切换
 * 使用 Recharts 实现响应式图表渲染
 */
import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  BarChart3,
  LineChart as LineChartIcon,
  PieChart as PieChartIcon,
  Table2,
  LayoutGrid,
} from "lucide-react";
import { analyzeData, getChartColors, type ChartType, type DataAnalysis } from "../lib/chartTypeDetector";
import { cn } from "../lib/format";

interface ResultChartProps {
  data: unknown;
  className?: string;
}

const CHART_TYPES: { value: ChartType; label: string; icon: typeof BarChart3 }[] = [
  { value: "bar", label: "柱状图", icon: BarChart3 },
  { value: "line", label: "折线图", icon: LineChartIcon },
  { value: "pie", label: "饼图", icon: PieChartIcon },
  { value: "groupedBar", label: "分组柱", icon: LayoutGrid },
  { value: "table", label: "表格", icon: Table2 },
];

function ChartTypeSwitcher({
  current,
  recommended,
  onChange,
  disabledTypes,
}: {
  current: ChartType;
  recommended: ChartType;
  onChange: (type: ChartType) => void;
  disabledTypes: Set<ChartType>;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      {CHART_TYPES.map(({ value, label, icon: Icon }) => {
        const disabled = disabledTypes.has(value);
        const isActive = current === value;
        const isRecommended = recommended === value && !isActive;
        return (
          <button
            key={value}
            type="button"
            disabled={disabled}
            onClick={() => onChange(value)}
            className={cn(
              "inline-flex items-center gap-1.5 border px-2.5 py-1 text-xs font-semibold transition",
              isActive
                ? "border-moss/50 bg-moss text-parchment"
                : disabled
                  ? "cursor-not-allowed border-ink/10 bg-white/30 text-ink/30"
                  : "border-ink/10 bg-white/60 text-ink/70 hover:border-moss/35 hover:bg-white",
              isRecommended && !isActive && "ring-1 ring-brass/40",
            )}
            title={disabled ? `此数据不适合${label}` : label}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            {label}
          </button>
        );
      })}
    </div>
  );
}

function BarChartView({ analysis }: { analysis: DataAnalysis }) {
  const { rows, dimensions, metrics } = analysis;
  const colors = getChartColors(metrics.length);
  const dimKey = dimensions[0]?.key ?? "";

  const chartData = rows.map((row) => {
    const item: Record<string, unknown> = { name: String(row[dimKey] ?? "") };
    metrics.forEach((m) => {
      const v = row[m.key];
      item[m.key] = typeof v === "number" ? v : Number(v) || 0;
    });
    return item;
  });

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(32,32,29,0.1)" />
        <XAxis
          dataKey="name"
          tick={{ fontSize: 12, fill: "#20201d" }}
          interval={chartData.length > 12 ? Math.floor(chartData.length / 6) : 0}
        />
        <YAxis tick={{ fontSize: 12, fill: "#20201d" }} />
        <Tooltip
          contentStyle={{
            background: "#fffaf1",
            border: "1px solid rgba(32,32,29,0.1)",
            borderRadius: 4,
            fontSize: 13,
          }}
        />
        {metrics.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {metrics.map((m, i) => (
          <Bar
            key={m.key}
            dataKey={m.key}
            fill={colors[i]}
            radius={[3, 3, 0, 0]}
            maxBarSize={48}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

function LineChartView({ analysis }: { analysis: DataAnalysis }) {
  const { rows, dimensions, metrics } = analysis;
  const colors = getChartColors(metrics.length);
  const dimKey = dimensions[0]?.key ?? "";

  const chartData = rows.map((row) => {
    const item: Record<string, unknown> = { name: String(row[dimKey] ?? "") };
    metrics.forEach((m) => {
      const v = row[m.key];
      item[m.key] = typeof v === "number" ? v : Number(v) || 0;
    });
    return item;
  });

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(32,32,29,0.1)" />
        <XAxis
          dataKey="name"
          tick={{ fontSize: 12, fill: "#20201d" }}
          interval={chartData.length > 12 ? Math.floor(chartData.length / 6) : 0}
        />
        <YAxis tick={{ fontSize: 12, fill: "#20201d" }} />
        <Tooltip
          contentStyle={{
            background: "#fffaf1",
            border: "1px solid rgba(32,32,29,0.1)",
            borderRadius: 4,
            fontSize: 13,
          }}
        />
        {metrics.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {metrics.map((m, i) => (
          <Line
            key={m.key}
            type="monotone"
            dataKey={m.key}
            stroke={colors[i]}
            strokeWidth={2}
            dot={{ r: 3, fill: colors[i] }}
            activeDot={{ r: 5 }}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

function PieChartView({ analysis }: { analysis: DataAnalysis }) {
  const { rows, dimensions, metrics } = analysis;
  const colors = getChartColors(rows.length);
  const dimKey = dimensions[0]?.key ?? "";
  const metricKey = metrics[0]?.key ?? "";

  const chartData = rows.map((row) => ({
    name: String(row[dimKey] ?? ""),
    value: typeof row[metricKey] === "number" ? row[metricKey] : Number(row[metricKey]) || 0,
  }));

  return (
    <ResponsiveContainer width="100%" height={280}>
      <PieChart>
        <Pie
          data={chartData}
          dataKey="value"
          nameKey="name"
          cx="50%"
          cy="50%"
          outerRadius={90}
          innerRadius={45}
          paddingAngle={2}
          label={({ name, percent }) =>
            `${name} ${((percent ?? 0) * 100).toFixed(0)}%`
          }
          labelLine={{ stroke: "rgba(32,32,29,0.3)" }}
        >
          {chartData.map((_, index) => (
            <Cell key={`cell-${index}`} fill={colors[index % colors.length]} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            background: "#fffaf1",
            border: "1px solid rgba(32,32,29,0.1)",
            borderRadius: 4,
            fontSize: 13,
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}

function GroupedBarChartView({ analysis }: { analysis: DataAnalysis }) {
  const { rows, dimensions, metrics } = analysis;
  const colors = getChartColors(metrics.length);
  const dimKey = dimensions[0]?.key ?? "";

  const chartData = rows.map((row) => {
    const item: Record<string, unknown> = { name: String(row[dimKey] ?? "") };
    metrics.forEach((m) => {
      const v = row[m.key];
      item[m.key] = typeof v === "number" ? v : Number(v) || 0;
    });
    return item;
  });

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(32,32,29,0.1)" />
        <XAxis
          dataKey="name"
          tick={{ fontSize: 12, fill: "#20201d" }}
          interval={chartData.length > 12 ? Math.floor(chartData.length / 6) : 0}
        />
        <YAxis tick={{ fontSize: 12, fill: "#20201d" }} />
        <Tooltip
          contentStyle={{
            background: "#fffaf1",
            border: "1px solid rgba(32,32,29,0.1)",
            borderRadius: 4,
            fontSize: 13,
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {metrics.map((m, i) => (
          <Bar
            key={m.key}
            dataKey={m.key}
            fill={colors[i]}
            radius={[3, 3, 0, 0]}
            maxBarSize={32}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ResultChart({ data, className }: ResultChartProps) {
  const analysis = useMemo(() => analyzeData(data), [data]);
  const [chartType, setChartType] = useState<ChartType>(analysis.recommendedType);

  useEffect(() => {
    setChartType(analysis.recommendedType);
  }, [analysis.recommendedType]);

  const disabledTypes = useMemo(() => {
    const disabled = new Set<ChartType>();
    if (!analysis.canChart) {
      disabled.add("bar");
      disabled.add("line");
      disabled.add("pie");
      disabled.add("groupedBar");
    } else {
      if (analysis.metrics.length < 2) disabled.add("groupedBar");
      if (analysis.dimensions.length < 1 || analysis.metrics.length < 1) {
        disabled.add("bar");
        disabled.add("line");
        disabled.add("pie");
      }
      if (analysis.metrics.length !== 1) disabled.add("pie");
    }
    return disabled;
  }, [analysis]);

  const effectiveType = disabledTypes.has(chartType) ? analysis.recommendedType : chartType;

  if (analysis.rowCount === 0) {
    return null;
  }

  return (
    <section className={cn("mt-4 overflow-hidden border border-ink/10 bg-white/70 shadow-line", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink/10 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink">
          <BarChart3 className="h-4 w-4 text-moss" aria-hidden="true" />
          数据可视化
        </div>
        <ChartTypeSwitcher
          current={effectiveType}
          recommended={analysis.recommendedType}
          onChange={setChartType}
          disabledTypes={disabledTypes}
        />
      </div>

      <div className="px-2 py-3">
        {effectiveType === "bar" && <BarChartView analysis={analysis} />}
        {effectiveType === "line" && <LineChartView analysis={analysis} />}
        {effectiveType === "pie" && <PieChartView analysis={analysis} />}
        {effectiveType === "groupedBar" && <GroupedBarChartView analysis={analysis} />}
        {effectiveType === "table" && (
          <div className="flex h-[280px] items-center justify-center text-sm text-ink/45">
            请在下方查看详细表格数据
          </div>
        )}
      </div>
    </section>
  );
}
