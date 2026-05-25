# 파이프라인 실행 — webapp-backend 컨테이너 안에서 docker compose exec 으로 GPU 서비스 호출
# 각 step 그룹(같은 service 연속 단계)은 한 번의 docker exec 로 처리해 컨테이너 startup 비용 최소화
from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from webapp.backend.app.models import PIPELINE_STEPS, StepName
from webapp.backend.app.services import artifacts, events, run_store
from webapp.backend.app.services.step_router import group_consecutive_by_service, steps_in_range

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/workspace/project"))
COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "movie-dubbing-project")
COMPOSE_FILE = "docker-compose.yml"

# pipeline.py 의 logger format — "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
# message 에 "Starting step: <name>" / "Completed step: <name>" / "Step failed: <name> | <reason>" 가 들어옴
_RE_STEP_START = re.compile(r"Starting step:\s+([a-z_]+)\s*$")
_RE_STEP_DONE = re.compile(r"Completed step:\s+([a-z_]+)\s*$")
_RE_STEP_FAIL = re.compile(r"Step failed:\s+([a-z_]+)\s*\|\s*(.*)$")


class _RunState:
    """현재 활성 run 한 개의 상태 — 모듈 레벨 _ACTIVE 가 단일 인스턴스로 관리."""

    def __init__(self, run_id: str, proc: Optional[asyncio.subprocess.Process] = None) -> None:
        self.run_id = run_id
        self.proc: Optional[asyncio.subprocess.Process] = proc
        self.canceled = False


# 단일 GPU lock — 동시 실행 1개로 강제
_lock = asyncio.Lock()
_ACTIVE: Optional[_RunState] = None


def is_busy() -> Optional[str]:
    """현재 실행 중인 run_id 반환, 없으면 None."""
    return _ACTIVE.run_id if _ACTIVE is not None else None


async def cancel(run_id: str) -> bool:
    """현재 활성 run 이 run_id 면 취소. 성공 True."""
    global _ACTIVE
    if _ACTIVE is None or _ACTIVE.run_id != run_id:
        return False
    _ACTIVE.canceled = True
    proc = _ACTIVE.proc
    if proc is None:
        return True
    # docker compose exec 클라이언트 종료 — 컨테이너 안 python 도 SIGTERM 받음
    try:
        proc.terminate()
    except ProcessLookupError:
        return True
    # 5초 안에 안 끝나면 SIGKILL
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    return True


async def run(run_id: str, *, from_step: StepName = "extract_audio", to_step: StepName = "mux") -> None:
    """단일 run 실행 — _lock 으로 동시 실행 차단, 완료까지 await."""
    global _ACTIVE

    record = run_store.get(run_id)
    if record is None:
        raise ValueError(f"Unknown run_id: {run_id}")

    async with _lock:
        _ACTIVE = _RunState(run_id=run_id)
        try:
            await _execute(record=record, from_step=from_step, to_step=to_step)
        finally:
            _ACTIVE = None


