// 청크 테이블과 A/B 오디오 상태를 참조 디자인 형식으로 렌더링
import { useState } from "react";
import { Check, Edit3, X } from "lucide-react";
import type { ChunkRow } from "@/api/client";
import { cn } from "@/lib/cn";
import { toStaticUrl } from "@/lib/staticUrl";

interface ChunkInspectorTableProps {
  rows: ChunkRow[];
  selectedId?: string;
  selectedIds: Set<string>;
  writesDisabled: boolean;
  audioReady: boolean;
  onSelect: (row: ChunkRow) => void;
  onToggleSelect: (row: ChunkRow) => void;
  onToggleAllVisible: () => void;
  onUpdateText: (row: ChunkRow, text: string) => void;
}

export function ChunkInspectorTable({ rows, selectedId, selectedIds, writesDisabled, audioReady, onSelect, onToggleSelect, onToggleAllVisible, onUpdateText }: ChunkInspectorTableProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const allVisibleSelected = rows.length > 0 && rows.every((row) => selectedIds.has(row.chunk_id));

  const startEdit = (row: ChunkRow) => {
    if (writesDisabled) return;
    setEditingId(row.chunk_id);
    setDraft(row.translated_text ?? "");
  };

  const commit = (row: ChunkRow) => {
    if (editingId !== row.chunk_id) return;
    setEditingId(null);
    if (draft !== (row.translated_text ?? "")) onUpdateText(row, draft);
  };

  return (
    <div className="h-full overflow-auto">
      <table className="min-w-[980px] w-full border-separate border-spacing-0 text-left">
        <thead className="sticky top-0 z-10 bg-surface-soft">
          <tr className="font-mono text-data-label uppercase text-data-label">
            <th className="w-12 border-b border-border-hairline px-4 py-3 font-medium">
              <input
                type="checkbox"
                name="chunk-select-visible"
                checked={allVisibleSelected}
                disabled={rows.length === 0}
                onChange={onToggleAllVisible}
                aria-label="visible chunks 선택"
                className="h-4 w-4 accent-black"
              />
            </th>
            {['ID', 'SPK / TIME', 'EMOTION', 'TEXT SOURCE', 'TRANSLATED TEXT', 'AUDIO A/B', 'STATUS'].map((head) => (
              <th key={head} className="border-b border-border-hairline px-4 py-3 font-medium">{head}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const focused = row.chunk_id === selectedId;
            const checked = selectedIds.has(row.chunk_id);
            const stale = row.dub_stale || row.status === "stale";
            const blocked = Boolean(row.translation_blocked) || row.status === "blocked";
            return (
              <tr key={row.chunk_id} onClick={() => onSelect(row)} className={cn("cursor-pointer border-b border-border-hairline hover:bg-surface-soft", focused && "bg-surface-soft", checked && "bg-primary/5 ring-1 ring-inset ring-primary/20", blocked ? "shadow-[-3px_0_0_0_#f59e0b]" : stale && "shadow-[-3px_0_0_0_#f59e0b]")}>
                <td className="border-b border-border-hairline px-4 py-4 align-top">
                  <input
                    type="checkbox"
                    name="chunk-selection"
                    checked={checked}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => onToggleSelect(row)}
                    aria-label={`${row.chunk_id} 선택`}
                    className="h-4 w-4 accent-black"
                  />
                </td>
                <td className="border-b border-border-hairline px-4 py-4 align-top font-mono text-code-sm text-primary">{row.chunk_id}</td>
                <td className="border-b border-border-hairline px-4 py-4 align-top">
                  <span className="inline-flex h-8 items-center whitespace-nowrap rounded-full border border-border-hairline bg-white px-3 font-mono text-code-sm text-primary">
                    {row.speaker ? `SPK ${row.speaker}` : "SPK --"}
                  </span>
                  <div className="mt-1 whitespace-nowrap font-mono text-code-sm text-mute">{formatRange(row.start, row.end)}</div>
                </td>
                <td className="border-b border-border-hairline px-4 py-4 align-top">
                  <span className="rounded-full bg-surface-container px-3 py-1 font-mono text-data-label uppercase text-data-label">{row.emotion ?? "neutral"}</span>
                </td>
                <td className="max-w-[220px] border-b border-border-hairline px-4 py-4 align-top text-body-sm text-secondary">{row.source_text ?? "—"}</td>
                <td className="min-w-[260px] border-b border-border-hairline px-4 py-4 align-top">
                  {editingId === row.chunk_id ? (
                    <input name={`translation-${row.chunk_id}`} aria-label={`${row.chunk_id} translated text`} value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={() => commit(row)} onKeyDown={(e) => { if (e.key === "Enter") commit(row); }} autoFocus className="h-9 w-full rounded-full border border-primary bg-white px-4 text-body-sm text-primary focus:outline-none" />
                  ) : (
                    <button type="button" onDoubleClick={() => startEdit(row)} onClick={(e) => e.stopPropagation()} className="flex w-full items-center justify-between gap-3 rounded-full border border-border-hairline bg-white px-4 py-2 text-left text-body-sm text-primary">
                      <span className="line-clamp-2">{row.translated_text ?? "번역 대기"}</span>
                      <Edit3 className={cn("h-4 w-4 shrink-0", writesDisabled ? "text-mute" : "text-primary")} />
                    </button>
                  )}
                </td>
                <td className="border-b border-border-hairline px-4 py-4 align-top">
                  <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
                    <AudioPreview label="A" path={row.original_audio} ready={audioReady} />
                    <AudioPreview label="B" path={row.dubbed_audio} ready={audioReady} />
                  </div>
                </td>
                <td className="border-b border-border-hairline px-4 py-4 align-top"><StatusBadge row={row} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AudioPreview({ label, path, ready }: { label: string; path?: string | null; ready: boolean }) {
  const src = toStaticUrl(path);
  // ready=false 면 컨트롤은 그대로 두되 회색 + 클릭/포커스 차단. path 가 아직 없는 케이스도 동일 처리.
  const playable = ready && Boolean(src);
  return (
    <div className={cn("flex items-center gap-2 rounded-full bg-surface-soft px-2 py-1", !playable && "opacity-40")}>
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary font-mono text-data-label text-white">{label}</span>
      <audio
        src={playable ? src! : undefined}
        controls
        preload="none"
        tabIndex={playable ? 0 : -1}
        aria-disabled={!playable}
        className={cn("h-8 w-44", !playable && "pointer-events-none")}
      />
    </div>
  );
}

function StatusBadge({ row }: { row: ChunkRow }) {
  if (row.translation_blocked || row.status === "blocked") {
    return <span className="inline-flex items-center gap-2 rounded-full bg-term-yellow/15 px-3 py-1 text-caption-strong text-term-yellow" title={row.translation_blocked_reason ?? undefined}><X className="h-3 w-3" />BLOCKED</span>;
  }
  if (row.error || row.status === "error") {
    return <span className="inline-flex items-center gap-2 rounded-full bg-error-container px-3 py-1 text-caption-strong text-on-error-container"><X className="h-3 w-3" />ERROR</span>;
  }
  if (row.dub_stale || row.status === "stale") {
    return <span className="inline-flex items-center gap-2 rounded-full border border-term-yellow bg-term-yellow/10 px-3 py-1 text-caption-strong text-term-yellow"><span className="h-2 w-2 rounded-full bg-term-yellow" />STALE</span>;
  }
  if (row.status === "done") {
    return <span className="inline-flex items-center gap-2 rounded-full bg-status-done/10 px-3 py-1 text-caption-strong text-status-done"><Check className="h-3 w-3" />DONE</span>;
  }
  return <span className="font-mono text-code-sm text-mute">{row.status ?? "QUEUED"}</span>;
}

function formatRange(start: number | null | undefined, end: number | null | undefined): string {
  if (start == null || end == null) return "--:-- → --:--";
  return `${formatTime(start)} → ${formatTime(end)}`;
}

function formatTime(value: number): string {
  const min = Math.floor(value / 60);
  const sec = Math.floor(value % 60).toString().padStart(2, "0");
  return `${min}:${sec}`;
}
