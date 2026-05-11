// Run 상태에 따라 사용 가능한 화면과 다음 행동을 판단하는 유틸
import type { RunRecord, StepName, StepRecord } from "@/api/client";

export function completedStepCount(steps: StepRecord[]): number {
  return steps.filter((step) => step.state === "done" || step.state === "skipped").length;
}

export function progressPercent(steps: StepRecord[]): number {
  if (!steps.length) return 0;
  return Math.round((completedStepCount(steps) / steps.length) * 100);
}

export function stepRecord(run: RunRecord | null | undefined, name: StepName): StepRecord | undefined {
  return run?.steps.find((step) => step.name === name);
}

export function stepHasStarted(run: RunRecord | null | undefined, name: StepName): boolean {
  const state = stepRecord(run, name)?.state;
  return state === "running" || state === "done" || state === "failed" || state === "skipped";
}

export function stepIsDone(run: RunRecord | null | undefined, name: StepName): boolean {
  const state = stepRecord(run, name)?.state;
  return state === "done" || state === "skipped";
}

export function pipelineHasStarted(run: RunRecord | null | undefined): boolean {
  return Boolean(run?.steps.some((step) => step.state !== "pending"));
}

export function canInspectChunks(run: RunRecord | null | undefined): boolean {
  return Boolean(run && (stepIsDone(run, "build_timeline") || stepIsDone(run, "translate") || run.status === "success"));
}

export function canCompareOutput(run: RunRecord | null | undefined): boolean {
  return Boolean(run?.output_video);
}

// run_tts 가 끝나야 dub.wav 가 만들어지고 청크 음성 (A/B) 모두 안전하게 들을 수 있음
// translate~build_timeline 단계에서 청크 검수는 가능하지만 재생은 막아 부분 결과 노출을 차단
export function canPlayChunkAudio(run: RunRecord | null | undefined): boolean {
  return Boolean(run && (stepIsDone(run, "run_tts") || run.status === "success"));
}

export function canViewStepArtifacts(run: RunRecord | null | undefined, step: StepName): boolean {
  return stepHasStarted(run, step);
}

export function deriveActiveStep(steps: StepRecord[]): StepName {
  return steps.find((step) => step.state === "running")?.name ?? steps.find((step) => step.state === "failed")?.name ?? steps.find((step) => step.state === "pending")?.name ?? steps[steps.length - 1].name;
}

export function runStageMessage(run: RunRecord | null | undefined): string {
  if (!run) return "새 더빙 작업을 시작하면 진행 상황이 여기에 표시됩니다.";
  if (run.status === "queued" && !pipelineHasStarted(run)) return "Queue에 등록됐지만 아직 첫 단계가 시작되지 않았습니다. Docker worker와 backend 로그를 확인하세요.";
  if (run.status === "queued") return "Queue에 등록된 run입니다. 곧 다음 단계가 시작됩니다.";
  if (run.status === "running") return "파이프라인이 실행 중입니다. 현재 단계와 로그를 먼저 확인하세요.";
  if (run.status === "success") return "더빙이 완료됐습니다. 결과 영상 비교와 산출물 검토를 사용할 수 있습니다.";
  if (run.status === "failed") return "실행이 실패했습니다. 실패한 단계와 로그를 먼저 확인하세요.";
  if (run.status === "canceled") return "사용자가 취소한 run입니다. 산출물은 완료된 단계까지만 사용할 수 있습니다.";
  return "Run 상태를 확인하고 가능한 작업만 선택하세요.";
}
