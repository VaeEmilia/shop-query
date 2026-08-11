/**
 * 前端应用主组件
 * 负责聊天会话状态、SSE 事件消费和整体页面布局
 * 新增：缓存统计面板、缓存命中标识
 */
import {
  Activity,
  BarChart3,
  Eraser,
  History,
  Leaf,
  Lightbulb,
  MessageSquarePlus,
  Server,
  Zap,
  RotateCcw,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { Composer } from "./components/Composer";
import { EmptyState } from "./components/EmptyState";
import { MessageBubble } from "./components/MessageBubble";
import { SessionList } from "./components/SessionList";
import { streamQuery } from "./lib/agentApi";
import {
  createSession,
  deleteSession,
  getSessionMessages,
  listSessions,
  renameSession,
} from "./lib/sessionApi";
import {
  deleteMessages,
  getCurrentSessionId,
  loadMessages,
  loadSessions,
  saveCurrentSessionId,
  saveMessages,
  saveSessions,
  sortSessions,
} from "./lib/sessionStorage";
import { cn, summarizeResult } from "./lib/format";
import type { AgentEvent, ChatMessage, StepState } from "./types/agent";
import type { Session } from "./types/session";

const examples = [
  "统计 2025 年第一季度各大区的 GMV，并按 GMV 从高到低排序",
  "统计 2025 年 3 月各商品品类的销量和销售额",
  "查询华东地区 2025 年第一季度销售额最高的前 5 个商品",
  "按会员等级统计 2025 年第一季度的订单数和销售额",
];

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

function makeId() {
  return crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function upsertStep(steps: StepState[] = [], event: Extract<AgentEvent, { type: "progress" }>) {
  const next = steps.filter((item) => item.step !== event.step);
  next.push({
    step: event.step,
    status: event.status,
    updatedAt: Date.now(),
  });
  return next;
}

type CacheStats = {
  hit: number;
  miss: number;
  total: number;
  hit_rate: number;
  cache_count: number;
};

export default function App() {
  // 会话列表与当前会话 ID 优先从 localStorage 恢复，保证刷新后不丢失
  const [sessions, setSessions] = useState<Session[]>(() => loadSessions());
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(() => getCurrentSessionId());
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    const id = getCurrentSessionId();
    return id ? loadMessages(id) : [];
  });
  const [draft, setDraft] = useState("");
  const [activeController, setActiveController] = useState<AbortController | null>(null);
  const [cacheStats, setCacheStats] = useState<CacheStats | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const isStreaming = Boolean(activeController);
  const canSubmit = draft.trim().length > 0 && !isStreaming;

  const completedCount = useMemo(
    () => messages.filter((message) => message.role === "assistant" && message.status === "done").length,
    [messages],
  );

  // 轮询缓存统计
  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/cache/stats`);
        if (res.ok) {
          const json = await res.json();
          if (json.data) setCacheStats(json.data);
        }
      } catch {
        // 静默失败，不干扰主流程
      }
    };
    fetchStats();
    const timer = setInterval(fetchStats, 5000);
    return () => clearInterval(timer);
  }, [messages]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  // 消息变化时持久化到当前会话的 localStorage，刷新或切回时不丢失
  useEffect(() => {
    if (currentSessionId) {
      saveMessages(currentSessionId, messages);
    }
  }, [messages, currentSessionId]);

  // 启动时从后端拉取权威会话列表，与 localStorage 合并
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const remote = sortSessions(await listSessions());
        if (cancelled) return;
        setSessions(remote);
        saveSessions(remote);
        // 当前会话已过期（后端 TTL 清理）时清空指向
        if (currentSessionId && !remote.some((s) => s.id === currentSessionId)) {
          setCurrentSessionId(null);
          saveCurrentSessionId(null);
          setMessages([]);
        }
      } catch {
        // 后端不可用时保留 localStorage 中的会话
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const resetCacheStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/cache/stats/reset`, { method: "POST" });
      if (res.ok) {
        const json = await res.json();
        if (json.data) setCacheStats(json.data);
      }
    } catch {
      // 静默失败
    }
  }, []);

  const startQuery = async (rawQuery = draft) => {
    const query = rawQuery.trim();
    if (!query || isStreaming) return;

    // 无活跃会话时自动创建，会话名取首条问题前 30 字，避免产生空会话
    let sessionId = currentSessionId;
    if (!sessionId) {
      try {
        const session = await createSession(query.slice(0, 30));
        sessionId = session.id;
        setSessions((prev) => {
          const next = sortSessions([session, ...prev]);
          saveSessions(next);
          return next;
        });
        setCurrentSessionId(sessionId);
        saveCurrentSessionId(sessionId);
      } catch {
        // 会话创建失败时降级为单轮查询（不携带 session_id）
      }
    }

    const userMessage: ChatMessage = {
      id: makeId(),
      role: "user",
      content: query,
      createdAt: Date.now(),
    };

    const assistantId = makeId();
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "正在连接问数智能体...",
      createdAt: Date.now(),
      status: "streaming",
      steps: [],
    };

    const controller = new AbortController();
    setActiveController(controller);
    setDraft("");
    setMessages((current) => [...current, userMessage, assistantMessage]);

    // 在闭包外捕获总结文本，用于查询结束后更新会话列表的 last_summary
    let capturedSummary = "";

    const onEvent = (event: AgentEvent) => {
      // 同步捕获总结完成文本（不依赖 setMessages 的异步回调）
      if (event.type === "summary" && event.status === "done") {
        capturedSummary = event.text;
      }

      setMessages((current) =>
        current.map((message) => {
          if (message.id !== assistantId) return message;

          if (event.type === "progress") {
            const isCacheHit = event.step === "cache_hit";
            const content =
              event.status === "running"
                ? isCacheHit
                  ? "命中相似问题缓存，直接返回结果..."
                  : `正在执行：${event.step}`
                : message.content;

            return {
              ...message,
              content,
              steps: upsertStep(message.steps, event),
              cached: isCacheHit ? true : message.cached,
            };
          }

          if (event.type === "result") {
            return {
              ...message,
              status: message.status,
              content: summarizeResult(event.data),
              result: event.data,
            };
          }

          if (event.type === "summary") {
            if (event.status === "start") {
              return { ...message, summary: "", summaryStreaming: true };
            }
            if (event.status === "streaming") {
              return {
                ...message,
                summary: (message.summary ?? "") + event.chunk,
                summaryStreaming: true,
              };
            }
            if (event.status === "done") {
              return {
                ...message,
                summary: event.text,
                summaryStreaming: false,
                status: "done",
              };
            }
            return {
              ...message,
              summaryStreaming: false,
              status: message.result !== undefined ? "done" : message.status,
            };
          }

          return {
            ...message,
            status: "error",
            content: "这次查询没有成功。",
            error: event.message,
          };
        }),
      );
    };

    try {
      await streamQuery(query, { signal: controller.signal, onEvent, sessionId });
      setMessages((current) =>
        current.map((message) => {
          if (message.id !== assistantId) return message;
          if (message.status !== "streaming") return message;
          if (message.result !== undefined) {
            return { ...message, status: "done", summaryStreaming: false };
          }
          return {
            ...message,
            status: "done",
            content: "流程已结束，后端未返回查询结果。",
          };
        }),
      );
    } catch (error) {
      const isAbort = error instanceof DOMException && error.name === "AbortError";
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                status: isAbort ? "done" : "error",
                content: isAbort ? "已停止本次查询。" : "无法连接问数接口。",
                error: isAbort ? undefined : error instanceof Error ? error.message : String(error),
              }
            : message,
        ),
      );
    } finally {
      setActiveController(null);

      // 查询结束后更新会话列表的摘要和时间，并按更新时间排序
      if (sessionId) {
        const summary = capturedSummary || query.slice(0, 40);
        setSessions((prev) => {
          const updated = prev.map((s) =>
            s.id === sessionId
              ? { ...s, last_summary: summary, updated_at: new Date().toISOString() }
              : s,
          );
          const sorted = sortSessions(updated);
          saveSessions(sorted);
          return sorted;
        });
      }
    }
  };

  const stopQuery = () => {
    activeController?.abort();
  };

  // 新会话：重置当前上下文，不立即创建后端会话（首条查询时按需创建）
  const handleNewSession = () => {
    if (isStreaming) return;
    setCurrentSessionId(null);
    saveCurrentSessionId(null);
    setMessages([]);
    setDraft("");
  };

  // 切换会话：优先从后端拉取完整历史（含 result），localStorage 作快速降级
  const handleSelectSession = async (sessionId: string) => {
    if (isStreaming) return;
    setCurrentSessionId(sessionId);
    saveCurrentSessionId(sessionId);
    // 先显示 localStorage 缓存的旧数据，用户无感知
    const cached = loadMessages(sessionId);
    setMessages(cached);
    // 异步从后端拉取权威数据（包含完整 result）
    try {
      const remote = await getSessionMessages(sessionId);
      if (remote.length > 0) {
        setMessages(remote);
        saveMessages(sessionId, remote);
      }
    } catch {
      // 后端不可用时保留 localStorage 缓存的旧数据
    }
  };

  // 重命名会话：调用后端 PATCH 接口并同步本地列表，保持排序
  const handleRenameSession = async (sessionId: string, name: string) => {
    try {
      const updated = await renameSession(sessionId, name);
      setSessions((prev) => {
        const next = prev.map((s) => (s.id === sessionId ? updated : s));
        const sorted = sortSessions(next);
        saveSessions(sorted);
        return sorted;
      });
    } catch {
      // 重命名失败时静默保留原名
    }
  };

  // 删除会话：清理后端记录和本地缓存，若删的是当前会话则回到空白态
  const handleDeleteSession = async (sessionId: string) => {
    try {
      await deleteSession(sessionId);
    } catch {
      // 后端删除失败也清理本地，保证 UI 一致
    }
    deleteMessages(sessionId);
    setSessions((prev) => {
      const next = sortSessions(prev.filter((s) => s.id !== sessionId));
      saveSessions(next);
      return next;
    });
    if (currentSessionId === sessionId) {
      setCurrentSessionId(null);
      saveCurrentSessionId(null);
      setMessages([]);
    }
  };

  // 清空当前会话的消息显示（保留会话本身）
  const clearConversation = () => {
    if (isStreaming) return;
    setMessages([]);
    setDraft("");
  };

  return (
    <div className="h-dvh overflow-hidden bg-parchment text-ink">
      <div className="pointer-events-none fixed inset-0 bg-[linear-gradient(90deg,rgba(32,32,29,0.045)_1px,transparent_1px),linear-gradient(rgba(32,32,29,0.035)_1px,transparent_1px)] bg-[size:48px_48px]" />
      <div className="pointer-events-none fixed inset-0 grain" />

      <div className="relative grid h-full min-h-0 overflow-hidden lg:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="hidden min-h-0 border-r border-ink/10 bg-[#efe6d8]/85 backdrop-blur lg:flex lg:flex-col">
          <div className="border-b border-ink/10 px-5 py-5">
            <div className="flex items-center gap-3">
              <div className="grid h-10 w-10 place-items-center bg-ink text-parchment">
                <BarChart3 className="h-5 w-5" aria-hidden="true" />
              </div>
              <div>
                <div className="text-base font-semibold tracking-[0.02em]">电商问数</div>
                <div className="text-xs text-ink/50">shopkeeper-agent</div>
              </div>
            </div>
          </div>

          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
            <button
              type="button"
              onClick={handleNewSession}
              disabled={isStreaming}
              className="flex h-11 w-full items-center justify-center gap-2 bg-ink text-sm font-semibold text-parchment transition hover:bg-soot disabled:cursor-not-allowed disabled:bg-ink/35"
            >
              <MessageSquarePlus className="h-4 w-4" aria-hidden="true" />
              新会话
            </button>

            <section>
              <div className="mb-2 flex items-center gap-2 px-1 text-xs font-semibold uppercase tracking-[0.16em] text-ink/45">
                <History className="h-3.5 w-3.5" aria-hidden="true" />
                会话
              </div>
              <SessionList
                sessions={sessions}
                currentSessionId={currentSessionId}
                disabled={isStreaming}
                onSelect={handleSelectSession}
                onRename={handleRenameSession}
                onDelete={handleDeleteSession}
              />
            </section>

            <section>
              <div className="mb-2 flex items-center gap-2 px-1 text-xs font-semibold uppercase tracking-[0.16em] text-ink/45">
                <Lightbulb className="h-3.5 w-3.5" aria-hidden="true" />
                样例
              </div>
              <div className="space-y-2">
                {examples.map((example) => (
                  <button
                    key={example}
                    type="button"
                    disabled={isStreaming}
                    onClick={() => startQuery(example)}
                    className="w-full border border-ink/10 bg-white/42 px-3 py-3 text-left text-sm leading-5 text-ink/75 transition hover:border-moss/35 hover:bg-white/75 disabled:cursor-not-allowed disabled:opacity-55"
                  >
                    {example}
                  </button>
                ))}
              </div>
            </section>

            {/* 缓存统计面板 */}
            {cacheStats && (
              <section className="border border-ink/10 bg-white/55 px-3 py-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-ink/45">
                    <Zap className="h-3.5 w-3.5" aria-hidden="true" />
                    SQL 缓存
                  </div>
                  <button
                    type="button"
                    onClick={resetCacheStats}
                    className="rounded p-1 text-ink/35 transition hover:bg-ink/5 hover:text-ink"
                    title="重置统计"
                  >
                    <RotateCcw className="h-3 w-3" aria-hidden="true" />
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded bg-white/70 px-2 py-1.5">
                    <div className="text-ink/45">命中率</div>
                    <div className="text-lg font-semibold text-moss">
                      {(cacheStats.hit_rate * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div className="rounded bg-white/70 px-2 py-1.5">
                    <div className="text-ink/45">缓存条数</div>
                    <div className="text-lg font-semibold text-ink">{cacheStats.cache_count}</div>
                  </div>
                  <div className="rounded bg-white/70 px-2 py-1.5">
                    <div className="text-ink/45">命中</div>
                    <div className="font-semibold text-moss">{cacheStats.hit}</div>
                  </div>
                  <div className="rounded bg-white/70 px-2 py-1.5">
                    <div className="text-ink/45">未命中</div>
                    <div className="font-semibold text-ink/75">{cacheStats.miss}</div>
                  </div>
                </div>
              </section>
            )}
          </div>

          <div className="border-t border-ink/10 p-4">
            <div className="grid gap-2 text-xs text-ink/55">
              <div className="flex items-center justify-between gap-3">
                <span className="inline-flex items-center gap-2">
                  <Server className="h-3.5 w-3.5" aria-hidden="true" />
                  API
                </span>
                <span className="truncate font-mono">{API_BASE_URL}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-2">
                  <Activity className="h-3.5 w-3.5" aria-hidden="true" />
                  完成
                </span>
                <span>{completedCount}</span>
              </div>
            </div>
          </div>
        </aside>

        <main className="flex min-h-0 min-w-0 flex-col overflow-hidden">
          <header className="flex h-16 shrink-0 items-center justify-between border-b border-ink/10 bg-parchment/88 px-4 backdrop-blur lg:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <div className="grid h-9 w-9 shrink-0 place-items-center bg-moss text-white lg:hidden">
                <BarChart3 className="h-4 w-4" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-ink">智能数据分析 Agent</div>
                <div className="truncate text-xs text-ink/45">FastAPI SSE / LangGraph</div>
              </div>
            </div>
            <button
              type="button"
              onClick={clearConversation}
              disabled={messages.length === 0 || isStreaming}
              className={cn(
                "grid h-9 w-9 place-items-center rounded-full text-ink/55 transition hover:bg-ink/5 hover:text-ink disabled:cursor-not-allowed disabled:opacity-35",
              )}
              title="清空"
              aria-label="清空"
            >
              <Eraser className="h-4 w-4" aria-hidden="true" />
            </button>
          </header>

          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
            {messages.length === 0 ? (
              <EmptyState examples={examples} onUseExample={(example) => setDraft(example)} />
            ) : (
              <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6 lg:px-8">
                {messages.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}
              </div>
            )}
          </div>

          <div className="border-t border-ink/10 bg-[#efe6d8]/45 px-4 py-2 text-center text-xs text-ink/45">
            <span className="inline-flex items-center gap-2">
              <Leaf className="h-3.5 w-3.5 text-moss" aria-hidden="true" />
              {isStreaming ? "运行中" : "就绪"}
            </span>
          </div>
          <Composer
            value={draft}
            disabled={!canSubmit}
            isStreaming={isStreaming}
            onChange={setDraft}
            onSubmit={() => startQuery()}
            onStop={stopQuery}
          />
        </main>
      </div>
    </div>
  );
}
