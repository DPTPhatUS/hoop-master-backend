from dataclasses import dataclass, field

from pydantic import BaseModel, Field

DEFAULT_THROW_INTERVAL_SECONDS = 10
DEFAULT_SESSION_DURATION_SECONDS = 60
DEFAULT_MAX_POINTS_PER_THROW = 10
DEFAULT_NO_MISTAKE_WEIGHT = 0.3


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
