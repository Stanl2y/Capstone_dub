# /api/uploads — Phase 1 에서는 단순 multipart 스트리밍 + input/ 디렉터리 picker 두 가지 모두 지원
# 큰 파일(100MB+)은 추후 tus-js-client 로 chunked upload 추가
from __future__ import annotations

import os
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, HTTPException, UploadFile

router = APIRouter(prefix="/api", tags=["uploads"])

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/workspace/project"))
INPUT_DIR = PROJECT_ROOT / "input"
ALLOWED_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


@router.post("/uploads")
async def upload_video(file: UploadFile) -> dict:
    """multipart 영상 업로드 — input/{uuid8}_{원래파일명} 으로 저장."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"extension not allowed: {suffix}")

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_stem = Path(file.filename).stem.replace(" ", "_")[:60] or "video"
    out_name = f"{uuid.uuid4().hex[:8]}_{safe_stem}{suffix}"
    out_path = INPUT_DIR / out_name

    async with aiofiles.open(out_path, "wb") as fp:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            await fp.write(chunk)

    rel = out_path.relative_to(PROJECT_ROOT).as_posix()
    return {"input_path": rel, "size_bytes": out_path.stat().st_size}


@router.get("/inputs")
def list_inputs() -> list[dict]:
    """input/ 디렉터리의 영상 파일 목록 — 이미 호스트에 떨어뜨린 파일 picker 용."""
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    for path in sorted(INPUT_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in ALLOWED_EXTS:
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        entries.append({
            "input_path": rel,
            "name": path.name,
            "size_bytes": path.stat().st_size,
        })
    return entries
