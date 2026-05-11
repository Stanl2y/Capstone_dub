# Run 메타데이터 영속화 — runs/{run_id}.json 평문 파일 (단일 사용자 가정, SQLite 미사용)
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from webapp.backend.app.models import (
    PIPELINE_STEPS,
    RunRecord,
    RunStatus,
    StepName,
    StepRecord,
    StepState,
)

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/workspace/project"))
RUNS_DIR = PROJECT_ROOT / "runs"
LOG_DIR = PROJECT_ROOT / "logs" / "webapp"


def _ensure_dirs() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def create(*, input_video: str, input_stem: str, config_path: str) -> RunRecord:
    _ensure_dirs()
    run_id = new_run_id()
    record = RunRecord(
        run_id=run_id,
        created_at=time.time(),
        input_video=input_video,
        input_stem=input_stem,
        config_path=config_path,
        status="queued",
        steps=[StepRecord(name=name) for name in PIPELINE_STEPS],
        log_path=str(LOG_DIR / f"{run_id}.log"),
    )
    save(record)
    return record


def save(record: RunRecord) -> None:
    _ensure_dirs()
    path = RUNS_DIR / f"{record.run_id}.json"
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with tmp.open("w", encoding="utf-8") as fp:
        fp.write(record.model_dump_json(indent=2))
    tmp.replace(path)


def get(run_id: str) -> Optional[RunRecord]:
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fp:
        return RunRecord.model_validate_json(fp.read())


def list_runs() -> list[RunRecord]:
    _ensure_dirs()
    out: list[RunRecord] = []
    for path in sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with path.open("r", encoding="utf-8") as fp:
                out.append(RunRecord.model_validate_json(fp.read()))
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def update_status(run_id: str, status: RunStatus, *, error: Optional[str] = None, clear_error: bool = False) -> Optional[RunRecord]:
    record = get(run_id)
    if record is None:
        return None
    prev = record.status
    record.status = status
    if clear_error:
        record.error = None
    elif error is not None:
        record.error = error
    save(record)
    if prev != status:
        # 순환 import 회피 — pipeline_runner / runs 라우터에서 자동으로 호출되는 상태 전이도 audit 에 잡기 위함
        from webapp.backend.app.services import activity
        activity.record(run_id, "status_change", status=status, before=prev, after=status, note=error)
    return record


def update_step(
    run_id: str,
    step: StepName,
    state: StepState,
    *,
    error: Optional[str] = None,
) -> Optional[RunRecord]:
    record = get(run_id)
    if record is None:
        return None
    now = time.time()
    for entry in record.steps:
        if entry.name == step:
            entry.state = state
            if state == "running":
                entry.started_at = now
            elif state in ("done", "failed", "skipped"):
                entry.ended_at = now
                if error is not None:
                    entry.error = error
            break
    save(record)
    return record


def set_output_video(run_id: str, output_video: str) -> Optional[RunRecord]:
    record = get(run_id)
    if record is None:
        return None
    record.output_video = output_video
    save(record)
    return record


def clear_output_video(run_id: str) -> Optional[RunRecord]:
    record = get(run_id)
    if record is None:
        return None
    record.output_video = None
    save(record)
    return record


def skip_running_steps(run_id: str) -> Optional[RunRecord]:
    record = get(run_id)
    if record is None:
        return None
    now = time.time()
    for entry in record.steps:
        if entry.state == "running":
            entry.state = "skipped"
            entry.ended_at = now
            entry.error = None
    save(record)
    return record


def reset_steps(run_id: str, steps: list[StepName]) -> Optional[RunRecord]:
    record = get(run_id)
    if record is None:
        return None
    target_steps = set(steps)
    for entry in record.steps:
        if entry.name not in target_steps:
            continue
        entry.state = "pending"
        entry.started_at = None
        entry.ended_at = None
        entry.error = None
    save(record)
    return record
