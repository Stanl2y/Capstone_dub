// Run 실행 상태와 실제로 가능한 다음 행동을 보여주는 모니터링 화면
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Activity, Clock3, Lock } from "lucide-react";
import { api, type StepName } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { LogTail } from "@/components/LogTail";
import { StepStatusList } from "@/components/StepStatusList";
import { useRunSocket } from "@/hooks/useRunSocket";
import { getStepMeta } from "@/lib/pipelineSpec";
import { fileName } from "@/lib/staticUrl";
import { canCompareOutput, canInspectChunks, completedStepCount, deriveActiveStep, progressPercent, runStageMessage } from "@/lib/runReadiness";

export function Progress() {
  const { id = "" } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [selectedStep, setSelectedStep] = useState<StepName | undefined>();
  const runQuery = useQuery({
    queryKey: ["run", id],
    queryFn: () => api.getRun(id),
    enabled: Boolean(id),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status === "running" || status === "queued" ? 5000 : false;
    },
  });
  const historyLogQuery = useQuery({ queryKey: ["log", id], queryFn: () => api.getLog(id), enabled: Boolean(id), retry: 1 });
  const { logLines, connected } = useRunSocket(id, runQuery.data?.status === "running");
  const combinedLogLines = useMemo(() => [...(historyLogQuery.data?.lines ?? []), ...logLines], [historyLogQuery.data?.lines, logLines]);

  const cancelMutation = useMutation({
    mutationFn: () => api.cancelRun(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", id] }),
  });
  const resumeMutation = useMutation({
    mutationFn: () => api.resumeRun(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", id] }),
  });

  if (runQuery.isLoading) return <div className="p-8 text-body-sm text-mute">run을 불러오는 중입니다.</div>;
  if (!runQuery.data) return <div className="p-8 text-body-sm text-term-red">run을 찾을 수 없습니다. {id}</div>;

  const run = runQuery.data;
  const isActive = run.status === "running" || run.status === "queued";
  const canResume = run.status === "failed" || run.status === "canceled";
  const resumeFromStep = run.steps.find((step) => step.state !== "done")?.name;
  const activeStep = selectedStep ?? deriveActiveStep(run.steps);
  const activeRecord = run.steps.find((step) => step.name === activeStep) ?? run.steps[0];
  const activeMeta = getStepMeta(activeRecord.name);
  const done = completedStepCount(run.steps);
  const progress = progressPercent(run.steps);
  const chunksReady = canInspectChunks(run);
  const compareReady = canCompareOutput(run);

  return (
    <section className="h-[calc(100vh-56px)] overflow-hidden bg-background">
      <header className="flex h-16 items-center justify-between border-b border-border-hairline bg-surface-container-lowest px-6">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <p className="font-mono text-code-sm text-mute">{run.run_id}</p>
            <StatusBadge status={run.status} connected={connected} />
          </div>
          <h1 className="mt-1 truncate font-display text-heading-sm text-primary">{fileName(run.input_video)}</h1>
        </div>
        <div className="flex items-center gap-3">
          <Link to={`/runs/${run.run_id}/activity`} className="inline-flex h-9 items-center rounded-full border border-border-hairline bg-surface-soft px-4 text-body-sm-strong text-primary hover:bg-surface-container">Activity</Link>
          {isActive && <Button variant="secondary" onClick={() => cancelMutation.mutate()} disabled={cancelMutation.isPending}>Cancel</Button>}
          {canResume && resumeFromStep && (
            <Button onClick={() => resumeMutation.mutate()} disabled={resumeMutation.isPending} title={`${resumeFromStep} 부터 재시작`}>
              {resumeMutation.isPending ? "재시작 중..." : `Resume from ${resumeFromStep}`}
            </Button>
          )}
          {compareReady ? (
            <Link to={`/runs/${run.run_id}/compare`} className="inline-flex h-9 items-center rounded-full bg-primary px-5 text-button-md text-white hover:bg-ink-deep">결과 비교</Link>
          ) : (
            <span className="inline-flex h-9 items-center rounded-full border border-border-hairline bg-surface-soft px-5 text-button-md text-mute">mux 완료 후 결과 비교 가능</span>
          )}
        </div>
      </header>

      <div className="grid h-[calc(100vh-120px)] grid-cols-[320px_minmax(420px,1fr)_480px] overflow-hidden">
        <aside className="overflow-y-auto border-r border-border-hairline bg-surface-container-lowest p-5">
          <div className="mb-5 flex items-end justify-between">
            <div>
              <p className="font-mono text-data-label uppercase text-data-label">Pipeline Steps</p>
              <h2 className="mt-1 font-display text-heading-sm text-primary">15단계 실행</h2>
            </div>
            <span className="font-mono text-code-sm text-mute">{done}/{run.steps.length}</span>
          </div>
          <StepStatusList steps={run.steps} activeStep={activeRecord.name} onStepSelect={setSelectedStep} />
        </aside>

        <main className="overflow-y-auto p-7">
          <div className="mx-auto max-w-[760px] space-y-6">
            <Card className="rounded-[2rem] p-6">
              <div className="flex items-start justify-between gap-5">
                <div>
                  <p className="font-mono text-data-label uppercase text-data-label">Current State</p>
                  <h2 className="mt-2 font-display text-heading-lg text-primary">{activeMeta.label}</h2>
                  <p className="mt-2 text-body-sm text-secondary">{runStageMessage(run)}</p>
                </div>
                <span className="inline-flex h-9 items-center gap-2 rounded-full bg-surface-soft px-4 font-mono text-code-sm text-primary">
                  <Activity className="h-4 w-4" />
                  {activeRecord.state}
                </span>
              </div>
              <div className="mt-6 rounded-[1.5rem] bg-surface-soft p-5">
                <div className="mb-3 flex items-center justify-between text-body-sm-strong text-primary">
                  <span>Pipeline Progress</span>
                  <span className="font-mono text-code-sm">{progress}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-surface-container">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${progress}%` }} />
                </div>
                <div className="mt-4 grid grid-cols-3 gap-3 font-mono text-code-sm text-secondary">
                  <Metric label="service" value={run.step_runtime?.[activeRecord.name]?.service ?? activeMeta.service} />
                  <Metric label="tool" value={run.step_runtime?.[activeRecord.name]?.tool || "—"} />
                  <Metric label="completed" value={`${done}/${run.steps.length}`} />
                </div>
              </div>
            </Card>

            <div className="grid grid-cols-2 gap-5">
              <ArtifactCard title="Inputs" items={activeMeta.inputs} />
              <ArtifactCard title="Expected Outputs" items={activeMeta.outputs} />
            </div>

            <Card className="rounded-[2rem] p-6">
              <p className="font-mono text-data-label uppercase text-data-label">Available Actions</p>
              <h2 className="mt-1 font-display text-heading-sm text-primary">지금 가능한 화면</h2>
              <div className="mt-5 grid grid-cols-3 gap-3">
                {chunksReady ? (
                  <Link to={`/runs/${run.run_id}/chunks`} className="rounded-[1.5rem] border border-border-hairline bg-surface-soft p-4 text-body-sm-strong text-primary hover:bg-surface-container">Chunks 확인</Link>
                ) : (
                  <LockedAction title="Chunks" reason="translate 또는 build_timeline 완료 후 사용할 수 있습니다." />
                )}
                <Link to={`/runs/${run.run_id}/metrics`} className="rounded-[1.5rem] border border-border-hairline bg-surface-soft p-4 text-body-sm-strong text-primary hover:bg-surface-container">Metrics 확인</Link>
                {compareReady ? (
                  <Link to={`/runs/${run.run_id}/compare`} className="rounded-[1.5rem] bg-primary p-4 text-body-sm-strong text-white hover:bg-ink-deep">결과 비교</Link>
                ) : (
                  <LockedAction title="Compare" reason="mux 단계가 output video를 만든 뒤 사용할 수 있습니다." />
                )}
              </div>
            </Card>
          </div>
        </main>

        <aside className="flex min-h-0 flex-col border-l border-border-hairline bg-[#080808] text-white">
          <div className="flex h-12 items-center justify-between border-b border-white/10 bg-[#151515] px-5">
            <span className="font-mono text-data-label uppercase text-white/60">STDOUT LOGS</span>
            <span className="inline-flex items-center gap-2 font-mono text-code-sm text-white/60"><span className={`h-2 w-2 rounded-full ${connected ? "bg-status-done" : "bg-mute"}`} />{connected ? "live" : "not connected"}</span>
          </div>
          <LogTail lines={combinedLogLines} className="min-h-0 flex-1 px-5 py-4 text-white/70" emptyLabel={run.status === "running" ? "WebSocket 로그를 기다리는 중입니다." : "저장된 로그가 아직 없습니다."} />
        </aside>
      </div>
    </section>
  );
}

function StatusBadge({ status, connected }: { status: string; connected: boolean }) {
  const tone = status === "success" ? "bg-status-done/10 text-status-done" : status === "failed" ? "bg-status-failed/10 text-status-failed" : status === "canceled" ? "bg-surface-container text-mute" : "bg-primary text-white";
  return <span className={`inline-flex h-7 items-center gap-2 rounded-full px-3 text-caption-strong ${tone}`}><span className={`h-2 w-2 rounded-full ${connected ? "bg-status-done" : "bg-mute"}`} />{status}</span>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-[1rem] bg-surface-container-lowest p-3"><div className="text-data-label uppercase text-data-label">{label}</div><div className="mt-1 truncate text-primary">{value}</div></div>;
}

function ArtifactCard({ title, items }: { title: string; items: string[] }) {
  return (
    <Card className="rounded-[2rem] p-5">
      <div className="mb-4 flex items-center gap-2">
        <Clock3 className="h-4 w-4 text-mute" />
        <h3 className="font-display text-heading-sm text-primary">{title}</h3>
      </div>
      <div className="space-y-2">
        {items.map((item) => <div key={item} className="rounded-full bg-surface-soft px-4 py-2 font-mono text-code-sm text-secondary">{item}</div>)}
      </div>
    </Card>
  );
}

function LockedAction({ title, reason }: { title: string; reason: string }) {
  return (
    <div className="rounded-[1.5rem] border border-border-hairline bg-surface-soft p-4 text-mute">
      <div className="flex items-center gap-2 text-body-sm-strong text-primary"><Lock className="h-4 w-4" />{title}</div>
      <p className="mt-2 text-caption-sm text-secondary">{reason}</p>
    </div>
  );
}
