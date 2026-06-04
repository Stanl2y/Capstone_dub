// 최종 output video가 있을 때 단일 플레이어로 원본과 더빙 오디오를 비교 재생하는 화면
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Edit3, Film, Pause, Play, RotateCcw, RotateCw, Volume2, Wand2 } from "lucide-react";
import { api } from "@/api/client";
import { useSyncedPlayback, type AudioMode } from "@/hooks/useSyncedPlayback";
import { fileName, toStaticUrl } from "@/lib/staticUrl";
import { canCompareOutput } from "@/lib/runReadiness";

export function Compare() {
  const { id = "" } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const runQuery = useQuery({ queryKey: ["run", id], queryFn: () => api.getRun(id), enabled: Boolean(id) });
  const run = runQuery.data;
  const inputUrl = toStaticUrl(run?.input_video);
  const outputUrl = toStaticUrl(run?.output_video);
  // 최종 영상은 고정 URL이라 재mux 후에도 브라우저가 옛 영상을 캐시함 → mux 완료시각을 버전 쿼리로 붙여 강제 리프레시
  const outputVersion = run?.steps?.find((s) => s.name === "mux")?.ended_at ?? 0;
  const ready = canCompareOutput(run);
  const player = useSyncedPlayback(ready);
  const activeAudioPath = player.audioMode === "original" ? run?.input_video : run?.output_video;
  const progress = player.duration ? (player.currentTime / player.duration) * 100 : 0;
  const remuxBusy = run?.status === "queued" || run?.status === "running";
  const remuxMutation = useMutation({
    mutationFn: () => api.rerunStep(id, "compose_audio"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", id] }),
  });

  if (runQuery.isLoading) return <CompareEmpty runId={id} title="run을 불러오는 중입니다" body="최종 output video가 있는지 확인하고 있습니다." />;
  if (!run) return <CompareEmpty runId={id} title="run을 찾을 수 없습니다" body="Run History에서 존재하는 run을 선택하세요." />;
  if (!ready || !outputUrl) {
    return (
      <CompareEmpty
        runId={id}
        title="아직 비교할 최종 영상이 없습니다"
        body="Compare Player는 mux 단계가 output video를 만든 뒤에 열립니다. 지금은 Run Detail에서 진행 상태와 로그를 먼저 확인하세요."
      />
    );
  }

  return (
    <section className="flex min-h-[calc(100vh-56px)] flex-col overflow-y-auto bg-background lg:h-[calc(100vh-56px)] lg:overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-hairline bg-surface-container-lowest px-4 py-3 sm:px-6">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <Link to={`/runs/${id}`} className="inline-flex h-9 shrink-0 items-center gap-2 rounded-full border border-border-hairline bg-surface-soft px-4 text-body-sm-strong text-primary hover:bg-surface-container">
            <ArrowLeft className="h-4 w-4" />Run Detail
          </Link>
          <span className="hidden truncate font-mono text-code-sm text-mute sm:inline">{id}</span>
          <span className="hidden max-w-[14rem] truncate font-mono text-code-sm text-mute sm:inline">{fileName(activeAudioPath)}</span>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
          <Link to={`/runs/${id}/chunks`} className="inline-flex h-9 items-center gap-2 whitespace-nowrap rounded-full border border-border-hairline bg-surface-soft px-4 text-body-sm-strong text-primary hover:bg-surface-container">
            <Edit3 className="h-4 w-4" />Edit Chunks
          </Link>
          <button
            type="button"
            onClick={() => remuxMutation.mutate()}
            disabled={remuxMutation.isPending || remuxBusy}
            className="inline-flex h-9 items-center gap-2 whitespace-nowrap rounded-full bg-primary px-4 text-body-sm-strong text-white hover:bg-ink-deep disabled:bg-surface-soft disabled:text-mute"
          >
            <Wand2 className="h-4 w-4" />
            <span className="hidden sm:inline">{remuxMutation.isPending || remuxBusy ? "Rebuilding..." : "Re-run Final Output"}</span>
            <span className="sm:hidden">{remuxMutation.isPending || remuxBusy ? "Rebuilding" : "Final Output"}</span>
          </button>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 border-b border-border-hairline bg-[#111111]">
        <VideoPane outputSrc={`${outputUrl}?v=${Math.round(outputVersion)}`} originalAudioSrc={inputUrl} player={player} activeFileName={fileName(activeAudioPath)} />
      </div>
      <footer className="border-t border-border-hairline bg-surface-container-lowest px-4 py-4 sm:px-8 sm:py-5">
        <div className="mb-4 flex items-center gap-4 font-mono text-code-sm text-secondary">
          <span>{formatTime(player.currentTime)}</span>
          <input aria-label="Video timeline" type="range" min={0} max={Math.max(player.duration, 0)} step={0.01} value={player.currentTime} onChange={(e) => player.seek(Number(e.target.value))} className="flex-1 accent-black" />
          <span>{formatTime(player.duration)}</span>
        </div>
        <div className="mb-4 h-5 overflow-hidden rounded-full bg-surface-soft">
          <div className="h-full rounded-full bg-primary" style={{ width: `${progress}%` }} />
        </div>
        <div className="grid grid-cols-1 items-center gap-4 md:grid-cols-3">
          <div className="order-2 inline-flex items-center gap-2 font-mono text-code-sm text-secondary md:order-1"><span className="h-2 w-2 rounded-full bg-status-done" />Single video · audio switch</div>
          <div className="order-1 flex items-center justify-center gap-3 md:order-2">
            <button type="button" aria-label="Seek backward 10 seconds" onClick={() => player.seek(Math.max(0, player.currentTime - 10))} className="flex h-10 w-10 items-center justify-center rounded-full border border-border-hairline bg-surface-soft text-primary"><RotateCcw className="h-4 w-4" /></button>
            <button type="button" aria-label={player.isPlaying ? "Pause video" : "Play video"} onClick={player.toggle} disabled={!outputUrl} className="flex h-14 w-14 items-center justify-center rounded-full bg-primary text-white disabled:bg-surface-container disabled:text-mute">{player.isPlaying ? <Pause className="h-5 w-5" /> : <Play className="h-5 w-5" />}</button>
            <button type="button" aria-label="Seek forward 10 seconds" onClick={() => player.seek(Math.min(player.duration, player.currentTime + 10))} className="flex h-10 w-10 items-center justify-center rounded-full border border-border-hairline bg-surface-soft text-primary"><RotateCw className="h-4 w-4" /></button>
          </div>
          <div className="order-3 flex items-center justify-start gap-3 md:justify-end">
            <AudioToggle value={player.audioMode} inputReady={Boolean(inputUrl)} outputReady={Boolean(outputUrl)} onChange={player.setAudioMode} />
            <button type="button" aria-label="Volume controls" className="flex h-10 w-10 items-center justify-center rounded-full border border-border-hairline bg-surface-soft text-primary"><Volume2 className="h-4 w-4" /></button>
          </div>
        </div>
        <div className="mt-5 flex h-10 overflow-hidden rounded-full bg-surface-soft">
          {Array.from({ length: 18 }).map((_, idx) => <button key={idx} type="button" onClick={() => player.seek((player.duration / 18) * idx)} className={`border-r border-border-hairline ${idx === Math.min(17, Math.floor((progress / 100) * 18)) ? "bg-primary" : "bg-surface-container"}`} style={{ width: `${100 / 18}%` }} aria-label={`Chunk ${idx + 1}`} />)}
        </div>
      </footer>
    </section>
  );
}

type Player = ReturnType<typeof useSyncedPlayback>;

function CompareEmpty({ runId, title, body }: { runId: string; title: string; body: string }) {
  return (
    <section className="min-h-[calc(100vh-56px)] bg-background px-8 py-7">
      <div className="mx-auto max-w-[760px] rounded-[2rem] border border-border-hairline bg-surface-container-lowest p-8 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-surface-soft text-primary"><Film className="h-5 w-5" /></div>
        <p className="mt-5 font-mono text-data-label uppercase text-data-label">Compare Player · {runId}</p>
        <h1 className="mt-2 font-display text-heading-lg text-primary">{title}</h1>
        <p className="mx-auto mt-3 max-w-[560px] text-body-sm text-secondary">{body}</p>
        <div className="mt-6 flex justify-center gap-3">
          <Link to={`/runs/${runId}`} className="inline-flex h-10 items-center gap-2 rounded-full border border-border-hairline bg-surface-soft px-5 text-body-sm-strong text-primary hover:bg-surface-container"><ArrowLeft className="h-4 w-4" />Run Detail</Link>
          <Link to={`/runs/${runId}/chunks`} className="inline-flex h-10 items-center gap-2 rounded-full border border-border-hairline bg-surface-soft px-5 text-body-sm-strong text-primary hover:bg-surface-container"><Edit3 className="h-4 w-4" />Edit Chunks</Link>
          <Link to="/runs/new" className="inline-flex h-10 items-center rounded-full bg-primary px-5 text-body-sm-strong text-white hover:bg-ink-deep">New Run</Link>
        </div>
      </div>
    </section>
  );
}

function VideoPane({ outputSrc, originalAudioSrc, player, activeFileName }: { outputSrc: string; originalAudioSrc: string | null; player: Player; activeFileName: string }) {
  return (
    <div className="relative flex h-full min-h-0 w-full items-center justify-center bg-[#111111]">
      <video key={outputSrc} ref={player.videoRef} src={outputSrc} muted={player.audioMode === "original"} onLoadedMetadata={player.handleLoadedMetadata} onTimeUpdate={player.handleTimeUpdate} onEnded={player.handleEnded} className="h-full max-h-full w-full object-contain" playsInline preload="metadata" />
      <audio ref={player.originalAudioRef} src={originalAudioSrc ?? undefined} preload="auto" onLoadedMetadata={player.handleAudioLoadedMetadata} />
      <div className="absolute left-5 top-5 inline-flex items-center gap-2 rounded-full bg-black/70 px-4 py-2 font-mono text-code-sm text-white"><span className="h-2 w-2 rounded-full bg-status-done" />{player.audioMode} audio</div>
      <div className="absolute right-5 top-5 rounded-full bg-black/60 px-4 py-2 text-body-sm-strong text-white/80">Final Output Preview</div>
      <div className="absolute bottom-5 left-5 max-w-[calc(100%-2.5rem)] truncate rounded-full bg-black/60 px-4 py-2 font-mono text-code-sm text-white/80">{activeFileName}</div>
    </div>
  );
}

function AudioToggle({ value, inputReady, outputReady, onChange }: { value: AudioMode; inputReady: boolean; outputReady: boolean; onChange: (mode: AudioMode) => void }) {
  const modes: { value: AudioMode; label: string; disabled: boolean }[] = [
    { value: "original", label: "Original", disabled: !inputReady },
    { value: "dubbed", label: "Dubbed", disabled: !outputReady },
  ];

  return (
    <div className="flex rounded-full border border-border-hairline bg-surface-soft p-1">
      {modes.map((mode) => (
        <button key={mode.value} type="button" aria-pressed={value === mode.value} aria-label={`Use ${mode.label} audio`} onClick={() => onChange(mode.value)} disabled={mode.disabled} className={`h-8 rounded-full px-4 text-body-sm-strong disabled:text-mute ${value === mode.value ? "bg-white text-primary" : "text-secondary"}`}>{mode.label}</button>
      ))}
    </div>
  );
}

function formatTime(value: number): string {
  if (!Number.isFinite(value)) return "0:00";
  const min = Math.floor(value / 60);
  const sec = Math.floor(value % 60).toString().padStart(2, "0");
  return `${min}:${sec}`;
}
