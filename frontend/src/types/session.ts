/**
 * 会话类型定义
 * 多轮对话场景下的会话元数据与前端持久化结构
 */
export type Session = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  last_summary: string | null;
};
