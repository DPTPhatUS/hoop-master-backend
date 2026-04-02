import asyncio
import random
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from typing import Any

from fastapi import WebSocket

from models import SessionConfig, SessionState, ThrowEvent

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
            self.last_frame_ts is not None
            and (now - self.last_frame_ts) <= CAMERA_ACTIVE_WINDOW_SECONDS
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