async def _execute(*, record, from_step: StepName, to_step: StepName) -> None:
    run_id = record.run_id
    config_path = record.config_path

    config = artifacts.load_run_config(record)
    pipeline_config = config.get("pipeline") if isinstance(config.get("pipeline"), dict) else {}
    use_separator = bool(pipeline_config.get("use_separator", True))

    requested_steps = steps_in_range(from_step, to_step)
    groups = group_consecutive_by_service(requested_steps, use_separator=use_separator)

    run_store.update_status(run_id, "running")
    events.publish(run_id, {"type": "run_started", "ts": time.time()})

    log_path = Path(record.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fp = log_path.open("a", encoding="utf-8")

    try:
        for service, group_steps in groups:
            if _ACTIVE is not None and _ACTIVE.canceled:
                break
            group_ok = await _run_group(
                run_id=run_id,
                service=service,
                group_steps=group_steps,
                config_path=config_path,
                log_fp=log_fp,
            )
            if not group_ok:
                break
            if "mux" in group_steps:
                _set_output_video_if_ready(run_id, record)
        if _ACTIVE is not None and _ACTIVE.canceled:
            run_store.skip_running_steps(run_id)
            run_store.clear_output_video(run_id)
            run_store.update_status(run_id, "canceled")
            events.publish(run_id, {"type": "run_done", "status": "canceled", "ts": time.time()})
        else:
            updated = run_store.get(run_id)
            failed = updated and any(s.state == "failed" for s in updated.steps)
            final_status = "failed" if failed else "success"
            if final_status == "success":
                _set_output_video_if_ready(run_id, record)
            run_store.update_status(run_id, final_status)
            events.publish(run_id, {"type": "run_done", "status": final_status, "ts": time.time()})
    except Exception as exc:  # noqa: BLE001
        run_store.update_status(run_id, "failed", error=str(exc))
        events.publish(run_id, {"type": "run_done", "status": "failed", "ts": time.time(), "message": str(exc)})
        raise
    finally:
        log_fp.close()


def _set_output_video_if_ready(run_id: str, record) -> None:
    output_video = artifacts.output_video_path(record)
    if output_video:
        run_store.set_output_video(run_id, output_video)


async def _run_group(
    *,
    run_id: str,
    service: str,
    group_steps: list[StepName],
    config_path: str,
    log_fp,
) -> bool:
    """같은 service 연속 단계를 한 번의 docker compose exec 로 실행."""
    from_step = group_steps[0]
    to_step = group_steps[-1]

    cmd = [
        "docker", "compose",
        "-p", COMPOSE_PROJECT,
        "-f", COMPOSE_FILE,
        "exec", "-T",
        service,
        "python", "-u", "src/pipeline.py",
        "--config", config_path,
        "--from-step", from_step,
        "--to-step", to_step,
    ]
    log_fp.write(f"\n[exec {service}] {' '.join(cmd)}\n")
    log_fp.flush()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(PROJECT_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    if _ACTIVE is not None:
        _ACTIVE.proc = proc

    step_start_ts: dict[str, float] = {}

    async def _read() -> None:
        assert proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            log_fp.write(line + "\n")
            log_fp.flush()
            _dispatch_line(run_id=run_id, line=line, step_start_ts=step_start_ts)

    await _read()
    rc = await proc.wait()

    # group 안에서 명시적 fail 이벤트가 없었는데 rc != 0 면 마지막 미완료 step 을 failed 로 마킹
    canceled = _ACTIVE is not None and _ACTIVE.run_id == run_id and _ACTIVE.canceled
    if rc != 0 and not canceled:
        record = run_store.get(run_id)
        if record:
            for step in group_steps:
                entry = next((s for s in record.steps if s.name == step), None)
                if entry and entry.state in ("pending", "running"):
                    run_store.update_step(run_id, step, "failed", error=f"docker exec exit={rc}")
                    events.publish(run_id, {
                        "type": "step_error",
                        "step": step,
                        "index": PIPELINE_STEPS.index(step),
                        "ts": time.time(),
                        "message": f"docker exec exit={rc}",
                    })
                    break

    if canceled:
        return True
    record = run_store.get(run_id)
    return not bool(record and any(step.name in group_steps and step.state == "failed" for step in record.steps))


def _dispatch_line(*, run_id: str, line: str, step_start_ts: dict[str, float]) -> None:
    """파이프라인 stdout 한 줄 해석 → step 이벤트 또는 log 이벤트."""
    now = time.time()

    m = _RE_STEP_START.search(line)
    if m:
        step = m.group(1)
        step_start_ts[step] = now
        run_store.update_step(run_id, step, "running")
        events.publish(run_id, {
            "type": "step_start",
            "step": step,
            "index": PIPELINE_STEPS.index(step) if step in PIPELINE_STEPS else -1,
            "ts": now,
        })
        return

    m = _RE_STEP_DONE.search(line)
    if m:
        step = m.group(1)
        started = step_start_ts.pop(step, now)
        run_store.update_step(run_id, step, "done")
        events.publish(run_id, {
            "type": "step_done",
            "step": step,
            "index": PIPELINE_STEPS.index(step) if step in PIPELINE_STEPS else -1,
            "ts": now,
            "duration_ms": (now - started) * 1000.0,
        })
        return

    m = _RE_STEP_FAIL.search(line)
    if m:
        step = m.group(1)
        message = m.group(2).strip()
        run_store.update_step(run_id, step, "failed", error=message)
        events.publish(run_id, {
            "type": "step_error",
            "step": step,
            "index": PIPELINE_STEPS.index(step) if step in PIPELINE_STEPS else -1,
            "ts": now,
            "message": message,
        })
        return

    # 일반 로그 라인
    events.publish(run_id, {"type": "log", "line": line, "ts": now})


async def heartbeat_loop(run_id: str, interval: float = 15.0) -> None:
    """오래 도는 run (run_tts 등) 동안 WS 무메시지 끊김 방지용 heartbeat."""
    while True:
        await asyncio.sleep(interval)
        if is_busy() != run_id:
            return
        events.publish(run_id, {"type": "heartbeat", "ts": time.time()})


def schedule_run(run_id: str, *, from_step: StepName, to_step: StepName) -> None:
    """API 핸들러에서 fire-and-forget 실행. 단일 lock 이라 두 번째 호출은 await 에서 대기."""
    asyncio.create_task(run(run_id, from_step=from_step, to_step=to_step))
    asyncio.create_task(heartbeat_loop(run_id))
