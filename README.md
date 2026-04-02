# Hoop Master Backend Simulation

This project now runs as a backend-only simulation service.
It accepts camera frames from any frontend and emits simulated basketball throw feedback events.

The simulation behavior is still prototype logic (not real pose estimation): outcomes are randomized from predefined mistake patterns.

## What The Backend Provides

1. Session lifecycle APIs (create, start, stop, reset).
2. Timed throw simulation events (default every 10 seconds for a 60-second session).
3. Per-throw scoring and feedback text.
4. Session summary statistics.
5. Camera ingest endpoint (WebSocket binary frames).

## Tech Stack

- Python 3.11+
- FastAPI
- Uvicorn
- uv for package management and execution

## Run With uv

From the project root:

```bash
uv sync
uv run uvicorn app:app --reload
```

Then open http://127.0.0.1:8000/docs for interactive API docs.

## Code Structure

- `app.py`: thin ASGI entrypoint (`from api import app`).
- `api.py`: FastAPI routes, websocket handlers, and event broadcasting loop.
- `manager.py`: in-memory session registry and lookup/create helpers.
- `models.py`: Pydantic request models and dataclasses for session state/events.
- `simulation.py`: simulation runtime logic, outcomes, scoring, snapshots, and summaries.

## API Overview

### Health

- `GET /health`

### Session REST Endpoints

- `POST /sessions`
- `GET /sessions/{session_id}`
- `POST /sessions/{session_id}/start`
- `POST /sessions/{session_id}/stop`
- `POST /sessions/{session_id}/reset`
- `GET /sessions/{session_id}/summary`

### WebSocket Endpoints

- `WS /ws/sessions/{session_id}/events`
	- Server pushes JSON messages:
		- `session_state` (on connect)
		- `session_started`
		- `throw_event`
		- `session_completed`
		- `session_stopped`
		- `session_reset`
- `WS /ws/sessions/{session_id}/video`
	- Frontend sends binary frame blobs (JPEG/PNG bytes).
	- Backend tracks camera activity metadata only.

## Minimal Frontend Flow

1. `POST /sessions` to create a session.
2. Connect to `WS /ws/sessions/{session_id}/events` to receive feedback.
3. Connect to `WS /ws/sessions/{session_id}/video` and stream frames.
4. `POST /sessions/{session_id}/start` to begin simulation.
5. Render feedback from incoming `throw_event` JSON messages.

## Notes

- Video frames do not currently influence simulation outcomes.
- This service stores sessions in memory only.
- Browser TTS and UI rendering belong to the frontend.
