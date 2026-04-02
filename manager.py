import asyncio
from uuid import uuid4

from fastapi import HTTPException

from models import SessionConfig
from simulation import SessionRuntime


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
