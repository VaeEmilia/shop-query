/**
 * 会话本地存储工具
 * 使用 localStorage 缓存当前会话 ID 和会话列表元数据，
 * 确保页面刷新后不丢失会话上下文。
 */
import type { Session } from "../types/session";

const CURRENT_SESSION_KEY = "shop_query:current_session_id";
const SESSIONS_KEY = "shop_query:sessions";
const MESSAGES_PREFIX = "shop_query:messages:";

/** 读取当前会话 ID */
export function getCurrentSessionId(): string | null {
  try {
    return localStorage.getItem(CURRENT_SESSION_KEY);
  } catch {
    return null;
  }
}

/** 持久化当前会话 ID */
export function saveCurrentSessionId(sessionId: string | null): void {
  try {
    if (sessionId) {
      localStorage.setItem(CURRENT_SESSION_KEY, sessionId);
    } else {
      localStorage.removeItem(CURRENT_SESSION_KEY);
    }
  } catch {
    // localStorage 不可用时静默降级
  }
}

/** 读取本地缓存的会话列表 */
export function loadSessions(): Session[] {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    return raw ? (JSON.parse(raw) as Session[]) : [];
  } catch {
    return [];
  }
}

/** 持久化会话列表 */
export function saveSessions(sessions: Session[]): void {
  try {
    // 最多保留 20 条，避免 localStorage 溢出
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.slice(0, 20)));
  } catch {
    // 静默降级
  }
}

/** 读取指定会话的消息列表 */
export function loadMessages(sessionId: string): ChatMessageStore[] {
  try {
    const raw = localStorage.getItem(MESSAGES_PREFIX + sessionId);
    return raw ? (JSON.parse(raw) as ChatMessageStore[]) : [];
  } catch {
    return [];
  }
}

/** 持久化指定会话的消息列表（仅保留最近 50 条，裁剪大体积 result） */
export function saveMessages(sessionId: string, messages: ChatMessageStore[]): void {
  try {
    const trimmed = messages.slice(-50).map((m) => ({
      ...m,
      // result 可能很大，存储时只保留摘要信息
      result: m.result ? "<stored>" : undefined,
    }));
    localStorage.setItem(MESSAGES_PREFIX + sessionId, JSON.stringify(trimmed));
  } catch {
    // 静默降级
  }
}

/** 删除指定会话的消息缓存 */
export function deleteMessages(sessionId: string): void {
  try {
    localStorage.removeItem(MESSAGES_PREFIX + sessionId);
  } catch {
    // 静默降级
  }
}

/** 简化版 ChatMessage，用于本地存储 */
export type ChatMessageStore = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  status?: "streaming" | "done" | "error";
  steps?: { step: string; status: string; updatedAt: number }[];
  error?: string;
  cached?: boolean;
  result?: unknown;
};
