/**
 * 图表类型自动检测工具
 * 根据数据的列类型和分布特征，推断最合适的图表类型
 */

export type ChartType = "bar" | "line" | "pie" | "groupedBar" | "table";

export type ColumnRole = "dimension" | "metric" | "unknown";

export interface ColumnAnalysis {
  key: string;
  role: ColumnRole;
  isTimeDimension: boolean;
  numericValues: number[];
  stringValues: string[];
}

export interface DataAnalysis {
  rows: Array<Record<string, unknown>>;
  columns: ColumnAnalysis[];
  dimensions: ColumnAnalysis[];
  metrics: ColumnAnalysis[];
  rowCount: number;
  canChart: boolean;
  recommendedType: ChartType;
}

const TIME_KEYWORDS = /(时间|日期|月份|季度|年|月|日|time|date|month|quarter|year|day)/i;

const DIMENSION_KEYWORDS = /(名称|品类|类别|分类|大区|区域|省份|城市|等级|会员|category|type|region|area|name|label|等级)/i;

function isNumeric(value: unknown): boolean {
  if (value === null || value === undefined || value === "") return false;
  if (typeof value === "number") return true;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed === "") return false;
    return !Number.isNaN(Number(trimmed));
  }
  return false;
}

function isTimeLike(value: unknown): boolean {
  if (value === null || value === undefined || value === "") return false;
  if (typeof value === "number") {
    return value > 1900 && value < 2200;
  }
  if (typeof value === "string") {
    const s = value.trim();
    if (/^\d{4}[-/年]\d{1,2}([-/月]\d{1,2})?/.test(s)) return true;
    if (/^\d{4}$/.test(s)) return true;
    if (/Q[1-4]\s?\d{4}/i.test(s)) return true;
    if (/^\d{1,2}月$/i.test(s)) return true;
  }
  return false;
}

function detectColumnRole(
  key: string,
  values: unknown[],
): { role: ColumnRole; isTimeDimension: boolean } {
  const nonEmpty = values.filter((v) => v !== null && v !== undefined && v !== "");
  if (nonEmpty.length === 0) return { role: "unknown", isTimeDimension: false };

  const numericCount = nonEmpty.filter(isNumeric).length;
  const numericRatio = numericCount / nonEmpty.length;

  const hasTimeKeyword = TIME_KEYWORDS.test(key);
  const hasDimensionKeyword = DIMENSION_KEYWORDS.test(key);

  const timeLikeCount = nonEmpty.filter(isTimeLike).length;
  const timeRatio = timeLikeCount / nonEmpty.length;

  if (numericRatio >= 0.8) {
    return { role: "metric", isTimeDimension: false };
  }

  if (hasTimeKeyword || timeRatio >= 0.7) {
    return { role: "dimension", isTimeDimension: true };
  }

  if (hasDimensionKeyword) {
    return { role: "dimension", isTimeDimension: false };
  }

  if (numericRatio < 0.3) {
    return { role: "dimension", isTimeDimension: false };
  }

  return { role: "unknown", isTimeDimension: false };
}

export function normalizeChartData(data: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(data)) {
    return data.map((item, index) =>
      item && typeof item === "object" && !Array.isArray(item)
        ? (item as Record<string, unknown>)
        : { 序号: index + 1, 值: item },
    );
  }
  if (data && typeof data === "object") {
    return [data as Record<string, unknown>];
  }
  return [];
}

export function analyzeData(data: unknown): DataAnalysis {
  const rows = normalizeChartData(data);

  if (rows.length === 0) {
    return {
      rows: [],
      columns: [],
      dimensions: [],
      metrics: [],
      rowCount: 0,
      canChart: false,
      recommendedType: "table",
    };
  }

  const allKeys = Array.from(
    rows.reduce((keys, row) => {
      Object.keys(row).forEach((key) => keys.add(key));
      return keys;
    }, new Set<string>()),
  );

  const columns: ColumnAnalysis[] = allKeys.map((key) => {
    const values = rows.map((row) => row[key]);
    const { role, isTimeDimension } = detectColumnRole(key, values);

    const numericValues = values
      .filter(isNumeric)
      .map((v) => (typeof v === "number" ? v : Number(v)));

    const stringValues = values
      .filter((v) => v !== null && v !== undefined && v !== "")
      .map((v) => String(v));

    return { key, role, isTimeDimension, numericValues, stringValues };
  });

  const dimensions = columns.filter((c) => c.role === "dimension");
  const metrics = columns.filter((c) => c.role === "metric");

  const canChart = dimensions.length >= 1 && metrics.length >= 1 && rows.length >= 2;

  let recommendedType: ChartType = "table";

  if (canChart) {
    const hasTimeDimension = dimensions.some((d) => d.isTimeDimension);
    const uniqueDimValues = new Set(dimensions[0].stringValues).size;

    if (hasTimeDimension && metrics.length >= 1) {
      recommendedType = "line";
    } else if (dimensions.length === 1 && metrics.length === 1 && uniqueDimValues <= 8) {
      recommendedType = "pie";
    } else if (dimensions.length === 1 && metrics.length >= 2) {
      recommendedType = "groupedBar";
    } else if (dimensions.length >= 1 && metrics.length >= 1) {
      recommendedType = "bar";
    }
  }

  return {
    rows,
    columns,
    dimensions,
    metrics,
    rowCount: rows.length,
    canChart,
    recommendedType,
  };
}

export function getChartColors(count: number): string[] {
  const palette = [
    "#2f6b4f",
    "#b48638",
    "#5a8a6f",
    "#d4a94e",
    "#3d8b63",
    "#8b6914",
    "#1a4a32",
    "#e0c068",
    "#4a7d5e",
    "#c49a3c",
  ];
  return Array.from({ length: count }, (_, i) => palette[i % palette.length]);
}
