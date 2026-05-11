// run 진행 상황을 WS 로 받아 react-query 캐시에 머지 + 로그 라인 ring buffer 유지
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { RunRecord, StepState } from "@/api/client";

type WsEvent =
  | { type: "step_start"; step: string; index: number; ts: number }
  | { type: "step_done"; step: string; index: number; ts: number; duration_ms: number }
  | { type: "step_error"; step: string; index: number; ts: number; message?: string }
  | { type: "log"; line: string; ts: number }
  | { type: "heartbeat"; ts: number }
  | { type: "run_started"; ts: number }
  | { type: "run_done"; status: RunRecord["status"]; ts: number; message?: string };

const LOG_BUFFER_MAX = 2000;

export interface UseRunSocketOptions {
  enabled?: boolean;
  onRunDone?: (status: RunRecord["status"]) => void;
}

export function useRunSocket(runId: string | undefined, options: UseRunSocketOptions | boolean = true) {
  const opts = typeof options === "boolean" ? { enabled: options } : options;
  const enabled = opts.enabled ?? true;
  const onRunDoneRef = useRef(opts.onRunDone);
  onRunDoneRef.current = opts.onRunDone;

  const queryClient = useQueryClient();
  const [logLines, setLogLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const reconnectAttempt = useRef(0);

  useEffect(() => {
    if (!runId || !enabled) {
      setConnected(false);
      return;
    }
    let ws: WebSocket | null = null;
    let closed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      // run_done 직후 cleanup이 돌면서 closed=true가 된 다음에도 이미 스케줄된 타이머가 fire 할 수 있음
      if (closed) return;
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${location.host}/api/ws/runs/${runId}`);
      ws.onopen = () => {
        setConnected(true);
        reconnectAttempt.current = 0;
      };
      ws.onclose = () => {
        setConnected(false);
        if (closed) return;
        // 지수 backoff 재연결 (최대 30초)
        const delay = Math.min(30000, 500 * 2 ** reconnectAttempt.current);
        reconnectAttempt.current += 1;
        reconnectTimer = setTimeout(connect, delay);
      };
      ws.onmessage = (msg) => {
        try {
          const event: WsEvent = JSON.parse(msg.data);
          handleEvent(event);
        } catch {
          // 무시 — 잘못된 페이로드
        }
      };
    };

    const handleEvent = (event: WsEvent) => {
      if (event.type === "log") {
        setLogLines((prev) => {
          const next = [...prev, event.line];
          if (next.length > LOG_BUFFER_MAX) next.splice(0, next.length - LOG_BUFFER_MAX);
          return next;
        });
        return;
      }
      if (event.type === "heartbeat" || event.type === "run_started") return;

      if (event.type === "step_start" || event.type === "step_done" || event.type === "step_error") {
        const stateMap: Record<typeof event.type, StepState> = {
          step_start: "running",
          step_done: "done",
          step_error: "failed",
        };
        const newState = stateMap[event.type];
        queryClient.setQueryData<RunRecord>(["run", runId], (old) => {
          if (!old) return old;
          return {
            ...old,
            steps: old.steps.map((s) =>
              s.name === event.step ? { ...s, state: newState, error: event.type === "step_error" ? event.message ?? null : s.error } : s,
            ),
          };
        });
        return;
      }

      if (event.type === "run_done") {
        queryClient.setQueryData<RunRecord>(["run", runId], (old) =>
          old ? { ...old, status: event.status } : old,
        );
        // 최종 상태 + output_video 갱신을 위해 invalidate
        queryClient.invalidateQueries({ queryKey: ["run", runId] });
        // 외부에서 토스트 등 후처리 — 최신 콜백을 ref로 호출 (의존성 없이)
        onRunDoneRef.current?.(event.status);
      }
    };

    connect();
    return () => {
      closed = true;
      if (reconnectTimer != null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      ws?.close();
    };
  }, [runId, enabled, queryClient]);

  return { logLines, connected };
}
