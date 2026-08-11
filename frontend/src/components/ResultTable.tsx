/**
 * 查询结果表格组件
 * 将后端返回的结构化数据归一化为可滚动表格
 * 支持嵌入模式（embedded）用于嵌入到 ResultChart 的表格 tab 中
 */
import { Database, FileJson } from "lucide-react";
import { cn } from "../lib/format";

function normalizeRows(data: unknown): Array<Record<string, unknown>> {
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

  return [{ 值: data ?? "" }];
}

function formatCell(value: unknown) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

interface ResultTableProps {
  data: unknown;
  embedded?: boolean;
  className?: string;
}

export function ResultTable({ data, embedded = false, className }: ResultTableProps) {
  const rows = normalizeRows(data);
  const columns = Array.from(
    rows.reduce((keys, row) => {
      Object.keys(row).forEach((key) => keys.add(key));
      return keys;
    }, new Set<string>()),
  );

  if (columns.length === 0) {
    return null;
  }

  const tableScroll = (
    <div className={cn("overflow-auto", embedded ? "max-h-[280px]" : "max-h-[360px]")}>
      <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
        <thead className="sticky top-0 z-10 bg-[#efe6d8]">
          <tr>
            {columns.map((column) => (
              <th
                key={column}
                scope="col"
                className="border-b border-ink/10 px-4 py-3 font-semibold text-ink/70"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="odd:bg-white/45 even:bg-white/20">
              {columns.map((column) => (
                <td key={column} className="border-b border-ink/5 px-4 py-3 text-ink/80">
                  {formatCell(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  if (embedded) {
    return <div className={cn("px-2 py-2", className)}>{tableScroll}</div>;
  }

  return (
    <section className={cn("mt-4 overflow-hidden border border-ink/10 bg-white/70 shadow-line", className)}>
      <div className="flex items-center justify-between border-b border-ink/10 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink">
          <Database className="h-4 w-4 text-moss" aria-hidden="true" />
          查询结果
        </div>
        <div className="flex items-center gap-2 text-xs text-ink/55">
          <FileJson className="h-3.5 w-3.5" aria-hidden="true" />
          {rows.length} 行
        </div>
      </div>
      {tableScroll}
    </section>
  );
}
