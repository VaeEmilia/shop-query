/**
 * 智能体类型定义
 * 定义问数智能体前端使用的 SSE 事件、流程步骤和聊天消息类型
 */
export type ProgressStatus = "running" | "success" | "error";

export type ProgressEvent = {
  type: "progress";
  step: string;
  status: ProgressStatus;
};

export type ResultEvent = {
  type: "result";
  data: unknown;
  sql?: string;
};

export type ErrorEvent = {
  type: "error";
  message: string;
};

/**
 * 自然语言总结 SSE 事件
 */
export type SummaryEvent =
  | { type: "summary"; status: "start" }
  | { type: "summary"; status: "streaming"; chunk: string }
  | { type: "summary"; status: "done"; text: string }
  | { type: "summary"; status: "error"; message?: string };

export type AgentEvent = ProgressEvent | ResultEvent | ErrorEvent | SummaryEvent;

export type StepState = {
  step: string;
  status: ProgressStatus;
  updatedAt: number;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  status?: "streaming" | "done" | "error";
  steps?: StepState[];
  result?: unknown;
  error?: string;
  cached?: boolean;
  summary?: string;
  summaryStreaming?: boolean;
};
