# /api/projects — input_stem 단위 가상 그룹 조회 + cross-run activity feed
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from webapp.backend.app.models import ActivityEvent, ProjectSummary, RunRecord
from webapp.backend.app.services import activity, projects as projects_service

router = APIRouter(tags=["projects"])


@router.get("/api/projects", response_model=list[ProjectSummary])
def list_projects() -> list[ProjectSummary]:
    return projects_service.list_projects()


@router.get("/api/projects/{input_stem}/runs", response_model=list[RunRecord])
def get_project_runs(input_stem: str) -> list[RunRecord]:
    rows = projects_service.list_project_runs(input_stem)
    if not rows:
        raise HTTPException(status_code=404, detail=f"no runs for input_stem={input_stem}")
    return rows


@router.get("/api/activity", response_model=list[ActivityEvent])
def list_cross_activity(limit: int = Query(default=200, ge=1, le=2000)) -> list[ActivityEvent]:
    return activity.list_all_events(limit=limit)
