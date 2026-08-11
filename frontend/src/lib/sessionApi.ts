/**
 * 会话管理接口客户端
 * 封装后端 /api/sessions CRUD 接口请求
 */
import type { ChatMessage } from "../types/agent";
import type { Session } from "../types/session";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

type ApiResponse<T> = {
  code: number;
  message: string;
  data: T;
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new Error(`接口请求失败：HTTP ${res.status}`);
  }
  const json = (await res.json()) as ApiResponse<T>;
  if (json.code !== 0) {
    throw new Error(json.message || "接口返回错误");
  }
  return json.data;
}

/** 获取全部会话列表 */
export async function listSessions(): Promise<Session[]> {
  return request<Session[]>(`${API_BASE_URL}/api/sessions`);
}

/** 创建新会话 */
export async function createSession(name?: string): Promise<Session> {
  return request<Session>(`${API_BASE_URL}/api/sessions`, {
    method: "POST",
    body: JSON.stringify({ name: name ?? null }),
  });
}

/** 重命名会话 */
export async function renameSession(sessionId: string, name: string): Promise<Session> {
  return request<Session>(`${API_BASE_URL}/api/sessions/${sessionId}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

/** 删除会话 */
export async function deleteSession(sessionId: string): Promise<void> {
  await request<void>(`${API_BASE_URL}/api/sessions/${sessionId}`, {
    method: "DELETE",
  });
}

/** 获取指定会话的完整对话历史（含 result 数据，供切换会话时恢复渲染） */
export async function getSessionMessages(sessionId: string): Promise<ChatMessage[]> {
  return request<ChatMessage[]>(`${API_BASE_URL}/api/sessions/${sessionId}/messages`);
}
