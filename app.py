import asyncio
import random
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DEFAULT_THROW_INTERVAL_SECONDS = 10
DEFAULT_SESSION_DURATION_SECONDS = 60
DEFAULT_MAX_POINTS_PER_THROW = 10
DEFAULT_NO_MISTAKE_WEIGHT = 0.3
CAMERA_ACTIVE_WINDOW_SECONDS = 3.0

MISTAKES = [
    {
        "id": "elbow_flare",
        "title": "Elbow flares outward",
        "feedback": "Keep your shooting elbow under the ball and aligned to the rim.",
        "target": "ELBOW",
        "penalty": 3,
        "weight": 1.0,
    },
    {
        "id": "guide_hand_interference",
        "title": "Guide hand is pushing the ball",
        "feedback": "Relax your guide hand. It should stabilize, not push the shot.",
        "target": "GUIDE HAND",
        "penalty": 3,
        "weight": 0.9,
    },
    {
        "id": "weak_follow_through",
        "title": "Weak follow-through",
        "feedback": "Snap your wrist and hold your follow-through after release.",
        "target": "WRIST",
        "penalty": 2,
        "weight": 1.0,
    },
    {
        "id": "feet_not_set",
        "title": "Feet are not set",
        "feedback": "Set a stable base with balanced feet before you shoot.",
        "target": "FEET",
        "penalty": 2,
        "weight": 1.0,
    },
    {
        "id": "release_timing",
        "title": "Release timing is off",
        "feedback": "Release at the top of your jump for better control.",
        "target": "RELEASE",
        "penalty": 2,
        "weight": 0.8,
    },
    {
        "id": "flat_arc",
        "title": "Shot arc is too flat",
        "feedback": "Add more arc by extending upward through your shot.",
        "target": "TRAJECTORY",
        "penalty": 2,
        "weight": 0.8,
    },
    {
        "id": "eyes_off_target",
        "title": "Eyes are off the rim",
        "feedback": "Lock your eyes on the target before and during release.",
        "target": "EYES",
        "penalty": 1,
        "weight": 0.7,
    },
    {
        "id": "shoulders_not_square",
        "title": "Shoulders are not square",
        "feedback": "Square your shoulders to the basket to improve alignment.",
        "target": "SHOULDERS",
        "penalty": 2,
        "weight": 0.8,
    },
    {
        "id": "jump_forward",
        "title": "Jumping forward on release",
        "feedback": "Try to land near your takeoff spot to stay balanced.",
        "target": "LANDING",
        "penalty": 2,
        "weight": 0.8,
    },
    {
        "id": "ball_pocket_low",
        "title": "Ball starts too low in pocket",
        "feedback": "Bring the ball smoothly to your shooting pocket near chest-face level.",
        "target": "BALL POCKET",
        "penalty": 1,
        "weight": 0.7,
    },
]


class SessionConfig(BaseModel):
    throw_interval_seconds: int = Field(default=DEFAULT_THROW_INTERVAL_SECONDS, ge=1)
    session_duration_seconds: int = Field(default=DEFAULT_SESSION_DURATION_SECONDS, ge=1)
    max_points_per_throw: int = Field(default=DEFAULT_MAX_POINTS_PER_THROW, ge=1)
    no_mistake_weight: float = Field(default=DEFAULT_NO_MISTAKE_WEIGHT, ge=0.0, le=1.0)


class CreateSessionRequest(BaseModel):
    config: SessionConfig | None = None


@dataclass
class ThrowEvent:
    idx: int
    timestamp: str
    elapsed_s: float
    mistake_id: str | None
    mistake_title: str
    feedback: str
    target: str
    points: int


@dataclass
class SessionState:
    session_active: bool = False
    session_completed: bool = False
    session_start_ts: float | None = None
    session_end_ts: float | None = None
    next_throw_at: float = DEFAULT_THROW_INTERVAL_SECONDS
    throw_events: list[ThrowEvent] = field(default_factory=list)
    total_points: int = 0
    rng_seed: int | None = None


