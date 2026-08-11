/**
 * 会话本地存储工具
 * 使用 localStorage 缓存当前会话 ID 和会话列表元数据，
 * 确保页面刷新后不丢失会话上下文。
 */
import type { ChatMessage } from "../types/agent";
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

/** 按 updated_at 降序排列会话列表（最近修改的排在最前） */
export function sortSessions(sessions: Session[]): Session[] {
  return [...sessions].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

/** 持久化会话列表（会自动按更新时间排序后截断到 20 条） */
export function saveSessions(sessions: Session[]): void {
  try {
    const sorted = sortSessions(sessions);
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sorted.slice(0, 20)));
  } catch {
    // 静默降级
  }
}

/** 读取指定会话的消息列表 */
export function loadMessages(sessionId: string): ChatMessage[] {
  try {
    const raw = localStorage.getItem(MESSAGES_PREFIX + sessionId);
    if (!raw) return [];
    return JSON.parse(raw) as ChatMessage[];
  } catch {
    return [];
  }
}

/** 持久化指定会话的消息列表（保留最近 50 条，包含完整 result 数据）
 * 若 localStorage 配额超限导致写入失败，会静默降级——
 * 此时消息仅在内存中存在，刷新后丢失，属可接受的降级行为。 */
export function saveMessages(sessionId: string, messages: ChatMessage[]): void {
  try {
    const trimmed = messages.slice(-50);
    localStorage.setItem(MESSAGES_PREFIX + sessionId, JSON.stringify(trimmed));
  } catch {
    // 静默降级：配额超限或其他存储异常时不阻断主流程
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
