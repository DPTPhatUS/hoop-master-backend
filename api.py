import asyncio
import time
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from manager import SessionManager
from models import CreateSessionRequest
from simulation import SessionRuntime

manager = SessionManager()
app = FastAPI(title="Hoop Master Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def broadcast_message(runtime: SessionRuntime, payload: dict[str, Any]) -> None:
    stale_clients: list[WebSocket] = []
    for client in runtime.event_clients:
        try:
            await client.send_json(payload)
        except RuntimeError:
            stale_clients.append(client)
    for client in stale_clients:
        runtime.event_clients.discard(client)


async def run_session(runtime: SessionRuntime) -> None:
    try:
        while True:
            await asyncio.sleep(0.25)

            async with runtime.lock:
                if not runtime.state.session_active:
                    break
                events, completed_now = runtime.advance(time.time())

            for event in events:
                await broadcast_message(
                    runtime,
                    {
                        "type": "throw_event",
                        "session_id": runtime.session_id,
                        "data": asdict(event),
                    },
                )

            if completed_now:
                await broadcast_message(
                    runtime,
                    {
                        "type": "session_completed",
                        "session_id": runtime.session_id,
                        "summary": runtime.summary(),
                    },
                )
                break
    finally:
        runtime.runner_task = None


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sessions")
async def create_session(payload: CreateSessionRequest | None = None) -> dict[str, Any]:
    config = payload.config if payload else None
    runtime = await manager.create_session(config=config)
    return runtime.snapshot()


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    runtime = await manager.get_session(session_id)
    async with runtime.lock:
        return runtime.snapshot()


@app.post("/sessions/{session_id}/start")
async def start_session(session_id: str) -> dict[str, Any]:
    runtime = await manager.get_session(session_id)
    async with runtime.lock:
        runtime.start(time.time())
        if runtime.runner_task is None or runtime.runner_task.done():
            runtime.runner_task = asyncio.create_task(run_session(runtime))
        snapshot = runtime.snapshot()

    await broadcast_message(
        runtime,
        {
            "type": "session_started",
            "session_id": runtime.session_id,
            "data": snapshot,
        },
    )
    return snapshot


@app.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str) -> dict[str, Any]:
    runtime = await manager.get_session(session_id)
    async with runtime.lock:
        runtime.stop(time.time())
        snapshot = runtime.snapshot()
        summary = runtime.summary()

    await broadcast_message(
        runtime,
        {
            "type": "session_stopped",
            "session_id": runtime.session_id,
            "summary": summary,
        },
    )
    return snapshot


@app.post("/sessions/{session_id}/reset")
async def reset_session(session_id: str) -> dict[str, Any]:
    runtime = await manager.get_session(session_id)
    async with runtime.lock:
        runtime.reset()
        snapshot = runtime.snapshot()

    await broadcast_message(
        runtime,
        {
            "type": "session_reset",
            "session_id": runtime.session_id,
            "data": snapshot,
        },
    )
    return snapshot


@app.get("/sessions/{session_id}/summary")
async def get_session_summary(session_id: str) -> dict[str, Any]:
    runtime = await manager.get_session(session_id)
    async with runtime.lock:
        return runtime.summary()


@app.websocket("/ws/sessions/{session_id}/events")
async def events_websocket(websocket: WebSocket, session_id: str) -> None:
    runtime = await manager.get_session(session_id)
    await websocket.accept()
    runtime.event_clients.add(websocket)

    try:
        async with runtime.lock:
            await websocket.send_json(
                {
                    "type": "session_state",
                    "session_id": runtime.session_id,
                    "data": runtime.snapshot(),
                }
            )

        while True:
            await websocket.receive()
    except WebSocketDisconnect:
        pass
    finally:
        runtime.event_clients.discard(websocket)


@app.websocket("/ws/sessions/{session_id}/video")
async def video_websocket(websocket: WebSocket, session_id: str) -> None:
    runtime = await manager.get_session(session_id)
    await websocket.accept()

    try:
        while True:
            message = await websocket.receive()
            frame = message.get("bytes")
            if frame is None:
                continue

            async with runtime.lock:
                runtime.last_frame_ts = time.time()
                runtime.last_frame_size = len(frame)
    except WebSocketDisconnect:
        return
