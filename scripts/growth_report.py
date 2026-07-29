#!/usr/bin/env python3
"""
scripts/growth_report.py — the one page a human actually reads.

Runs the full learning cycle and prints a plain-language report:

  1. fetch real numbers from YouTube + Facebook + Instagram
  2. learn from them (slots, topics, hooks, cadence)
  3. print what is working, what is not, and the single next action

Also writes docs/GROWTH_REPORT.md so the latest verdict is committed with the
channel state and can be read from a phone without opening Actions logs.

Everything is read-only against the platforms. Nothing here publishes,
deletes, or edits a video.

Usage:
    python scripts/growth_report.py            # fetch + learn + report
    python scripts/growth_report.py --no-fetch # re-print from stored metrics
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import algorithm_policy as policy  # noqa: E402
from growth_engine import analyse, load_state  # noqa: E402

REPORT_PATH = ROOT / "docs" / "GROWTH_REPORT.md"

_STATUS_ICON = {
    "healthy": "🟢",
    "below_gate": "🟡",
    "critical": "🔴",
    "no_data": "⚪",
}


def _fmt_pct(value, digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.{digits}f}%"


def _platform_block(info: dict) -> list:
    icon = _STATUS_ICON.get(info["status"], "⚪")
    lines = [
        f"### {icon} {info['label']} — {info['status'].replace('_', ' ')}",
        "",
    ]
    if info["status"] == "no_data":
        lines += [f"No usable metrics yet. {info['action']}", ""]
        return lines
    lines += [
        f"- Videos measured: **{info['samples']}**",
        f"- Average completion: **{_fmt_pct(info.get('avg_completion'))}** "
        f"against a **{_fmt_pct(info['gate'])}** distribution gate "
        f"(ratio {info.get('gate_ratio', 0):.2f})",
    ]
    if info.get("avg_views") is not None:
        lines.append(f"- Average views: **{info['avg_views']:.0f}**")
    lines += ["", f"**Next action:** {info['action']}", ""]
    return lines


def build_report(state: dict) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# SKILLOR growth report",
        "",
        f"_Generated {generated} · policy {policy.POLICY_VERSION} "
        f"(verified {policy.LAST_VERIFIED})_",
        "",
        "This file is produced by `scripts/growth_report.py`. It reads real",
        "numbers from all three platforms, compares each against that",
        "platform's own 2026 distribution gate, and states one next action.",
        "",
        "---",
        "",
        "## Headline",
        "",
    ]

    sample = state.get("sample_size", 0)
    if not sample:
        lines += [
            "**No mature videos with readable metrics yet.**",
            "",
            "This is expected on a fresh channel or when analytics access is",
            "not connected. Every platform needs ~24-48h after publishing",
            "before its numbers mean anything, and the learning loop waits for",
            f"at least {policy.HEALTH_THRESHOLDS['min_samples_per_slot']} mature",
            "videos per bucket before it will move any weight — small samples",
            "produce confident nonsense.",
            "",
        ]
    else:
        ratio = state.get("channel_gate_ratio")
        verdict = (
            "clearing the bar" if ratio and ratio >= 1.0
            else "under the bar" if ratio and ratio >= policy.HEALTH_THRESHOLDS["critical_retention_ratio"]
            else "far under the bar"
        )
        lines += [
            f"Across **{sample} mature videos**, the channel is **{verdict}** "
            f"(retention index {ratio:.2f}, where 1.00 = exactly the level at "
            "which each platform widens distribution).",
            "",
            f"- Best publish slot: **{state.get('best_slot') or '—'} NY**",
            f"- Best-retaining topics: **{', '.join(state.get('best_topics') or []) or '—'}**",
            f"- Best opening frame: **{state.get('best_hook_frame') or '—'}**",
            f"- Recommended cadence: **{state.get('recommended_cadence')} video(s)/day**",
            "",
            f"> {state.get('cadence_reason', '')}",
            "",
        ]

    alerts = state.get("alerts") or []
    if alerts:
        lines += ["## Needs attention", ""]
        for alert in alerts:
            marker = "🔴" if alert.get("level") == "error" else "🟡"
            lines.append(f"- {marker} {alert.get('message')}")
        lines.append("")

    lines += ["## Per platform", ""]
    for platform in policy.PLATFORMS:
        info = (state.get("platform_health") or {}).get(platform)
        if info:
            lines += _platform_block(info)

    sends = state.get("instagram_sends")
    if sends:
        icon = "🟢" if sends["healthy"] else "🟡"
        lines += [
            "### " + icon + " Instagram sends (DM shares)",
            "",
            f"- Sends per reach: **{sends['avg_sends_per_reach'] * 100:.2f}%** "
            f"across {sends['samples']} Reels",
            "",
            "Sends are Instagram's strongest signal for reaching people who do",
            "not already follow the account — weighted several times higher",
            "than a like. It is the metric nothing else in this repo reports.",
            "",
            f"**Next action:** {sends['action']}",
            "",
        ]

    slot_weights = state.get("slot_weights") or {}
    if slot_weights:
        lines += [
            "## Learned weights",
            "",
            "Weights multiply how often a slot or topic pillar gets chosen.",
            "1.00 is neutral; they are clamped to 0.35-2.00 so nothing is ever",
            "permanently switched off and can always earn its way back.",
            "",
            "| Slot (NY) | Weight | Videos |",
            "|---|---|---|",
        ]
        samples = state.get("slot_samples") or {}
        for slot in sorted(slot_weights, key=slot_weights.get, reverse=True):
            lines.append(f"| {slot} | {slot_weights[slot]:.2f} | {samples.get(slot, 0)} |")
        lines.append("")

    topic_weights = state.get("topic_weights") or {}
    if topic_weights:
        topic_samples = state.get("topic_samples") or {}
        lines += ["| Topic pillar | Weight | Videos |", "|---|---|---|"]
        for pillar in sorted(topic_weights, key=topic_weights.get, reverse=True):
            lines.append(
                f"| {pillar} | {topic_weights[pillar]:.2f} | {topic_samples.get(pillar, 0)} |"
            )
        lines.append("")

    lines += [
        "## The policy this is measured against",
        "",
        "```",
        policy.summary(),
        "```",
        "",
        "Platform ranking behaviour changes every few months. Re-verify the",
        f"sources in `src/algorithm_policy.py` every {policy.REVERIFY_AFTER_DAYS} days",
        "and update the constants there — every other module follows.",
        "",
    ]
    return "\n".join(lines)


def print_console(state: dict) -> None:
    print("=" * 68)
    print(f"SKILLOR GROWTH REPORT · policy {policy.POLICY_VERSION}")
    print("=" * 68)
    sample = state.get("sample_size", 0)
    print(f"Mature videos measured : {sample}")
    ratio = state.get("channel_gate_ratio")
    print(f"Retention index        : {ratio if ratio is not None else '—'} (1.00 = at the gate)")
    print(f"Recommended cadence    : {state.get('recommended_cadence')}/day")
    print(f"Reason                 : {state.get('cadence_reason')}")
    print()
    for platform in policy.PLATFORMS:
        info = (state.get("platform_health") or {}).get(platform, {})
        if not info:
            continue
        icon = _STATUS_ICON.get(info.get("status"), "⚪")
        print(f"{icon} {info.get('label')}: {info.get('status')} "
              f"(completion {_fmt_pct(info.get('avg_completion'))} / gate {_fmt_pct(info.get('gate'))})")
        print(f"   → {info.get('action')}")
    print()
    for alert in state.get("alerts") or []:
        marker = "!!" if alert.get("level") == "error" else " !"
        print(f"{marker} {alert.get('message')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch metrics, learn, and report.")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip the API round-trip and re-use stored metrics")
    parser.add_argument("--no-write", action="store_true",
                        help="print only; do not update docs/GROWTH_REPORT.md")
    args = parser.parse_args()

    if not args.no_fetch:
        try:
            from platform_metrics import collect
            result = collect(
                min_hours_old=int(os.environ.get("METRICS_MIN_HOURS", "24")),
                refresh_hours=int(os.environ.get("METRICS_REFRESH_HOURS", "20")),
            )
            print(f"Metrics collected: {result['stats']}")
        except Exception as exc:  # noqa: BLE001 - report must still render
            print(f"WARNING: metric collection failed ({exc}); using stored data.")

    state = analyse()
    if not state:
        state = load_state()
    print_console(state)

    if not args.no_write:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(build_report(state), encoding="utf-8")
        print(f"\nWritten: {REPORT_PATH.relative_to(ROOT)}")

    # Exit 0 always: this is a report, and a non-zero exit would turn a
    # legitimate "you have no data yet" into a red workflow that people learn
    # to ignore. Real problems are surfaced as alerts in the report body.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
