# 단순 pub/sub — run_id 별 asyncio.Queue 구독자 fanout (단일 백엔드 프로세스 가정)
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

# run_id → set of asyncio.Queue
_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
# 누락 이벤트 replay 용 ring buffer — 최근 N개 이벤트만 보관
_buffers: dict[str, list[dict[str, Any]]] = defaultdict(list)
_BUFFER_MAX = 5000


def subscribe(run_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
    _subscribers[run_id].add(queue)
    # 가입 시 그동안 쌓인 버퍼를 즉시 push (page reload 후 진행상황 복구용)
    for ev in _buffers[run_id]:
        try:
            queue.put_nowait(ev)
        except asyncio.QueueFull:
            break
    return queue


def unsubscribe(run_id: str, queue: asyncio.Queue) -> None:
    _subscribers[run_id].discard(queue)
    # 마지막 구독자가 빠졌고 run이 이미 종료된 상태면 ring buffer도 비워 메모리 누수 방지
    if not _subscribers[run_id]:
        buffer = _buffers.get(run_id)
        if buffer and buffer[-1].get("type") == "run_done":
            clear(run_id)


def publish(run_id: str, event: dict[str, Any]) -> None:
    """모든 구독자 큐에 push + ring buffer 갱신. backpressure 무시 (구독자 측 책임)."""
    buffer = _buffers[run_id]
    buffer.append(event)
    if len(buffer) > _BUFFER_MAX:
        del buffer[: len(buffer) - _BUFFER_MAX]
    for queue in list(_subscribers[run_id]):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # 느린 구독자는 잘라낸다 — heartbeat 로 재연결 유도
            continue
    # 구독자가 한 번도 없었던 run의 run_done 은 즉시 정리 — 사용자가 페이지를 안 연 케이스
    if event.get("type") == "run_done" and not _subscribers[run_id]:
        clear(run_id)


def clear(run_id: str) -> None:
    """run 종료 시 메모리 정리."""
    _subscribers.pop(run_id, None)
    _buffers.pop(run_id, None)
