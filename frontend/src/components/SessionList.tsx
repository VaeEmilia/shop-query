/**
 * 会话列表侧边栏组件
 * 展示全部会话，支持切换、重命名和删除操作
 */
import { Check, MessageSquare, Pencil, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Session } from "../types/session";
import { cn } from "../lib/format";

type SessionListProps = {
  sessions: Session[];
  currentSessionId: string | null;
  disabled?: boolean;
  onSelect: (sessionId: string) => void;
  onRename: (sessionId: string, name: string) => void;
  onDelete: (sessionId: string) => void;
};

export function SessionList({
  sessions,
  currentSessionId,
  disabled,
  onSelect,
  onRename,
  onDelete,
}: SessionListProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (editingId) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editingId]);

  const startEdit = (session: Session) => {
    setEditingId(session.id);
    setEditValue(session.name);
  };

  const confirmEdit = () => {
    const name = editValue.trim();
    if (editingId && name) {
      onRename(editingId, name);
    }
    setEditingId(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditValue("");
  };

  if (sessions.length === 0) {
    return (
      <p className="px-1 py-2 text-xs text-ink/40">暂无会话，点击上方按钮新建。</p>
    );
  }

  return (
    <div className="space-y-1">
      {sessions.map((session) => {
        const isActive = session.id === currentSessionId;
        const isEditing = session.id === editingId;

        return (
          <div
            key={session.id}
            className={cn(
              "group flex cursor-pointer items-center gap-2 border-l-2 px-2 py-2 text-sm transition",
              isActive
                ? "border-moss bg-white/80 text-ink"
                : "border-transparent text-ink/65 hover:bg-white/50 hover:text-ink",
              disabled && !isActive && "cursor-not-allowed opacity-50",
            )}
            onClick={() => !disabled && !isEditing && onSelect(session.id)}
          >
            <MessageSquare
              className={cn("h-3.5 w-3.5 shrink-0", isActive ? "text-moss" : "text-ink/35")}
              aria-hidden="true"
            />

            <div className="min-w-0 flex-1">
              {isEditing ? (
                <input
                  ref={inputRef}
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") confirmEdit();
                    if (e.key === "Escape") cancelEdit();
                  }}
                  onClick={(e) => e.stopPropagation()}
                  className="w-full border border-moss/40 bg-white px-1.5 py-0.5 text-sm outline-none"
                />
              ) : (
                <>
                  <div className="truncate font-medium">{session.name}</div>
                  {session.last_summary && (
                    <div className="truncate text-xs text-ink/40">
                      {session.last_summary}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* 操作按钮：编辑时显示确认/取消，否则 hover 显示编辑/删除 */}
            {isEditing ? (
              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    confirmEdit();
                  }}
                  className="rounded p-1 text-moss transition hover:bg-moss/10"
                  title="确认"
                >
                  <Check className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    cancelEdit();
                  }}
                  className="rounded p-1 text-ink/40 transition hover:bg-ink/5"
                  title="取消"
                >
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </div>
            ) : (
              <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    startEdit(session);
                  }}
                  className="rounded p-1 text-ink/40 transition hover:bg-ink/5 hover:text-ink"
                  title="重命名"
                >
                  <Pencil className="h-3 w-3" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (window.confirm(`确认删除会话「${session.name}」？`)) {
                      onDelete(session.id);
                    }
                  }}
                  className="rounded p-1 text-ink/40 transition hover:bg-tomato/10 hover:text-tomato"
                  title="删除"
                >
                  <Trash2 className="h-3 w-3" aria-hidden="true" />
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
