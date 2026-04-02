# Hoop Master Backend API Documentation

## Purpose
This document defines the HTTP and WebSocket contract for the Hoop Master backend.

The backend is a simulation service:
- Frontend streams camera frames to the backend.
- Backend emits timed, simulated throw feedback events.
- Outcomes are randomized from a predefined mistake catalog.

## Base URL
Local development default:

```text
http://127.0.0.1:8000
```

## Runtime Characteristics
- Storage: in-memory only (sessions are lost on server restart).
- CORS: currently permissive (`*`) for all origins, methods, and headers.
- Timing defaults:
  - `throw_interval_seconds`: `10`
  - `session_duration_seconds`: `60`
- Video influence: uploaded frames are currently used only for camera activity metadata, not feedback generation.

## Data Models

### SessionConfig
```json
{
  "throw_interval_seconds": 10,
  "session_duration_seconds": 60,
  "max_points_per_throw": 10,
  "no_mistake_weight": 0.3
}
```

Field constraints:
- `throw_interval_seconds`: integer, `>= 1`
- `session_duration_seconds`: integer, `>= 1`
- `max_points_per_throw`: integer, `>= 1`
- `no_mistake_weight`: float, `0.0 <= value <= 1.0`

### ThrowEvent
```json
{
  "idx": 1,
  "timestamp": "13:05:21",
  "elapsed_s": 10.0,
  "mistake_id": "elbow_flare",
  "mistake_title": "Elbow flares outward",
  "feedback": "Keep your shooting elbow under the ball and aligned to the rim.",
  "target": "ELBOW",
  "points": 7
}
```

Notes:
- If no mistake is detected:
  - `mistake_id` is `null`
  - `mistake_title` is `No mistake detected`
  - `target` is `GOOD FORM`

### SessionSnapshot (response shape used by most REST endpoints)
```json
{
  "session_id": "8d7d90f2a4f740c18f3f83f9f5f7f7f1",
  "config": {
    "throw_interval_seconds": 10,
    "session_duration_seconds": 60,
    "max_points_per_throw": 10,
    "no_mistake_weight": 0.3
  },
  "state": {
    "session_active": false,
    "session_completed": false,
    "session_start_ts": null,
    "session_end_ts": null,
    "next_throw_at": 10,
    "remaining_seconds": 0.0,
    "throw_events": [],
    "total_points": 0,
    "throws": 0
  },
  "camera": {
    "connected": false,
    "last_frame_ts": null,
    "last_frame_size": null
  }
}
```

### Summary
```json
{
  "session_id": "8d7d90f2a4f740c18f3f83f9f5f7f7f1",
  "total_throws": 6,
  "total_points": 45,
  "average_points": 7.5,
  "best_throw": 10,
  "worst_throw": 6,
  "no_mistake_rate": 33.3,
  "most_frequent_mistake": {
    "title": "Elbow flares outward",
    "count": 2
  }
}
```

If no throws were recorded:
- `total_throws = 0`
- `most_frequent_mistake = null`

## HTTP API

### 1. Health Check
- Method: `GET`
- Path: `/health`
- Description: Basic liveness endpoint.

Response example:
```json
{
  "status": "ok"
}
```

### 2. Create Session
- Method: `POST`
- Path: `/sessions`
- Description: Creates a new session with optional config override.

Request body (optional):
```json
{
  "config": {
    "throw_interval_seconds": 5,
    "session_duration_seconds": 30,
    "max_points_per_throw": 10,
    "no_mistake_weight": 0.25
  }
}
```

Response:
- Returns a `SessionSnapshot`.

Example:
```bash
curl -X POST http://127.0.0.1:8000/sessions \
  -H 'Content-Type: application/json' \
  -d '{"config":{"throw_interval_seconds":5,"session_duration_seconds":30,"max_points_per_throw":10,"no_mistake_weight":0.25}}'
```

### 3. Get Session State
- Method: `GET`
- Path: `/sessions/{session_id}`
- Description: Returns latest session snapshot including camera metadata and all throw events.

Response:
- Returns a `SessionSnapshot`.

Example:
```bash
curl http://127.0.0.1:8000/sessions/<session_id>
```

### 4. Start Session
- Method: `POST`
- Path: `/sessions/{session_id}/start`
- Description: Resets and starts simulation timer for the session.

Behavior:
- Session state is reset before start.
- A background task begins producing throw events at configured intervals.
- A websocket event message with type `session_started` is broadcast to event subscribers.

Response:
- Returns a fresh `SessionSnapshot`.

Example:
```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/start
```

### 5. Stop Session
- Method: `POST`
- Path: `/sessions/{session_id}/stop`
- Description: Marks session as completed immediately.

Behavior:
- Sets `session_active = false`, `session_completed = true`.
- Broadcasts websocket message `session_stopped` with a summary payload.

Response:
- Returns current `SessionSnapshot`.

Example:
```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/stop
```

