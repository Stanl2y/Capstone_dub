// Run별 실제 산출물에서 계산한 더빙 품질 지표를 보여주는 화면
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api } from "@/api/client";
import { Card } from "@/components/ui/card";
import { fileName } from "@/lib/staticUrl";

export function Metrics() {
  const { id = "" } = useParams<{ id: string }>();
  const runQuery = useQuery({ queryKey: ["run", id], queryFn: () => api.getRun(id), enabled: Boolean(id), retry: 1 });
  const metricsQuery = useQuery({ queryKey: ["metrics", id], queryFn: () => api.getMetrics(id), enabled: Boolean(id), retry: 1 });
  const metrics = metricsQuery.data;

  return (
    <section className="min-h-[calc(100vh-56px)] bg-background px-8 py-7">
      <div className="mx-auto max-w-[960px] space-y-6">
        <Link to={`/runs/${id}`} className="inline-flex items-center gap-2 text-body-sm-strong text-secondary hover:text-primary"><ArrowLeft className="h-4 w-4" />Back to run</Link>
        <header className="border-b border-border-hairline pb-5">
          <p className="font-mono text-data-label uppercase text-data-label">Evaluation Metrics</p>
          <h1 className="mt-2 font-display text-heading-lg text-primary">더빙 품질 지표</h1>
          <p className="mt-2 text-body-sm text-secondary">{runQuery.data ? fileName(runQuery.data.input_video) : "실제 run 산출물을 불러오는 중입니다."}</p>
        </header>

        {metricsQuery.isLoading ? <div className="text-body-sm text-mute">metrics를 계산하는 중입니다.</div> : null}
        {metricsQuery.isError ? <div className="rounded-[1.5rem] bg-error-container p-5 text-body-sm text-on-error-container">metrics endpoint를 불러오지 못했습니다.</div> : null}

        <div className="grid grid-cols-3 gap-5">
          <Metric title="Total Chunks" value={formatNumber(metrics?.total_chunks)} />
          <Metric title="Dub Ready" value={formatNumber(metrics?.ready_chunks)} />
          <Metric title="Stale Chunks" value={formatNumber(metrics?.stale_chunks)} />
          <Metric title="Chunk Errors" value={formatNumber(metrics?.error_chunks)} />
          <Metric title="Duration Ratio" value={metrics?.average_duration_ratio == null ? "not ready" : `${metrics.average_duration_ratio.toFixed(2)}x`} />
          <Metric title="Validation Failures" value={formatNumber(metrics?.validation_failures)} />
        </div>

        <Card className="rounded-[2rem] p-6">
          <p className="font-mono text-data-label uppercase text-data-label">Emotion Distribution</p>
          <div className="mt-4 space-y-3">
            {Object.entries(metrics?.emotion_distribution ?? {}).length ? Object.entries(metrics?.emotion_distribution ?? {}).map(([label, count]) => (
              <div key={label} className="flex items-center justify-between rounded-full bg-surface-soft px-4 py-3 font-mono text-code-sm">
                <span className="text-primary">{label}</span>
                <span className="text-secondary">{count}</span>
              </div>
            )) : <div className="rounded-full bg-surface-soft px-4 py-3 text-body-sm text-mute">emotion artifact가 아직 없습니다.</div>}
          </div>
        </Card>
      </div>
    </section>
  );
}

function Metric({ title, value }: { title: string; value: string }) {
  return (
    <Card className="rounded-[2rem] p-6">
      <p className="font-mono text-data-label uppercase text-data-label">{title}</p>
      <div className="mt-6 font-display text-heading-md text-primary">{value}</div>
    </Card>
  );
}

function formatNumber(value: number | null | undefined): string {
  return value == null ? "not ready" : value.toLocaleString();
}
