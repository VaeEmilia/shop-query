# 查询结果自然语言总结

> 对应源码：[app/agent/nodes/summarize_result.py](file:///f:/code/ai/shop-query/app/agent/nodes/summarize_result.py) | [prompts/summarize_result.prompt](file:///f:/code/ai/shop-query/prompts/summarize_result.prompt) | [frontend/src/types/agent.ts](file:///f:/code/ai/shop-query/frontend/src/types/agent.ts) | [frontend/src/components/MessageBubble.tsx](file:///f:/code/ai/shop-query/frontend/src/components/MessageBubble.tsx)

## 1. 概述

在 SQL 执行完成、拿到结果表格后，调用 LLM 把「用户问题 + 生成的 SQL + 结果数据」总结成 1~3 句中文自然语言，**流式逐 token** 推给前端，展示在结果表格上方。让业务同学一眼看懂结论，不需要自己看表读数。

## 2. 在 LangGraph 工作流中的位置

```
run_sql → summarize_result → END
```

`summarize_result` 节点放在 `run_sql` 之后、END 之前，拿到 `state["sql_result"]` 后调用 LLM 生成总结。

## 3. SSE 消息协议（新增 `summary` 类型）

前端已有的 `progress` / `result` / `error` 类型保持不变，新增一种事件类型：

| status | 含义 | 携带字段 |
|--------|------|----------|
| `start` | 总结开始，准备展示区 | - |
| `streaming` | 流式 chunk，前端追加显示 | `chunk: string` |
| `done` | 总结完成，前端落盘完整文本 | `text: string` |
| `error` | 总结失败，前端隐藏总结区 | `message: string` |

**示例事件流**：
```
data: {"type":"summary","status":"start"}
data: {"type":"summary","status":"streaming","chunk":"2025"}
data: {"type":"summary","status":"streaming","chunk":"年第一季度"}
...
data: {"type":"summary","status":"done","text":"2025年第一季度华北大区GMV最高，达1234万元..."}
```

## 4. Prompt 设计原则

> 源码：[prompts/summarize_result.prompt](file:///f:/code/ai/shop-query/prompts/summarize_result.prompt)

Prompt 中明确写入三条硬约束：

1. **≤ 3 句**：输出必须简短，业务结论在第 1 句
2. **不编造数字**：所有数字必须来自 `result` 字段，禁止估算/四舍五入推断
3. **不确定就不说**：数据缺失的维度不要猜测

```
# 输入
- 用户问题：{query}
- 生成的 SQL：{sql}
- 查询结果：{result}

# 要求
1. 用中文回答，最多 3 句话
2. 第一句直接回答用户问题，给出核心结论
3. 所有数字必须严格来自查询结果，禁止估算或编造
4. 数据为空或无法理解时，直接说"暂无数据"
```

## 5. 降级策略（非阻塞）

总结功能是**锦上添花**，任何情况失败都不能影响主查询流程：

| 失败场景 | 处理方式 |
|----------|----------|
| 配置开关关闭（`summary.enable=false`） | 节点直接 `return`，0 开销 |
| `sql_result` 为 `None` 或空数组 | 跳过总结，不发任何事件 |
| LLM 调用超时 / 抛异常 | 发送 `summary.error` 事件，前端隐藏总结区，**不 raise**，图正常走到 END |
| LLM 返回空串 | `done` 事件的 `text` 为空，前端不显示 |

后端代码的核心结构：
```python
try:
    async for chunk in chain.astream(input_data):
        ...  # 正常流式推送
except Exception as e:
    logger.warning(f"总结失败（降级跳过）: {e}")
    writer({"type": "summary", "status": "error", ...})
    # 注意：不 raise！
```

## 6. 前端展示

MessageBubble 中，总结区放在结果表格**上方**、结果图表**上方**：

```
┌─ MessageBubble (assistant) ──────────────────┐
│  步骤进度条 StepRail                           │
│                                                │
│  ┌─ 总结区（如果有）────────────────────────┐ │
│  │  ✨ 2025年第一季度华北大区GMV最高...      │ │  ← 流式打字机效果
│  └───────────────────────────────────────────┘ │
│                                                │
│  ┌─ ResultChart ─────────────────────────────┐ │
│  │  [柱状图|折线图|饼图|表格]  Tab 切换        │ │
│  │  ... 图表 / 表格内容 ...                    │ │
│  └───────────────────────────────────────────┘ │
└────────────────────────────────────────────────┘
```

### 6.1 打字机效果

前端在 `start` 事件时 `summary=""` + `summaryStreaming=true`，每次 `streaming` 事件追加 `chunk`，`done` 事件用完整 `text` 覆盖并把状态切到 `done`。

```typescript
// App.tsx onEvent handler
if (event.type === "summary") {
  if (event.status === "start")     return { ...message, summary: "", summaryStreaming: true };
  if (event.status === "streaming") return { ...message, summary: (summary ?? "") + event.chunk, summaryStreaming: true };
  if (event.status === "done")      return { ...message, summary: event.text, summaryStreaming: false, status: "done" };
}
```

## 7. 配置开关

在 `conf/app_config.yaml` 中控制是否启用，默认关闭以节省 token：

```yaml
summary:
    enable: false  # 改为 true 开启总结
```

对应 Python 配置：
```python
@dataclass
class SummaryConfig:
    enable: bool = False
```

## 8. 多轮会话集成

每轮结束后，QueryService 会把 `summary_text`（如果有）写入 `session_turn.result_summary` 字段：
- 后端：会话列表接口用该字段展示会话最后摘要
- 前端：切换会话时 localStorage 恢复摘要；后端拉取时用权威摘要覆盖
