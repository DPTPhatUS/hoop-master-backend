import io
import json
import random
import time
from collections import Counter
from datetime import datetime

import streamlit as st
from PIL import Image, ImageDraw
from streamlit_autorefresh import st_autorefresh

THROW_INTERVAL_SECONDS = 3
SESSION_DURATION_SECONDS = 30
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

TARGET_BOXES = {
    "EYES": (0.42, 0.08, 0.58, 0.2),
    "SHOULDERS": (0.3, 0.22, 0.7, 0.38),
    "ELBOW": (0.55, 0.32, 0.75, 0.55),
    "GUIDE HAND": (0.28, 0.3, 0.48, 0.56),
    "WRIST": (0.6, 0.45, 0.78, 0.68),
    "BALL POCKET": (0.42, 0.3, 0.62, 0.5),
    "RELEASE": (0.45, 0.02, 0.72, 0.24),
    "TRAJECTORY": (0.15, 0.02, 0.85, 0.25),
    "FEET": (0.3, 0.74, 0.72, 0.98),
    "LANDING": (0.18, 0.74, 0.85, 0.98),
}


def init_state() -> None:
    defaults = {
        "captured_image": None,
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


def draw_target_box(image_bytes: bytes, target: str) -> Image.Image:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)

    box = TARGET_BOXES.get(target)
    if not box:
        return image

    width, height = image.size
    x1 = int(box[0] * width)
    y1 = int(box[1] * height)
    x2 = int(box[2] * width)
    y2 = int(box[3] * height)

    draw.rectangle([x1, y1, x2, y2], outline="red", width=max(3, width // 150))
    draw.rectangle([x1, max(0, y1 - 28), x1 + 180, y1], fill="red")
    draw.text((x1 + 8, max(0, y1 - 24)), f"SIMULATED: {target}", fill="white")
    return image


def speak_feedback_once(text: str, event_idx: int) -> None:
    safe_text = json.dumps(text)
    script = f"""
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
    st.components.v1.html(script, height=0)
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
        use_container_width=True,
        hide_index=True,
    )


def main() -> None:
    st.set_page_config(page_title="Hoop Master Prototype", layout="wide")
    init_state()

    st.title("Hoop Master: Basketball Throw Form Assistant (Hi-Fi Prototype)")
    st.caption(
        "Simulation mode: camera still image capture + randomized feedback every 3 seconds for 30 seconds."
    )

    st.session_state.mute_audio = st.toggle(
        "Mute audio feedback", value=st.session_state.mute_audio
    )

    if st.session_state.session_active:
        st_autorefresh(interval=THROW_INTERVAL_SECONDS * 1000, key="throw_timer")

    maybe_advance_simulation()

    camera_file = st.camera_input("Capture your current shooting form")
    if camera_file is not None:
        st.session_state.captured_image = camera_file.getvalue()

    control_col1, control_col2, control_col3 = st.columns(3)
    if control_col1.button("Start Session", use_container_width=True):
        if st.session_state.captured_image is None:
            st.warning("Please capture a form image before starting the session.")
        elif not st.session_state.session_active:
            reset_session()
            st.session_state.session_active = True
            st.session_state.session_start_ts = time.time()
            st.session_state.rng_seed = int(st.session_state.session_start_ts)

    if control_col2.button("Stop Session", use_container_width=True):
        if st.session_state.session_active:
            st.session_state.session_active = False
            st.session_state.session_completed = True
            st.session_state.session_end_ts = time.time()

    if control_col3.button("Reset", use_container_width=True):
        reset_session()

    if st.session_state.session_active:
        elapsed = time.time() - st.session_state.session_start_ts
        remaining = max(0, SESSION_DURATION_SECONDS - elapsed)
        st.info(
            f"Session running: throw every {THROW_INTERVAL_SECONDS}s | Remaining time: {remaining:.1f}s"
        )
    elif st.session_state.session_completed:
        st.success("Session completed. Review your summary below.")

    left_col, right_col = st.columns([1.2, 1])

    with left_col:
        st.subheader("Captured Form")
        latest_event = (
            st.session_state.throw_events[-1] if st.session_state.throw_events else None
        )
        if st.session_state.captured_image is None:
            st.write("No captured image yet.")
        elif latest_event is None or latest_event["target"] == "GOOD FORM":
            st.image(st.session_state.captured_image, use_container_width=True)
            st.caption("No highlight currently shown.")
        else:
            highlighted = draw_target_box(
                st.session_state.captured_image, latest_event["target"]
            )
            st.image(highlighted, use_container_width=True)
            st.caption("Highlight is simulated for prototype demonstration.")

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
                use_container_width=True,
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
