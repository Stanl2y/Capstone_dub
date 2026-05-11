// 한 영상 (input_stem) 의 모든 run 시도를 한 페이지에서 — 최신 hero + run 카드 그리드
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowUpRight, Plus, XCircle } from "lucide-react";
import { api, type RunRecord } from "@/api/client";
import { Button } from "@/components/ui/button";
import { fileName } from "@/lib/staticUrl";
import { canCompareOutput, completedStepCount, progressPercent, runStageMessage } from "@/lib/runReadiness";

export function ProjectDetail() {
  const { inputStem = "" } = useParams<{ inputStem: string }>();
  const queryClient = useQueryClient();
  const runsQuery = useQuery({
    queryKey: ["project-runs", inputStem],
    queryFn: () => api.getProjectRuns(inputStem),
    enabled: Boolean(inputStem),
    refetchInterval: 15000,
    retry: 1,
  });
  const cancelMutation = useMutation({
    mutationFn: api.cancelRun,
    onSuccess: (run) => {
      queryClient.setQueryData<RunRecord[]>(["project-runs", inputStem], (current) =>
        current?.map((item) => (item.run_id === run.run_id ? run : item)),
      );
      queryClient.invalidateQueries({ queryKey: ["project-runs", inputStem] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      queryClient.invalidateQueries({ queryKey: ["run", run.run_id] });
    },
  });

  const runs = runsQuery.data ?? [];
  const latest = useMemo(() => runs[0], [runs]);
  const sample = latest?.input_video ?? "";
  const successCount = runs.filter((r) => r.status === "success").length;
  const failedCount = runs.filter((r) => r.status === "failed" || r.status === "canceled").length;

  return (
    <section className="min-h-[calc(100vh-56px)] bg-background px-8 py-7">
      <div className="mx-auto max-w-[1280px]">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border-hairline pb-5">
          <div className="min-w-0">
            <p className="font-mono text-data-label uppercase text-data-label">Project</p>
            <h1 className="mt-1 font-display text-heading-lg text-primary">{sample ? fileName(sample) : inputStem}</h1>
            <p className="mt-1 font-mono text-code-sm text-mute">{inputStem}</p>
          </div>
          <div className="flex items-center gap-2">
            <Link to="/projects" className="inline-flex h-9 items-center gap-2 rounded-full border border-border-hairline bg-surface-soft px-4 text-body-sm-strong text-primary hover:bg-surface-container">
              <ArrowLeft className="h-4 w-4" />
              All Projects
            </Link>
            <Link
              to={`/runs/new?input_path=${encodeURIComponent(latest?.input_video ?? "")}`}
              className="inline-flex h-10 items-center gap-2 rounded-full bg-primary px-5 text-body-sm-strong text-white hover:bg-ink-deep"
            >
              <Plus className="h-4 w-4" />이 영상으로 새 Run
            </Link>
          </div>
        </header>

        {runsQuery.isLoading ? (
          <div className="py-10 text-body-sm text-mute">run 목록을 불러오는 중입니다.</div>
        ) : runs.length === 0 ? (
          <div className="mt-8 rounded-[2rem] border border-border-hairline bg-surface-container-lowest p-8 text-center">
            <h2 className="font-display text-heading-md text-primary">이 프로젝트의 run 이 없습니다.</h2>
            <p className="mt-2 text-body-sm text-secondary">새 run 을 시작하면 여기에 시도가 쌓입니다.</p>
          </div>
        ) : (
          <>
            {latest ? <LatestHero run={latest} runCount={runs.length} successCount={successCount} failedCount={failedCount} /> : null}

            <div className="mt-7">
              <div className="mb-3 flex items-end justify-between">
                <div>
                  <p className="font-mono text-data-label uppercase text-data-label">All Runs</p>
                  <h2 className="mt-1 font-display text-heading-sm text-primary">이 영상으로 시도한 모든 run · {runs.length}</h2>
                </div>
              </div>
              <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {runs.map((run) => (
                  <RunCard
                    key={run.run_id}
                    run={run}
                    canceling={cancelMutation.isPending && cancelMutation.variables === run.run_id}
                    onCancel={() => cancelMutation.mutate(run.run_id)}
                  />
                ))}
              </ul>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function LatestHero({ run, runCount, successCount, failedCount }: { run: RunRecord; runCount: number; successCount: number; failedCount: number }) {
  const done = completedStepCount(run.steps);
  const pct = progressPercent(run.steps);
  return (
    <div className="mt-7 rounded-[2rem] border border-border-hairline bg-surface-container-lowest p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <span className="rounded-full bg-primary/10 px-3 py-1 font-mono text-data-label uppercase text-primary">latest run</span>
            <span className="rounded-full bg-surface-container px-3 py-1 font-mono text-data-label uppercase text-data-label">{run.status}</span>
          </div>
          <p className="mt-2 font-mono text-code-sm text-mute">{run.run_id}</p>
          <p className="mt-2 text-body-sm text-secondary">{runStageMessage(run)}</p>
        </div>
        <div className="flex shrink-0 flex-col gap-2">
          <Link to={`/runs/${run.run_id}`} className="inline-flex h-9 items-center justify-center rounded-full bg-primary px-4 text-body-sm-strong text-white hover:bg-ink-deep">
            진행 상태 보기
          </Link>
          {canCompareOutput(run) ? (
            <Link to={`/runs/${run.run_id}/compare`} className="inline-flex h-9 items-center justify-center rounded-full border border-border-hairline bg-surface-soft px-4 text-body-sm-strong text-primary hover:bg-surface-container">
              결과 비교
            </Link>
          ) : null}
        </div>
      </div>

      <div className="mt-5 grid grid-cols-3 gap-2 font-mono text-code-sm">
        <Stat label="runs" value={runCount} tone="primary" />
        <Stat label="success" value={successCount} tone="success" />
        <Stat label="failed" value={failedCount} tone="muted" />
      </div>

      <div className="mt-5">
        <div className="mb-2 flex justify-between font-mono text-code-sm text-secondary">
          <span>{done}/{run.steps.length}</span>
          <span>{pct}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-surface-container">
          <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>
    </div>
  );
}

function RunCard({ run, canceling, onCancel }: { run: RunRecord; canceling: boolean; onCancel: () => void }) {
  const done = completedStepCount(run.steps);
  const pct = progressPercent(run.steps);
  const active = run.status === "queued" || run.status === "running";
  const failed = run.status === "failed";
  const canceled = run.status === "canceled";
  const success = run.status === "success";
  return (
    <li className="relative">
      <Link
        to={`/runs/${run.run_id}`}
        className="flex h-full flex-col rounded-[2rem] border border-border-hairline bg-surface-container-lowest p-5 transition hover:bg-surface-soft"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="truncate font-display text-heading-sm text-primary">{run.run_id}</h3>
            <p className="mt-1 truncate font-mono text-code-sm text-mute">{configLabel(run.config_path)}</p>
          </div>
          <ArrowUpRight className="h-4 w-4 shrink-0 text-mute" />
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <span
            className={`rounded-full px-3 py-1 font-mono text-data-label uppercase ${
              active
                ? "bg-primary text-white"
                : success
                  ? "bg-status-done/10 text-status-done"
                  : failed
                    ? "bg-status-failed/10 text-status-failed"
                    : canceled
                      ? "bg-surface-container text-mute"
                      : "bg-surface-container text-data-label"
            }`}
          >
            {run.status}
          </span>
          <span className="rounded-full bg-surface-soft px-3 py-1 font-mono text-data-label uppercase text-data-label">
            {run.tts_engine}
          </span>
        </div>

        <div className="mt-4">
          <div className="mb-1 flex items-center justify-between font-mono text-caption-sm text-secondary">
            <span>{done}/{run.steps.length} steps</span>
            <span>{pct}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-container">
            <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
          </div>
        </div>

        <p className="mt-4 truncate text-caption-sm text-secondary">{runStageMessage(run)}</p>

        <p className="mt-3 font-mono text-caption-sm text-mute">created · {formatRelative(run.created_at)}</p>
      </Link>
      {active ? (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onCancel();
          }}
          disabled={canceling}
          className="absolute right-4 top-4 gap-2"
        >
          <XCircle className="h-4 w-4" />
          {canceling ? "Canceling" : "Cancel"}
        </Button>
      ) : null}
    </li>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: "primary" | "success" | "muted" }) {
  const color = tone === "success" ? "text-status-done" : tone === "primary" ? "text-primary" : "text-mute";
  return (
    <div className="rounded-[1rem] bg-surface-soft p-3">
      <p className="font-mono text-data-label uppercase text-data-label">{label}</p>
      <p className={`mt-1 font-display text-heading-sm ${color}`}>{value}</p>
    </div>
  );
}

function configLabel(path: string): string {
  return path.split("/").pop() ?? path;
}

function formatRelative(value: number): string {
  const ms = value > 10_000_000_000 ? value : value * 1000;
  const diff = Date.now() - ms;
  const min = Math.round(diff / 60_000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}시간 전`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day}일 전`;
  return new Date(ms).toLocaleDateString("ko-KR", { month: "2-digit", day: "2-digit" });
}
