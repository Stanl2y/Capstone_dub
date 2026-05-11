# input_stem 단위로 run 들을 동적 그룹핑해 ProjectSummary 로 집계
from __future__ import annotations

from typing import Iterable

from webapp.backend.app.models import ProjectSummary, RunRecord
from webapp.backend.app.services import run_store


def list_projects() -> list[ProjectSummary]:
    runs = run_store.list_runs()
    return _summarize(runs)


def list_project_runs(input_stem: str) -> list[RunRecord]:
    runs = run_store.list_runs()
    filtered = [r for r in runs if r.input_stem == input_stem]
    filtered.sort(key=lambda r: r.created_at, reverse=True)
    return filtered


def _summarize(runs: Iterable[RunRecord]) -> list[ProjectSummary]:
    buckets: dict[str, list[RunRecord]] = {}
    for run in runs:
        buckets.setdefault(run.input_stem, []).append(run)

    summaries: list[ProjectSummary] = []
    for input_stem, group in buckets.items():
        group_sorted = sorted(group, key=lambda r: r.created_at)
        latest = group_sorted[-1]
        success = sum(1 for r in group if r.status == "success")
        failed = sum(1 for r in group if r.status == "failed")
        canceled = sum(1 for r in group if r.status == "canceled")
        summaries.append(ProjectSummary(
            input_stem=input_stem,
            input_video=latest.input_video,
            run_count=len(group),
            success_count=success,
            failed_count=failed,
            canceled_count=canceled,
            last_run_id=latest.run_id,
            last_status=latest.status,
            last_progress_pct=_progress_pct(latest),
            created_at=group_sorted[0].created_at,
            updated_at=latest.created_at,
        ))
    summaries.sort(key=lambda p: p.updated_at, reverse=True)
    return summaries


def _progress_pct(run: RunRecord) -> int:
    if not run.steps:
        return 0
    done = sum(1 for s in run.steps if s.state in ("done", "skipped"))
    return round(done / len(run.steps) * 100)
