#!/usr/bin/env python3
"""
SKILLOR Analytics Dashboard
----------------------------
Streamlit dashboard for the Mr. Nextep / SKILLOR channel.
Reads data/*.json files and displays a comprehensive operator view.

Run:  streamlit run scripts/dashboard.py
Install: pip install streamlit pandas plotly
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="SKILLOR Dashboard",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_DIR = Path(os.environ.get("SKILLOR_DATA_DIR", "data"))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    """Safely load a JSON file."""
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        st.warning(f"Could not load {path.name}: {e}")
    return {}


def platform_status_icon(status: str) -> str:
    icons = {
        "healthy": "🟢",
        "below_gate": "🟡",
        "critical": "🔴",
        "no_data": "⚪",
    }
    return icons.get(status, "⚪")


def format_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def format_int(value: Optional[int]) -> str:
    if value is None:
        return "—"
    return f"{value:,}"


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

growth_state = load_json(DATA_DIR / "growth_state.json")
video_history = load_json(DATA_DIR / "video_history.json")
platform_metrics = load_json(DATA_DIR / "platform_metrics.json")
upload_state = load_json(DATA_DIR / "upload_state.json")
fb_analytics = load_json(DATA_DIR / "facebook_analytics.json")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("🧬 SKILLOR Dashboard")
st.sidebar.caption("Mr. Nextep — Body Science Shorts")

st.sidebar.markdown("---")

# Last updated
gen_time = growth_state.get("generated_at", "")
if gen_time:
    st.sidebar.metric("Last Updated", gen_time[:19].replace("T", " "))
else:
    st.sidebar.warning("No growth state yet")

st.sidebar.markdown("---")

# Quick stats
total_videos = len(video_history) if isinstance(video_history, list) else "?"
st.sidebar.metric("Total Videos", total_videos)

youtube_uploads = sum(
    1 for v in (video_history if isinstance(video_history, list) else [])
    if v.get("youtube_id")
)
st.sidebar.metric("YouTube Uploads", youtube_uploads)

fb_uploads = len(upload_state.get("facebook_reels", {})) if upload_state else 0
st.sidebar.metric("Facebook Reels", fb_uploads or "?")

st.sidebar.markdown("---")

# Cadence
cadence = growth_state.get("recommended_cadence", "?")
st.sidebar.metric("Recommended Cadence", f"{cadence}/day")
cadence_reason = growth_state.get("cadence_reason", "")
if cadence_reason:
    st.sidebar.caption(cadence_reason[:120] + "...")

st.sidebar.markdown("---")
st.sidebar.caption("[GitHub Repo](https://github.com/jashaidaslamhfd/Mr-Nextep)")
st.sidebar.caption(f"Policy: {growth_state.get('_policy_version', '?')}")

# ---------------------------------------------------------------------------
# Main Content
# ---------------------------------------------------------------------------

st.title("🧬 SKILLOR — Mr. Nextep Analytics")

# ---- Row 1: Platform Health Cards ----
st.subheader("Platform Health")

ph = growth_state.get("platform_health", {})
cols = st.columns(3)

platform_labels = {
    "youtube_shorts": ("YouTube Shorts", "▶️"),
    "facebook_reels": ("Facebook Reels", "📘"),
    "instagram_reels": ("Instagram Reels", "📸"),
}

for i, (key, (label, emoji)) in enumerate(platform_labels.items()):
    data = ph.get(key, {})
    with cols[i]:
        status = data.get("status", "no_data")
        icon = platform_status_icon(status)
        gate_ratio = data.get("gate_ratio")
        
        st.metric(
            f"{icon} {label}",
            f"{data.get('samples', 0)} videos",
        )
        
        completion = data.get("avg_completion")
        gate = data.get("gate")
        if completion and gate:
            st.progress(
                min(completion / gate, 1.5),
                text=f"Completion: {format_pct(completion)} / Gate: {format_pct(gate)}",
            )
        
        avg_views = data.get("avg_views")
        if avg_views:
            st.caption(f"Avg Views: {format_int(int(avg_views))}")
        
        action = data.get("action", "")
        if action:
            st.caption(action[:100] + "...")

# ---- Row 2: Slot Performance ----
st.markdown("---")
st.subheader("📅 Publish Slot Performance")

slot_weights = growth_state.get("slot_weights", {})
slot_samples = growth_state.get("slot_samples", {})

if slot_weights:
    # Sort by weight descending
    sorted_slots = sorted(slot_weights.items(), key=lambda x: x[1], reverse=True)
    
    fig = go.Figure()
    
    slots = [s[0] for s in sorted_slots]
    weights = [s[1] for s in sorted_slots]
    samples = [slot_samples.get(s[0], 0) for s in sorted_slots]
    
    # Color: green if above neutral (1.0), yellow if below
    colors = ["#2ecc71" if w >= 1.0 else "#e67e22" for w in weights]
    
    fig.add_trace(go.Bar(
        x=slots,
        y=weights,
        text=[f"{w:.2f} ({n}v)" for w, n in zip(weights, samples)],
        textposition="outside",
        marker_color=colors,
        name="Slot Weight",
    ))
    
    fig.add_hline(y=1.0, line_dash="dash", line_color="gray", 
                  annotation_text="Neutral (1.0)")
    
    fig.update_layout(
        height=350,
        margin=dict(l=20, r=20, t=30, b=20),
        xaxis_title="Publish Slot (NY Time)",
        yaxis_title="Weight",
        yaxis=dict(range=[0.3, 1.6]),
    )
    
    st.plotly_chart(fig, use_container_width=True)

# ---- Row 3: Topic & Hook Performance ----
col1, col2 = st.columns(2)

with col1:
    st.subheader("🧠 Topic Pillar Weights")
    topic_weights = growth_state.get("topic_weights", {})
    topic_samples = growth_state.get("topic_samples", {})
    
    if topic_weights:
        sorted_topics = sorted(topic_weights.items(), key=lambda x: x[1], reverse=True)
        df_topics = pd.DataFrame([
            {"Topic": t, "Weight": w, "Videos": topic_samples.get(t, 0)}
            for t, w in sorted_topics
        ])
        
        fig = px.bar(
            df_topics, x="Topic", y="Weight",
            text=df_topics.apply(lambda r: f"{r['Weight']:.2f} ({r['Videos']}v)", axis=1),
            color="Weight",
            color_continuous_scale="RdYlGn",
        )
        fig.add_hline(y=1.0, line_dash="dash", line_color="gray")
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=10, b=20))
        st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("🪝 Hook Style Performance")
    hook_weights = growth_state.get("hook_weights", {})
    hook_samples = growth_state.get("hook_samples", {})
    
    if hook_weights:
        sorted_hooks = sorted(hook_weights.items(), key=lambda x: x[1], reverse=True)
        df_hooks = pd.DataFrame([
            {"Hook Pattern": h, "Weight": w, "Videos": hook_samples.get(h, 0)}
            for h, w in sorted_hooks
        ])
        
        fig = px.bar(
            df_hooks, x="Hook Pattern", y="Weight",
            text=df_hooks.apply(lambda r: f"{r['Weight']:.2f} ({r['Videos']}v)", axis=1),
            color="Weight",
            color_continuous_scale="RdYlGn",
        )
        fig.add_hline(y=1.0, line_dash="dash", line_color="gray")
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=10, b=20))
        st.plotly_chart(fig, use_container_width=True)

# ---- Row 4: Retention Trend ----
st.markdown("---")
st.subheader("📈 Retention Analysis")

retention_data = load_json(DATA_DIR / "retention_analysis.json")
if retention_data:
    # Try to show retention data if available
    st.info("Retention data available. Check data/retention_analysis.json for details.")

# ---- Row 5: Recent Videos ----
st.markdown("---")
st.subheader("🎬 Recent Videos")

if isinstance(video_history, list) and video_history:
    recent = video_history[-10:]
    rows = []
    for v in reversed(recent):
        rows.append({
            "Topic": v.get("topic", "?")[:60],
            "Platform": "YT" if v.get("youtube_id") else "?",
            "Published": v.get("published_at", v.get("timestamp", "?"))[:10],
            "Words": v.get("word_count", "?"),
            "Hook Score": v.get("hook_score", "?"),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("No videos published yet.")

# ---- Row 6: Alerts ----
alerts = growth_state.get("alerts", [])
if alerts:
    st.markdown("---")
    st.subheader("🚨 Alerts")
    for alert in alerts:
        level = alert.get("level", "info")
        icon = {"warn": "⚠️", "info": "ℹ️", "error": "🚫"}.get(level, "ℹ️")
        if level == "warn":
            st.warning(f"{icon} {alert.get('message', '')}")
        elif level == "error":
            st.error(f"{icon} {alert.get('message', '')}")
        else:
            st.info(f"{icon} {alert.get('message', '')}")

# ---- Row 7: Raw JSON debug (collapsed) ----
with st.expander("🔧 Raw Growth State (debug)"):
    st.json(growth_state)

# Footer
st.markdown("---")
st.caption(f"SKILLOR Dashboard • Generated at {datetime.now(timezone.utc).isoformat()[:19]}Z")
st.caption("Refresh the page to load latest data after a pipeline run commits new state files.")
