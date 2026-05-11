// 한 run 내부의 변경 이력 (audit log) 을 시간순 timeline 으로 보여주는 화면
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, RefreshCcw } from "lucide-react";
import { api, isOptionalEndpointMissing } from "@/api/client";
import { Button } from "@/components/ui/button";
import { EventRow, groupByDay } from "@/components/activity/EventRow";
import { fileName } from "@/lib/staticUrl";

export function Activity() {
  const { id = "" } = useParams<{ id: string }>();
  const runQuery = useQuery({ queryKey: ["run", id], queryFn: () => api.getRun(id), enabled: Boolean(id), retry: 1, staleTime: 10_000 });
  const activityQuery = useQuery({
    queryKey: ["activity", id],
    queryFn: () => api.getActivity(id),
    enabled: Boolean(id),
    retry: 1,
    refetchInterval: () => {
      const status = runQuery.data?.status;
      return status === "running" || status === "queued" ? 5000 : false;
    },
  });
  const events = activityQuery.data ?? [];
  const grouped = useMemo(() => groupByDay(events), [events]);
  const endpointMissing = activityQuery.isError && isOptionalEndpointMissing(activityQuery.error);

  return (
    <section className="min-h-[calc(100vh-56px)] bg-background px-8 py-7">
      <div className="mx-auto max-w-[920px]">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border-hairline pb-5">
          <div className="min-w-0">
            <p className="font-mono text-data-label uppercase text-data-label">Run Activity</p>
            <h1 className="mt-1 font-display text-heading-lg text-primary">{runQuery.data ? fileName(runQuery.data.input_video) : id}</h1>
            <p className="mt-1 font-mono text-code-sm text-mute">{id}</p>
          </div>
          <div className="flex items-center gap-2">
            <Link to={`/runs/${id}`} className="inline-flex h-9 items-center gap-2 rounded-full border border-border-hairline bg-surface-soft px-4 text-body-sm-strong text-primary hover:bg-surface-container">
              <ArrowLeft className="h-4 w-4" />
              Run Detail
            </Link>
            <Button variant="secondary" onClick={() => activityQuery.refetch()} disabled={activityQuery.isFetching} className="gap-2">
              <RefreshCcw className="h-4 w-4" />
              {activityQuery.isFetching ? "갱신 중" : "Refresh"}
            </Button>
          </div>
        </header>

        {endpointMissing ? (
          <EmptyCard title="Activity API 가 아직 연결되지 않았습니다." body="백엔드를 최신으로 다시 띄운 뒤 새로고침 하세요." />
        ) : activityQuery.isLoading ? (
          <div className="py-10 text-body-sm text-mute">이벤트를 불러오는 중입니다.</div>
        ) : events.length === 0 ? (
          <EmptyCard title="아직 기록된 이벤트가 없습니다." body="run 생성, 청크 편집, redub, step 재실행 등이 일어나면 여기에 시간순으로 쌓입니다." />
        ) : (
          <div className="mt-7 space-y-7">
            {grouped.map(([day, items]) => (
              <div key={day}>
                <p className="mb-3 font-mono text-data-label uppercase text-data-label">{day}</p>
                <ul className="relative border-l border-border-hairline pl-6">
                  {items.map((event, idx) => (
                    <EventRow key={`${day}-${idx}`} event={event} />
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function EmptyCard({ title, body }: { title: string; body: string }) {
  return (
    <div className="mt-8 rounded-[2rem] border border-border-hairline bg-surface-container-lowest p-8 text-center">
      <h2 className="font-display text-heading-md text-primary">{title}</h2>
      <p className="mt-2 text-body-sm text-secondary">{body}</p>
    </div>
  );
}
