# Run 별 변경 이력 (audit log) 을 append-only JSONL 로 영속화
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from webapp.backend.app.models import ActivityEvent, ActivityKind, RunStatus, StepName

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/workspace/project"))
RUNS_DIR = PROJECT_ROOT / "runs"

_TEXT_TRIM = 240  # before/after 가 너무 긴 텍스트면 잘라서 저장 — UI 가 발췌만 보여주면 충분


def _path(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}.events.jsonl"


def _trim(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _TEXT_TRIM:
        return value[:_TEXT_TRIM] + "…"
    return value


def record(
    run_id: str,
    kind: ActivityKind,
    *,
    chunk_id: Optional[str] = None,
    step: Optional[StepName] = None,
    status: Optional[RunStatus] = None,
    before: Any = None,
    after: Any = None,
    note: Optional[str] = None,
) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": time.time(),
        "kind": kind,
        "chunk_id": chunk_id,
        "step": step,
        "status": status,
        "before": _trim(before),
        "after": _trim(after),
        "note": note,
    }
    # None 필드는 제거 — 파일 가독성 + 페이로드 크기
    payload = {k: v for k, v in payload.items() if v is not None}
    with _path(run_id).open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def list_events(run_id: str, *, limit: int = 500) -> list[ActivityEvent]:
    rows = _read_file(_path(run_id), run_id=None)
    rows.reverse()
    return rows[: max(1, min(limit, 2000))]


def list_all_events(*, limit: int = 200) -> list[ActivityEvent]:
    """모든 run 의 events.jsonl 을 시간 역순으로 머지. cross-run feed 용."""
    if not RUNS_DIR.exists():
        return []
    merged: list[ActivityEvent] = []
    for path in RUNS_DIR.glob("*.events.jsonl"):
        # filename: {run_id}.events.jsonl
        run_id = path.name.replace(".events.jsonl", "")
        merged.extend(_read_file(path, run_id=run_id))
    merged.sort(key=lambda e: e.ts, reverse=True)
    return merged[: max(1, min(limit, 2000))]


def _read_file(path: Path, *, run_id: Optional[str]) -> list[ActivityEvent]:
    if not path.exists():
        return []
    rows: list[ActivityEvent] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if run_id is not None:
                data["run_id"] = run_id
            try:
                rows.append(ActivityEvent.model_validate(data))
            except (TypeError, ValueError):
                continue
    return rows