### 6. Reset Session
- Method: `POST`
- Path: `/sessions/{session_id}/reset`
- Description: Clears session state and throw history.

Behavior:
- Clears events and points.
- Broadcasts websocket message `session_reset`.

Response:
- Returns reset `SessionSnapshot`.

Example:
```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/reset
```

### 7. Get Session Summary
- Method: `GET`
- Path: `/sessions/{session_id}/summary`
- Description: Returns summary metrics derived from throw events.

Response:
- Returns a `Summary` object.

Example:
```bash
curl http://127.0.0.1:8000/sessions/<session_id>/summary
```

## WebSocket API

## Event Stream
- URL: `ws://127.0.0.1:8000/ws/sessions/{session_id}/events`
- Direction: primarily server -> client JSON messages.
- On connection: server immediately sends one `session_state` message with current snapshot.

### Event message envelope
```json
{
  "type": "throw_event",
  "session_id": "<session_id>",
  "data": { }
}
```

### Event types and payloads
1. `session_state`
- Sent on websocket connect.
- Payload field: `data` -> `SessionSnapshot`

2. `session_started`
- Sent after `POST /sessions/{id}/start`.
- Payload field: `data` -> `SessionSnapshot`

3. `throw_event`
- Sent each time a simulated throw is produced.
- Payload field: `data` -> `ThrowEvent`

4. `session_completed`
- Sent when configured duration is reached naturally.
- Payload field: `summary` -> `Summary`

5. `session_stopped`
- Sent after explicit stop.
- Payload field: `summary` -> `Summary`

6. `session_reset`
- Sent after reset.
- Payload field: `data` -> `SessionSnapshot`

### Frontend handling guidance
- Treat websocket as authoritative for live updates.
- Use `GET /sessions/{id}` for initial fetch or recovery after disconnect.
- Reconnect strategy: exponential backoff and state refresh after reconnect.

## Video Upload Stream
- URL: `ws://127.0.0.1:8000/ws/sessions/{session_id}/video`
- Direction: client -> server.
- Expected payload: binary frames (`bytes`), typically JPEG/PNG blobs.

Behavior:
- For each received binary frame, backend updates:
  - `camera.last_frame_ts`
  - `camera.last_frame_size`
- `camera.connected` in snapshots is true when the last frame was received within approximately 3 seconds.

Notes:
- Text websocket messages are ignored by video processing logic.
- Backend does not return processed frames on this socket.

## End-to-End Recommended Flow
1. Create session (`POST /sessions`).
2. Connect event websocket (`/ws/sessions/{id}/events`).
3. Connect video websocket (`/ws/sessions/{id}/video`) and begin sending binary frames.
4. Start session (`POST /sessions/{id}/start`).
5. Render each incoming `throw_event`.
6. On completion or stop, use summary event or `GET /sessions/{id}/summary`.

## Error Handling

### Not Found
If `session_id` does not exist in REST or websocket setup phase:
- HTTP status: `404`
- Body:
```json
{
  "detail": "Session not found"
}
```

### Validation Errors
Invalid request body values (for example out-of-range config fields):
- HTTP status: `422`
- Body: standard FastAPI/Pydantic validation error format.

### WebSocket Disconnects
- Backend silently removes disconnected event clients.
- Frontend should reconnect and refetch session state.

## Practical Examples

### Create + Start (bash)
```bash
SESSION_ID=$(curl -sS -X POST http://127.0.0.1:8000/sessions | jq -r '.session_id')
curl -sS -X POST http://127.0.0.1:8000/sessions/$SESSION_ID/start
```

### Event socket listener (browser JavaScript)
```javascript
const sessionId = "<session_id>";
const eventWs = new WebSocket(`ws://127.0.0.1:8000/ws/sessions/${sessionId}/events`);

eventWs.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  switch (msg.type) {
    case "session_state":
    case "session_started":
    case "session_reset":
      console.log("snapshot", msg.data);
      break;
    case "throw_event":
      console.log("throw", msg.data);
      break;
    case "session_completed":
    case "session_stopped":
      console.log("summary", msg.summary);
      break;
    default:
      console.log("unknown", msg);
  }
};
```

### Video frame streaming sketch (browser JavaScript)
```javascript
const videoWs = new WebSocket(`ws://127.0.0.1:8000/ws/sessions/${sessionId}/video`);
videoWs.binaryType = "arraybuffer";

async function sendFrameFromCanvas(canvas) {
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.75));
  if (!blob || videoWs.readyState !== WebSocket.OPEN) return;
  const frameBytes = await blob.arrayBuffer();
  videoWs.send(frameBytes);
}
```

## Versioning and Compatibility
- Current API is unversioned.
- If breaking changes are planned, consider introducing `/v1` route prefix and freezing current contract.

## Security Notes
Current backend is prototype-oriented:
- No authentication or authorization.
- Open CORS policy.
- In-memory state only.

For production-like deployment, add:
- Auth token checks.
- Restricted CORS origins.
- Rate limits for websocket and frame throughput.
- Persistent session storage.
