// 참조 대시보드의 phase box와 pill node 파이프라인 그래프
import { Link } from "react-router-dom";
import { Check, Circle, Loader2, Minus, X } from "lucide-react";
import type { StepName, StepRecord, StepState } from "@/api/client";
import { PIPELINE_PHASES, getStepMeta } from "@/lib/pipelineSpec";
import { cn } from "@/lib/cn";

interface PipelineGraphProps {
  steps: StepRecord[];
  runId?: string;
}

const stateIcon: Record<StepState, typeof Circle> = {
  pending: Circle,
  running: Loader2,
  done: Check,
  failed: X,
  skipped: Minus,
};

export function PipelineGraph({ steps, runId }: PipelineGraphProps) {
  const stepMap = new Map<StepName, StepRecord>(steps.map((step) => [step.name, step]));

  return (
    <div className="relative overflow-x-auto pb-8 pt-6">
      <div className="flex min-w-[1180px] items-stretch gap-5 px-2">
        {PIPELINE_PHASES.map((phase, phaseIndex) => (
          <section key={phase.id} className="relative flex-1 rounded-[2rem] border border-border-hairline bg-surface-soft/80 px-5 pb-5 pt-7">
            <div className="absolute -top-3 left-6 rounded-full border border-border-hairline bg-surface-container-lowest px-3 py-1 font-mono text-data-label uppercase text-data-label">
              {phase.label}
            </div>
            <div className="space-y-3">
              {phase.steps.map((name, index) => {
                const record = stepMap.get(name) ?? { name, state: "pending" as const };
                const nextLabel = phase.steps[index + 1] ? getStepMeta(phase.steps[index + 1]).inputs[0] : getStepMeta(name).outputs[0];
                return (
                  <div key={name} className="relative">
                    <PipelineNode record={record} runId={runId} />
                    {(index < phase.steps.length - 1 || phaseIndex < PIPELINE_PHASES.length - 1) && (
                      <div className="pointer-events-none ml-8 flex h-5 items-center gap-2 text-data-label text-data-label">
                        <span className={cn("h-px flex-1", record.state === "pending" ? "border-t border-dashed border-data-flow" : "bg-data-flow")} />
                        <span className="rounded-full bg-surface-soft px-2 font-mono">{nextLabel}</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function PipelineNode({ record, runId }: { record: StepRecord; runId?: string }) {
  const meta = getStepMeta(record.name);
  const Icon = stateIcon[record.state];
  const content = (
    <div className={cn("group flex min-h-[68px] items-center gap-3 rounded-full border bg-surface-container-lowest px-4 transition-all", nodeTone(record.state))}>
      <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-full", iconTone(record.state))}>
        <Icon className={cn("h-4 w-4", record.state === "running" && "animate-spin")} />
      </span>
      <span className="min-w-0 flex-1 text-left">
        <span className="block truncate text-body-sm-strong text-primary">{meta.label}</span>
        <span className="block truncate font-mono text-code-sm text-mute">{statusLabel(record)}</span>
      </span>
    </div>
  );

  if (!runId || record.state === "pending") return content;
  return (
    <Link to={`/runs/${runId}/steps/${record.name}`} className="block rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring">
      {content}
    </Link>
  );
}

function nodeTone(state: StepState): string {
  if (state === "running") return "border-primary border-2 shadow-running-ring";
  if (state === "done") return "border-border-hairline bg-surface-container-lowest";
  if (state === "failed") return "border-status-failed bg-error-container/40";
  if (state === "skipped") return "border-border-hairline border-dashed text-mute";
  return "border-border-hairline opacity-70";
}

function iconTone(state: StepState): string {
  if (state === "running") return "bg-primary text-white";
  if (state === "done") return "bg-status-done/10 text-status-done";
  if (state === "failed") return "bg-status-failed/10 text-status-failed";
  return "bg-surface-container text-mute";
}

function statusLabel(record: StepRecord): string {
  if (record.state === "done") return durationLabel(record) ?? "done";
  if (record.state === "running") return "Running...";
  if (record.state === "failed") return record.error ?? "failed";
  if (record.state === "skipped") return "skipped";
  return "pending";
}

function durationLabel(record: StepRecord): string | null {
  if (record.started_at == null || record.ended_at == null) return null;
  // backend는 time.time() 초 단위로 저장 — ms 변환 휴리스틱 금지 (16분 넘는 step이 1/1000로 잘못 표시됨)
  const seconds = Math.max(0, record.ended_at - record.started_at);
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}
