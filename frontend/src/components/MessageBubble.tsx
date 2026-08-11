/**
 * 聊天消息气泡组件
 * 组合展示用户问题、智能体回复、执行流程、自然语言总结和结果表格
 */
import { Bot, Copy, Sparkles, UserRound, Zap } from "lucide-react";
import { ResultChart } from "./ResultChart";
import { StepRail } from "./StepRail";
import { cn, formatTime, toClipboardText } from "../lib/format";
import type { ChatMessage } from "../types/agent";

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const hasSummary = Boolean(message.summary) || message.summaryStreaming;

  const copy = async () => {
    const text = message.result ? toClipboardText(message.result) : message.content;
    await navigator.clipboard.writeText(text);
  };

  return (
    <article className={cn("group flex gap-3", isUser && "justify-end")}>
      {!isUser && (
        <div className="mt-1 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink text-parchment">
          <Bot className="h-4 w-4" aria-hidden="true" />
        </div>
      )}

      <div className={cn("max-w-[920px] flex-1", isUser && "flex max-w-[760px] justify-end")}>
        <div
          className={cn(
            "relative border px-5 py-4 shadow-line",
            isUser
              ? "border-ink/80 bg-ink text-parchment"
              : "border-ink/10 bg-[#fffaf1]/78 text-ink backdrop-blur",
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <p className="whitespace-pre-wrap text-[15px] leading-7">{message.content}</p>
            <div className="flex shrink-0 items-center gap-2">
              {message.cached && (
                <span className="inline-flex items-center gap-1 rounded bg-moss/15 px-2 py-1 text-xs font-semibold text-moss">
                  <Zap className="h-3 w-3" aria-hidden="true" />
                  缓存命中
                </span>
              )}
              {!isUser && message.status !== "streaming" && (
                <button
                  type="button"
                  onClick={copy}
                  className="rounded-full p-1.5 text-ink/45 opacity-0 outline-none transition hover:bg-ink/5 hover:text-ink focus:opacity-100 focus:ring-2 focus:ring-moss/40 group-hover:opacity-100"
                  title="复制"
                  aria-label="复制"
                >
                  <Copy className="h-4 w-4" aria-hidden="true" />
                </button>
              )}
            </div>
          </div>

          {message.error && (
            <div className="mt-3 border border-tomato/30 bg-tomato/10 px-3 py-2 text-sm text-tomato">
              {message.error}
            </div>
          )}

          {!isUser && !message.cached && <StepRail steps={message.steps} />}

          {/* 自然语言总结：放在结果图表/表格上方，流式展示 */}
          {!isUser && hasSummary && (
            <div className="mt-4 rounded-lg border border-moss/25 bg-moss/8 px-4 py-3">
              <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-moss/85">
                <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                智能总结
                {message.summaryStreaming && (
                  <span className="ml-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-moss align-middle" />
                )}
              </div>
              <p className="whitespace-pre-wrap text-[14.5px] leading-7 text-ink/90">
                {message.summary}
                {message.summaryStreaming && (
                  <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-[3px] animate-pulse bg-ink/50 align-middle" />
                )}
              </p>
            </div>
          )}

          {!isUser && message.result !== undefined && <ResultChart data={message.result} />}

          <div
            className={cn(
              "mt-3 text-xs",
              isUser ? "text-parchment/55" : "text-ink/45",
            )}
          >
            {formatTime(message.createdAt)}
          </div>
        </div>
      </div>

      {isUser && (
        <div className="mt-1 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-moss text-white">
          <UserRound className="h-4 w-4" aria-hidden="true" />
        </div>
      )}
    </article>
  );
}
