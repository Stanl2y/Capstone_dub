# /api/ws/runs/{run_id} — 실행 중 파이프라인의 step/log/heartbeat 이벤트 push
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from webapp.backend.app.services import events

router = APIRouter(tags=["ws"])


@router.websocket("/api/ws/runs/{run_id}")
async def run_socket(ws: WebSocket, run_id: str) -> None:
    await ws.accept()
    queue = events.subscribe(run_id)
    try:
        while True:
            event = await queue.get()
            await ws.send_text(json.dumps(event, ensure_ascii=False))
            # run_done 이면 잠시 후 종료 (클라이언트가 마지막 메시지 받을 시간)
            if event.get("type") == "run_done":
                await asyncio.sleep(0.1)
                break
    except WebSocketDisconnect:
        pass
    finally:
        events.unsubscribe(run_id, queue)
        try:
            await ws.close()
        except RuntimeError:
            pass
