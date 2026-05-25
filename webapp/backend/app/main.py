# FastAPI 앱 — Phase 1a 라우터 + Static 마운트 포함
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from webapp.backend.app.api import projects, runs, uploads, ws

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/workspace/project"))
COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "movie-dubbing-project")
GPU_SERVICES = ("controller", "separator", "diarizer", "speaker", "tts-cosyvoice")

app = FastAPI(title="movie-dubbing webapp", version="0.0.1")

# dev 시 vite proxy 가 아닌 직접 호출도 대비 — localhost 만 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs.router)
app.include_router(projects.router)
app.include_router(uploads.router)
app.include_router(ws.router)


# 산출물 정적 서빙 — wavesurfer/audio/video 가 Range 요청 가능하도록 StaticFiles 사용
def _mount_static(name: str, sub: str) -> None:
    target = PROJECT_ROOT / sub
    target.mkdir(parents=True, exist_ok=True)
    app.mount(f"/static/{name}", StaticFiles(directory=str(target), html=False), name=f"static_{name}")


_mount_static("input", "input")
_mount_static("chunks", "chunks")
_mount_static("dub", "dub")
_mount_static("output", "output")


@app.get("/api/health")
def health() -> dict:
    """docker CLI 통신 + 5개 파이프라인 서비스(controller + separator/diarizer/speaker/tts-cosyvoice) 가동 여부 체크."""
    docker_available = shutil.which("docker") is not None
    services_status: dict[str, str] = {}
    if docker_available:
        try:
            result = subprocess.run(
                ["docker", "compose", "-p", COMPOSE_PROJECT, "ps", "--format", "json"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=10,
            )
            running = result.stdout if result.returncode == 0 else ""
            for service in GPU_SERVICES:
                services_status[service] = "running" if f'"Service":"{service}"' in running else "stopped"
        except (subprocess.TimeoutExpired, OSError) as exc:
            services_status = {service: f"unknown: {exc}" for service in GPU_SERVICES}
    return {
        "status": "ok",
        "docker_cli": docker_available,
        "project_root": str(PROJECT_ROOT),
        "services": services_status,
    }


@app.get("/api/configs")
def list_configs() -> list[dict]:
    """configs/*.json 후보 목록 (runs/ 제외)."""
    configs_dir = PROJECT_ROOT / "configs"
    entries: list[dict] = []
    for path in sorted(configs_dir.glob("*.json")):
        if not path.is_file():
            continue
        entries.append({
            "name": path.name,
            "path": path.relative_to(PROJECT_ROOT).as_posix(),
        })
    return entries
