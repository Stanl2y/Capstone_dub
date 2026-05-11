// Run Detail 좌측 레일에서 15단계 상태와 active step을 표시
import type { ReactNode } from "react";
import type { StepName, StepRecord } from "@/api/client";
import { Check, Circle, Loader2, X } from "lucide-react";
import { cn } from "@/lib/cn";

const STATE_BADGE: Record<StepRecord["state"], { icon: typeof Circle; color: string; label: string }> = {
  pending: { icon: Circle, color: "text-mute", label: "대기" },
  running: { icon: Loader2, color: "text-primary animate-spin", label: "실행 중" },
  done: { icon: Check, color: "text-status-done", label: "완료" },
  failed: { icon: X, color: "text-status-failed", label: "실패" },
  skipped: { icon: Circle, color: "text-status-skipped", label: "스킵" },
};

interface StepStatusListProps {
  steps: StepRecord[];
  activeStep?: StepName;
  onStepSelect?: (step: StepName) => void;
}

export function StepStatusList({ steps, activeStep, onStepSelect }: StepStatusListProps) {
  return (
    <div className="space-y-1 font-mono text-code-sm">
      {steps.map((step, idx) => {
        const meta = STATE_BADGE[step.state];
        const Icon = meta.icon;
        const ix = String(idx + 1).padStart(2, "0");
        const isActive = activeStep === step.name;
        const content: ReactNode = (
          <>
            <span className="w-10 shrink-0 text-mute">{ix}</span>
            <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-container", meta.color)}>
              <Icon className="h-4 w-4" />
            </span>
            <span className={cn("min-w-0 flex-1 truncate", step.state === "failed" ? "text-status-failed" : "text-primary")}>{step.name}</span>
            <span className="shrink-0 text-caption-sm text-mute">{durationOrState(step, meta.label)}</span>
          </>
        );
        const rowClass = cn(
          "flex w-full items-center gap-3 rounded-full px-3 py-2 text-left transition-colors",
          isActive ? "bg-surface-container text-primary ring-1 ring-primary/10" : "hover:bg-surface-soft",
          step.state === "pending" && "opacity-65",
        );
        return onStepSelect ? (
          <button key={step.name} type="button" onClick={() => onStepSelect(step.name)} className={rowClass}>
            {content}
          </button>
        ) : (
          <div key={step.name} className={rowClass}>
            {content}
          </div>
        );
      })}
    </div>
  );
}

function durationOrState(step: StepRecord, label: string): string {
  if (step.started_at != null && step.ended_at != null) {
    // backend는 time.time() 초 단위로 저장 — ms 변환 휴리스틱 금지 (16분 넘는 step이 1/1000로 잘못 표시됨)
    const seconds = Math.max(0, step.ended_at - step.started_at);
    return seconds < 60 ? `${seconds.toFixed(1)}s` : `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  }
  return step.state === "pending" ? "" : label;
}
