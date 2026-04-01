import json
import random
import time
from collections import Counter
from datetime import datetime

import streamlit as st
from streamlit_autorefresh import st_autorefresh
from streamlit_webrtc import WebRtcMode, webrtc_streamer

THROW_INTERVAL_SECONDS = 10
SESSION_DURATION_SECONDS = 60
MAX_POINTS_PER_THROW = 10
NO_MISTAKE_WEIGHT = 0.35

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

def init_state() -> None:
    defaults = {
        "session_active": False,
        "session_completed": False,
        "session_start_ts": None,
        "session_end_ts": None,
        "next_throw_at": THROW_INTERVAL_SECONDS,
        "throw_events": [],
        "total_points": 0,
        "rng_seed": None,
        "last_spoken_event_idx": 0,
        "mute_audio": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_session() -> None:
    st.session_state.session_active = False
    st.session_state.session_completed = False
    st.session_state.session_start_ts = None
    st.session_state.session_end_ts = None
    st.session_state.next_throw_at = THROW_INTERVAL_SECONDS
    st.session_state.throw_events = []
    st.session_state.total_points = 0
    st.session_state.rng_seed = None
    st.session_state.last_spoken_event_idx = 0


def choose_outcome(throw_idx: int) -> dict:
    rng = random.Random(st.session_state.rng_seed + (throw_idx * 1009))
    if rng.random() < NO_MISTAKE_WEIGHT:
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


def add_throw_event(elapsed_seconds: float) -> None:
    throw_idx = len(st.session_state.throw_events) + 1
    outcome = choose_outcome(throw_idx)
    points = max(0, MAX_POINTS_PER_THROW - outcome["penalty"])
    event = {
        "idx": throw_idx,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "elapsed_s": round(elapsed_seconds, 1),
        "mistake_id": outcome["mistake_id"],
        "mistake_title": outcome["mistake_title"],
        "feedback": outcome["feedback"],
        "target": outcome["target"],
        "points": points,
    }
    st.session_state.throw_events.append(event)
    st.session_state.total_points += points


def maybe_advance_simulation() -> None:
    if not st.session_state.session_active:
        return

    now = time.time()
    elapsed_seconds = now - st.session_state.session_start_ts

    while (
        st.session_state.next_throw_at <= SESSION_DURATION_SECONDS
        and elapsed_seconds >= st.session_state.next_throw_at
    ):
        add_throw_event(st.session_state.next_throw_at)
        st.session_state.next_throw_at += THROW_INTERVAL_SECONDS

    if elapsed_seconds >= SESSION_DURATION_SECONDS:
        st.session_state.session_active = False
        st.session_state.session_completed = True
        st.session_state.session_end_ts = now


def speak_feedback_once(text: str, event_idx: int) -> None:
    safe_text = json.dumps(text)
    html = f"""
    <script>
    const text = {safe_text};
    if ('speechSynthesis' in window) {{
        window.speechSynthesis.cancel();
        const utter = new SpeechSynthesisUtterance(text);
        utter.lang = 'en-US';
        utter.rate = 1.0;
        utter.pitch = 1.0;
        window.speechSynthesis.speak(utter);
    }}
    </script>
    """
    st.html(html, unsafe_allow_javascript=True)
    st.session_state.last_spoken_event_idx = event_idx


def render_summary() -> None:
    events = st.session_state.throw_events
    if not events:
        st.info("No throws recorded in this session.")
        return

    points = [event["points"] for event in events]
    no_mistake_count = sum(1 for event in events if event["mistake_id"] is None)
    mistake_counter = Counter(
        event["mistake_title"] for event in events if event["mistake_id"] is not None
    )
    most_common = mistake_counter.most_common(1)

    st.subheader("Session Summary")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Throws", len(events))
    col2.metric("Total Points", st.session_state.total_points)
    col3.metric("Average Points", f"{st.session_state.total_points / len(events):.2f}")

    col4, col5, col6 = st.columns(3)
    col4.metric("Best Throw", max(points))
    col5.metric("Worst Throw", min(points))
    col6.metric("No-Mistake Rate", f"{(no_mistake_count / len(events)) * 100:.1f}%")

    if most_common:
        st.write(
            f"Most frequent mistake: **{most_common[0][0]}** ({most_common[0][1]} times)"
        )
    else:
        st.write("Most frequent mistake: none")

    st.dataframe(
        [
            {
                "Throw": event["idx"],
                "Time": event["timestamp"],
                "Detected": event["mistake_title"],
                "Target": event["target"],
                "Points": event["points"],
            }
            for event in events
        ],
        width="stretch",
        hide_index=True,
    )


def main() -> None:
    st.set_page_config(page_title="Hoop Master Prototype", layout="wide")
    init_state()

    st.title("Hoop Master: Basketball Throw Form Assistant (Hi-Fi Prototype)")
    st.caption(
        f"Simulation mode: live video capture + randomized feedback every {THROW_INTERVAL_SECONDS} seconds for {SESSION_DURATION_SECONDS} seconds."
    )

    st.session_state.mute_audio = st.toggle(
        "Mute audio feedback", value=st.session_state.mute_audio
    )

    left_col, right_col = st.columns([1.2, 1])
    with left_col:
        st.subheader("Live Camera Feed")
        rtc_ctx = webrtc_streamer(
            key="live-preview",
            mode=WebRtcMode.SENDRECV,
            media_stream_constraints={"video": True, "audio": False},
            async_processing=True,
        )
        camera_live = bool(rtc_ctx and rtc_ctx.state.playing)
        if camera_live:
            st.success("Live camera is active. Perform your throws now.")
        else:
            st.info("Click START in the video box to enable your live camera.")

    control_col1, control_col2, control_col3 = st.columns(3)
    if control_col1.button("Start Session", width="stretch"):
        if not camera_live:
            st.warning("Enable live camera first, then start the session.")
        elif not st.session_state.session_active:
            reset_session()
            st.session_state.session_active = True
            st.session_state.session_start_ts = time.time()
            st.session_state.rng_seed = int(st.session_state.session_start_ts)
            st.rerun()

    if control_col2.button("Stop Session", width="stretch"):
        if st.session_state.session_active:
            st.session_state.session_active = False
            st.session_state.session_completed = True
            st.session_state.session_end_ts = time.time()

    if control_col3.button("Reset", width="stretch"):
        reset_session()

    if st.session_state.session_active:
        st_autorefresh(interval=THROW_INTERVAL_SECONDS * 1000, key="throw_timer")

    maybe_advance_simulation()

    if st.session_state.session_active:
        elapsed = time.time() - st.session_state.session_start_ts
        remaining = max(0, SESSION_DURATION_SECONDS - elapsed)
        st.info(
            f"Session running: throw every {THROW_INTERVAL_SECONDS}s | Remaining time: {remaining:.1f}s"
        )
    elif st.session_state.session_completed:
        st.success("Session completed. Review your summary below.")

    latest_event = st.session_state.throw_events[-1] if st.session_state.throw_events else None

    with left_col:
        st.subheader("Simulated Highlight")
        if latest_event is None:
            st.write("Waiting for throws...")
        elif latest_event["target"] == "GOOD FORM":
            st.success("No issue highlighted for this throw.")
        else:
            st.warning(f"Highlighted target area: {latest_event['target']}")
        st.caption("Highlighting is simulated text guidance for this prototype.")

    with right_col:
        st.subheader("Live Feedback")
        if latest_event is None:
            st.write("Waiting for throws...")
        else:
            if latest_event["mistake_id"] is None:
                st.success(latest_event["feedback"])
            else:
                st.warning(f"{latest_event['mistake_title']}: {latest_event['feedback']}")
            st.write(f"Target area: **{latest_event['target']}**")
            st.write(f"Points this throw: **{latest_event['points']} / {MAX_POINTS_PER_THROW}**")

        throws = len(st.session_state.throw_events)
        avg_points = (
            st.session_state.total_points / throws if throws > 0 else 0
        )
        no_mistake_count = sum(
            1 for event in st.session_state.throw_events if event["mistake_id"] is None
        )

        st.subheader("Running Stats")
        stat_col1, stat_col2 = st.columns(2)
        stat_col1.metric("Throws", throws)
        stat_col2.metric("Total Points", st.session_state.total_points)

        stat_col3, stat_col4 = st.columns(2)
        stat_col3.metric("Average", f"{avg_points:.2f}")
        stat_col4.metric(
            "No-Mistake Rate",
            f"{(no_mistake_count / throws) * 100:.1f}%" if throws > 0 else "0.0%",
        )

        if throws > 0:
            st.write("Recent Throws")
            st.dataframe(
                [
                    {
                        "Throw": event["idx"],
                        "Detected": event["mistake_title"],
                        "Points": event["points"],
                    }
                    for event in st.session_state.throw_events[-5:]
                ],
                hide_index=True,
                width="stretch",
            )

            latest_idx = latest_event["idx"]
            if (
                not st.session_state.mute_audio
                and latest_idx > st.session_state.last_spoken_event_idx
            ):
                speak_feedback_once(latest_event["feedback"], latest_idx)

    if st.session_state.session_completed:
        render_summary()


if __name__ == "__main__":
    main()
