# Hoop Master (Hi-Fi Prototype)

This project simulates a basketball throw form assistant for user-system interaction testing.
It is intentionally a prototype workflow (not real pose estimation).

## What It Simulates

1. Live camera capture of user shooting form (video stream).
2. Predefined common shooting-form mistakes.
3. Live processing simulation every 3 seconds with randomized outcomes:
	- A detected mistake, or
	- No mistake detected.
4. Audio feedback via text-to-speech (browser speech synthesis).
5. Per-throw points for each randomized outcome.
6. End-of-session summary after 30 seconds with throw counts and statistics.

## Tech Stack

- Python 3.11+
- Streamlit
- streamlit-autorefresh
- streamlit-webrtc
- uv for package management and execution

## Run With uv

From the project root:

```bash
uv sync
uv run streamlit run app.py
```

Then open the local Streamlit URL in your browser.

## Demo Flow

1. Turn on webcam live stream by clicking START in the video panel.
2. Click Start Session.
3. The app creates one simulated throw event every 3 seconds while you perform throws.
4. Each event shows:
	- Detected issue (or no issue),
	- Coaching feedback text,
	- Simulated highlighted target area,
	- Points for that throw.
5. Audio feedback is spoken for each new throw unless Mute is enabled.
6. At 30 seconds, session ends and summary metrics are shown.

## Notes

- Highlighted mistake regions are simulated guidance and not computer vision output.
- Browser permission is required for camera access.
- Browser support is required for the Web Speech API used for text-to-speech.
