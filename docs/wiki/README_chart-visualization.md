# 查询结果图表可视化

> 对应源码：[frontend/src/components/ResultChart.tsx](file:///f:/code/ai/shop-query/frontend/src/components/ResultChart.tsx) | [frontend/src/lib/chartTypeDetector.ts](file:///f:/code/ai/shop-query/frontend/src/lib/chartTypeDetector.ts) | [frontend/src/components/ResultTable.tsx](file:///f:/code/ai/shop-query/frontend/src/components/ResultTable.tsx)

## 1. 概述

在查询结果表格之上，增加**基于数据特征的自动图表渲染**能力。用户不需要手动选择图表类型——系统根据列的语义关键词和数值分布，自动识别维度 / 指标 / 时间维度，推荐最合适的图表（柱状/折线/饼图/分组柱），同时允许手动切换。数据不适合图表时自动降级为表格。

## 2. 技术选型

**Recharts**（而非 ECharts）：
- React 原生 API，组件化写法与项目一致
- 包体积更小（~300KB vs ECharts ~1MB），首屏加载更快
- 与 Tailwind CSS 的样式融合更自然，自定义颜色和圆角无需处理主题

依赖：`pnpm add recharts`（已在 package.json 中）

## 3. 图表类型自动检测

> 源码：[chartTypeDetector.ts](file:///f:/code/ai/shop-query/frontend/src/lib/chartTypeDetector.ts)

### 3.1 列角色识别

对每一列，综合三个信号判断是「维度」「指标」还是「未知」：

| 信号 | 判定规则 |
|------|----------|
| 数值比例 | ≥80% 非空值能解析为数字 → `metric` |
| 语义关键词 | 列名命中 `/(时间\|日期\|月份\|季度\|年\|月\|日\|time\|date\|...)/i` → 时间维度；命中 `/(名称\|品类\|类别\|大区\|区域\|省份\|城市\|...)/i` → 普通维度 |
| 时间格式比例 | ≥70% 非空值匹配 `YYYY-MM-DD` / `YYYY年MM月` / `Q1 2025` / `YYYY` 等 → 时间维度 |
| 数值比例兜底 | <30% → `dimension` |

### 3.2 图表推荐逻辑

```
canChart = (维度数 ≥ 1) AND (指标数 ≥ 1) AND (行数 ≥ 2)

if canChart:
    有时间维度 + 有指标                    → 折线图 (line)
    单维度单指标 + 维度取值 ≤ 8 个         → 饼图 (pie)
    单维度 + 指标 ≥ 2 个                  → 分组柱状图 (groupedBar)
    其他情况（维度多 / 取值多等）           → 柱状图 (bar)
else:
    → 表格 (table)
```

### 3.3 DataAnalysis 输出结构

```typescript
interface DataAnalysis {
  rows: Array<Record<string, unknown>>;   // 规范化后的行数据
  columns: ColumnAnalysis[];              // 全列分析详情
  dimensions: ColumnAnalysis[];           // 维度子集
  metrics: ColumnAnalysis[];              // 指标子集
  rowCount: number;
  canChart: boolean;
  recommendedType: ChartType;             // bar / line / pie / groupedBar / table
}
```

## 4. 组件结构

```
ResultChart（外层容器）
├── 头部：图表类型切换按钮（推荐类型有金色高亮边框提示）
│     · 柱状图 / 折线图 / 饼图 / 分组柱 / 表格
│     · 不适合的数据类型按钮自动 disabled（hover 有说明）
│
└── 内容区：根据 effectiveType 渲染
      ├── BarChartView       → 柱状图（多指标并列）
      ├── LineChartView      → 折线图（monotone 平滑）
      ├── PieChartView       → 环形饼图（innerRadius=45，带百分比标签）
      ├── GroupedBarChartView→ 分组对比柱状图
      └── ResultTable(embedded) → 表格模式（无边框，自适应高度）
```

### 4.1 推荐类型提示

推荐的图表按钮会有一圈 `ring-1 ring-brass/40` 金色高亮边框，引导用户优先尝试系统判断。

### 4.2 样式规范（与现有 Tailwind 主题一致）

```
主色调：   #2f6b4f  moss（墨绿）
辅色：     #b48638  brass（黄铜）
背景：     #fffaf1  parchment（羊皮纸）
网格线：   rgba(32,32,29,0.1)  半透明墨灰
字体：     12px tick，13px tooltip
```

配色板 `getChartColors(n)` 使用 10 种墨绿 + 黄铜交替色，避免默认红蓝配色与主题冲突。

## 5. 表格集成到 Tab

表格不再在 MessageBubble 中独立渲染，而是作为 ResultChart 的一个 Tab（表格 Tab）。切换逻辑：

- 空数据 / 无法图表化 → 默认选中表格 Tab，隐藏图表按钮
- 有数据且可图表 → 默认选中推荐的图表类型，用户可自由切换到表格

```typescript
// ResultChart.tsx
{effectiveType === "table" && (
  <ResultTable data={data} embedded />
)}
```

`ResultTable` 的 `embedded` 属性：
- 去掉外层边框和圆角（因为外层 ResultChart 已有）
- 去掉固定高度，让表格高度自适应内容
- 表格内部滚动区域缩小内边距

## 6. 优雅降级

| 场景 | 行为 |
|------|------|
| `data` 为空 / 非数组 / 0 行 | `return null`，整个 ResultChart 不渲染 |
| 维度 <1 或指标 <1 | 所有图表按钮 disabled，强制表格视图 |
| 饼图需要 1 指标，但有多个指标 | 饼图按钮 disabled，推荐柱状/分组柱 |
| 分组柱需要 ≥2 指标，只有 1 指标 | 分组柱按钮 disabled |
| 行数很多（>12） | X 轴 tick 自动间隔显示，避免文字重叠 |