class SessionRuntime:
    def __init__(self, session_id: str, config: SessionConfig):
        self.session_id = session_id
        self.config = config
        self.state = SessionState(next_throw_at=config.throw_interval_seconds)
        self.lock = asyncio.Lock()
        self.event_clients: set[WebSocket] = set()
        self.runner_task: asyncio.Task[None] | None = None
        self.last_frame_ts: float | None = None
        self.last_frame_size: int | None = None

    def reset(self) -> None:
        self.state = SessionState(next_throw_at=self.config.throw_interval_seconds)

    def start(self, now: float) -> None:
        self.reset()
        self.state.session_active = True
        self.state.session_start_ts = now
        self.state.rng_seed = int(now)

    def stop(self, now: float) -> None:
        self.state.session_active = False
        self.state.session_completed = True
        self.state.session_end_ts = now

    def choose_outcome(self, throw_idx: int) -> dict[str, Any]:
        if self.state.rng_seed is None:
            raise RuntimeError("Session seed is missing")

        rng = random.Random(self.state.rng_seed + (throw_idx * 1009))
        if rng.random() < self.config.no_mistake_weight:
            return {
                "mistake_id": None,
                "mistake_title": "No mistake detected",
                "feedback": "Great form. Keep this same rhythm and follow-through.",
                "target": "GOOD FORM",
                "penalty": 0,
            }

        weights = [mistake["weight"] for mistake in MISTAKES]
        choice = rng.choices(MISTAKES, weights=weights, k=1)[0]
        return {
            "mistake_id": choice["id"],
            "mistake_title": choice["title"],
            "feedback": choice["feedback"],
            "target": choice["target"],
            "penalty": choice["penalty"],
        }

    def add_throw_event(self, elapsed_seconds: float) -> ThrowEvent:
        throw_idx = len(self.state.throw_events) + 1
        outcome = self.choose_outcome(throw_idx)
        points = max(0, self.config.max_points_per_throw - outcome["penalty"])
        event = ThrowEvent(
            idx=throw_idx,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            elapsed_s=round(elapsed_seconds, 1),
            mistake_id=outcome["mistake_id"],
            mistake_title=outcome["mistake_title"],
            feedback=outcome["feedback"],
            target=outcome["target"],
            points=points,
        )
        self.state.throw_events.append(event)
        self.state.total_points += points
        return event

    def advance(self, now: float) -> tuple[list[ThrowEvent], bool]:
        if not self.state.session_active or self.state.session_start_ts is None:
            return [], False

        elapsed_seconds = now - self.state.session_start_ts
        new_events: list[ThrowEvent] = []

        while (
            self.state.next_throw_at <= self.config.session_duration_seconds
            and elapsed_seconds >= self.state.next_throw_at
        ):
            new_events.append(self.add_throw_event(self.state.next_throw_at))
            self.state.next_throw_at += self.config.throw_interval_seconds

        completed_now = False
        if elapsed_seconds >= self.config.session_duration_seconds:
            self.state.session_active = False
            self.state.session_completed = True
            self.state.session_end_ts = now
            completed_now = True

        return new_events, completed_now

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        remaining = 0.0
        if self.state.session_active and self.state.session_start_ts is not None:
            elapsed = now - self.state.session_start_ts
            remaining = max(0.0, self.config.session_duration_seconds - elapsed)

        camera_connected = (
            self.last_frame_ts is not None and (now - self.last_frame_ts) <= CAMERA_ACTIVE_WINDOW_SECONDS
        )

        return {
            "session_id": self.session_id,
            "config": self.config.model_dump(),
            "state": {
                "session_active": self.state.session_active,
                "session_completed": self.state.session_completed,
                "session_start_ts": self.state.session_start_ts,
                "session_end_ts": self.state.session_end_ts,
                "next_throw_at": self.state.next_throw_at,
                "remaining_seconds": round(remaining, 2),
                "throw_events": [asdict(event) for event in self.state.throw_events],
                "total_points": self.state.total_points,
                "throws": len(self.state.throw_events),
            },
            "camera": {
                "connected": camera_connected,
                "last_frame_ts": self.last_frame_ts,
                "last_frame_size": self.last_frame_size,
            },
        }

    def summary(self) -> dict[str, Any]:
        events = self.state.throw_events
        if not events:
            return {
                "session_id": self.session_id,
                "total_throws": 0,
                "total_points": 0,
                "average_points": 0.0,
                "best_throw": 0,
                "worst_throw": 0,
                "no_mistake_rate": 0.0,
                "most_frequent_mistake": None,
            }

        points = [event.points for event in events]
        no_mistake_count = sum(1 for event in events if event.mistake_id is None)
        mistake_counter = Counter(
            event.mistake_title for event in events if event.mistake_id is not None
        )
        most_common = mistake_counter.most_common(1)

        return {
            "session_id": self.session_id,
            "total_throws": len(events),
            "total_points": self.state.total_points,
            "average_points": round(self.state.total_points / len(events), 2),
            "best_throw": max(points),
            "worst_throw": min(points),
            "no_mistake_rate": round((no_mistake_count / len(events)) * 100, 1),
            "most_frequent_mistake": {
                "title": most_common[0][0],
                "count": most_common[0][1],
            }
            if most_common
            else None,
        }


class SessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionRuntime] = {}
        self._lock = asyncio.Lock()

    async def create_session(self, config: SessionConfig | None = None) -> SessionRuntime:
        session_id = uuid4().hex
        runtime = SessionRuntime(session_id=session_id, config=config or SessionConfig())
        async with self._lock:
            self.sessions[session_id] = runtime
        return runtime

    async def get_session(self, session_id: str) -> SessionRuntime:
        runtime = self.sessions.get(session_id)
        if runtime is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return runtime


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
