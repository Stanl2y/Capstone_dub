// 실행된 step의 실제 산출물 메타데이터와 재실행 액션을 보여주는 artifact 화면
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, FileSearch, Lock, RefreshCcw } from "lucide-react";
import { api, type StepArtifact } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { getStepMeta, isStepName } from "@/lib/pipelineSpec";
import { canViewStepArtifacts } from "@/lib/runReadiness";
import { toStaticUrl } from "@/lib/staticUrl";

export function StepDetail() {
  const { id = "", stepName } = useParams<{ id: string; stepName: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const valid = isStepName(stepName);
  const step = valid ? stepName : undefined;
  const runQuery = useQuery({ queryKey: ["run", id], queryFn: () => api.getRun(id), enabled: Boolean(id), retry: 1 });
  const ready = step ? canViewStepArtifacts(runQuery.data, step) : false;
  const detailQuery = useQuery({ queryKey: ["step-detail", id, step], queryFn: () => api.getStepDetail(id, step!), enabled: Boolean(id && step && ready), retry: 1 });
  const rerunMutation = useMutation({
    mutationFn: () => api.rerunStep(id, step!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", id] });
      queryClient.invalidateQueries({ queryKey: ["step-detail", id, step] });
      navigate(`/runs/${id}`);
    },
  });

  if (!step) return <div className="p-8 text-body-sm text-term-red">알 수 없는 step입니다.</div>;
  if (runQuery.isLoading) return <StepEmpty runId={id} title="run을 불러오는 중입니다" body="이 step의 실행 여부를 확인하고 있습니다." />;
  if (!runQuery.data) return <StepEmpty runId={id} title="run을 찾을 수 없습니다" body="Run History에서 존재하는 run을 선택하세요." />;

  const meta = getStepMeta(step);
  const record = runQuery.data.steps.find((item) => item.name === step);
  const isActive = runQuery.data.status === "queued" || runQuery.data.status === "running";

  if (!ready) {
    return (
      <StepEmpty
        runId={id}
        title="아직 실행 전인 step입니다"
        body={`${meta.label} 단계가 시작되기 전이라 실제 artifact가 없습니다. Run Detail에서 현재 진행 상태를 먼저 확인하세요.`}
      />
    );
  }

  const detail = detailQuery.data;
  const inputArtifacts = detail?.artifacts?.filter((item) => item.kind === "input") ?? [];
  const outputArtifacts = detail?.artifacts?.filter((item) => item.kind === "output") ?? [];

  return (
    <section className="min-h-[calc(100vh-56px)] bg-background px-8 py-7">
      <div className="mx-auto max-w-[960px] space-y-6">
        <Link to={`/runs/${id}`} className="inline-flex items-center gap-2 text-body-sm-strong text-secondary hover:text-primary"><ArrowLeft className="h-4 w-4" />Back to run</Link>
        <Card className="rounded-[2rem] p-6">
          <div className="flex items-start justify-between gap-5">
            <div>
              <p className="font-mono text-data-label uppercase text-data-label">Step Artifact Viewer</p>
              <h1 className="mt-2 font-display text-heading-lg text-primary">{meta.label}</h1>
              <p className="mt-2 text-body-sm text-secondary">{meta.description}</p>
            </div>
            <div className="flex items-center gap-3">
              <span className="inline-flex h-9 items-center rounded-full bg-surface-soft px-4 font-mono text-code-sm text-primary">{detail?.status ?? record?.state ?? "metadata"}</span>
              <Button onClick={() => rerunMutation.mutate()} disabled={isActive || rerunMutation.isPending} variant="secondary">
                <RefreshCcw className="mr-2 h-4 w-4" />Rerun from here
              </Button>
            </div>
          </div>
          {detailQuery.isLoading ? <div className="mt-5 rounded-full bg-surface-soft px-4 py-2 text-caption-sm text-secondary">실제 artifact 상태를 불러오는 중입니다.</div> : null}
          {detail?.error ? <div className="mt-5 rounded-full bg-error-container px-4 py-2 text-caption-sm text-on-error-container">{detail.error}</div> : null}
        </Card>

        <div className="grid grid-cols-2 gap-5">
          <ArtifactList title="Inputs" items={inputArtifacts} fallback={meta.inputs} />
          <ArtifactList title="Outputs" items={outputArtifacts} fallback={meta.outputs} />
        </div>

        <Card className="rounded-[2rem] p-6">
          <p className="font-mono text-data-label uppercase text-data-label">Execution Context</p>
          <div className="mt-4 grid grid-cols-3 gap-3 font-mono text-code-sm">
            <Metric label="service" value={detail?.service ?? meta.service} />
            <Metric label="status" value={detail?.status ?? record?.state ?? "unknown"} />
            <Metric label="run" value={id} />
          </div>
        </Card>

        <Card className="rounded-[2rem] p-6">
          <p className="font-mono text-data-label uppercase text-data-label">Log Excerpt</p>
          <pre className="mt-4 max-h-80 overflow-auto rounded-[1.5rem] bg-[#080808] p-4 font-mono text-code-sm text-white/70">{detail?.log_excerpt?.join("\n") || "— 로그가 아직 없습니다 —"}</pre>
        </Card>
      </div>
    </section>
  );
}

function StepEmpty({ runId, title, body }: { runId: string; title: string; body: string }) {
  return (
    <section className="min-h-[calc(100vh-56px)] bg-background px-8 py-7">
      <div className="mx-auto max-w-[760px] rounded-[2rem] border border-border-hairline bg-surface-container-lowest p-8 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-surface-soft text-primary"><Lock className="h-5 w-5" /></div>
        <p className="mt-5 font-mono text-data-label uppercase text-data-label">Step Artifact · {runId}</p>
        <h1 className="mt-2 font-display text-heading-lg text-primary">{title}</h1>
        <p className="mx-auto mt-3 max-w-[560px] text-body-sm text-secondary">{body}</p>
        <Link to={`/runs/${runId}`} className="mt-6 inline-flex h-10 items-center gap-2 rounded-full bg-primary px-5 text-body-sm-strong text-white hover:bg-ink-deep"><ArrowLeft className="h-4 w-4" />Run Detail</Link>
      </div>
    </section>
  );
}

function ArtifactList({ title, items, fallback }: { title: string; items: StepArtifact[]; fallback: string[] }) {
  const rows = items.length ? items : fallback.map((path) => ({ label: path, path, exists: false }));
  return (
    <Card className="rounded-[2rem] p-6">
      <div className="flex items-center gap-2">
        <FileSearch className="h-4 w-4 text-mute" />
        <p className="font-mono text-data-label uppercase text-data-label">{title}</p>
      </div>
      <div className="mt-4 space-y-2">
        {rows.map((item) => <ArtifactRow key={`${title}-${item.label}-${item.path}`} item={item} />)}
      </div>
    </Card>
  );
}

function ArtifactRow({ item }: { item: StepArtifact }) {
  const url = item.exists ? staticArtifactUrl(item.path) : null;
  const body = <><span className={item.exists ? "text-status-done" : "text-mute"}>{item.exists ? "exists" : "not generated"}</span> · {item.label || item.path}</>;
  const className = "block rounded-full bg-surface-soft px-4 py-3 font-mono text-code-sm text-primary";
  return url ? <a href={url} target="_blank" rel="noreferrer" className={className}>{body}</a> : <div className={className}>{body}</div>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-[1.5rem] bg-surface-soft p-4"><div className="text-data-label uppercase text-data-label">{label}</div><div className="mt-1 truncate text-primary">{value}</div></div>;
}

function staticArtifactUrl(path: string): string | null {
  const url = toStaticUrl(path);
  return url && /^\/static\/(input|chunks|dub|output)\//.test(url) ? url : null;
}
