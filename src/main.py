"""Pipeline entrypoint: topic -> script -> render -> validate -> guard -> publish.

Run from the repository root as a package:

    python -m src.main
"""
from __future__ import annotations

import json
import logging
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path

try:
    from datetime import UTC
except ImportError:  # Python < 3.11
    UTC = UTC

from .analytics import AnalyticsError, load_performance
from .config import SETTINGS
from .content import choose_topic, generate_script
from .guards import enforce, load_history, save_history
from .media import render, validate
from .meta import publish as publish_meta
from .utils import TitleRejected, validate_short_title
from .youtube import upload

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _git_persist(paths: list[str], message: str) -> None:
    """Best-effort state commit with rebase; never hide the production result."""
    existing = [p for p in paths if Path(p).exists()]
    if not existing:
        return
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=False)
    subprocess.run(
        ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        check=False,
    )
    subprocess.run(["git", "add", "-f", *existing], check=False)
    commit = subprocess.run(["git", "commit", "-m", message], check=False, capture_output=True, text=True)
    if commit.returncode == 0:
        pull = subprocess.run(
            ["git", "pull", "--rebase", "origin", "main"], check=False, capture_output=True, text=True
        )
        if pull.returncode == 0:
            pushed = subprocess.run(
                ["git", "push", "origin", "HEAD:main"], check=False, capture_output=True, text=True
            )
            if pushed.returncode != 0:
                log.warning("State push failed: %s", pushed.stderr[-500:])
        else:
            log.warning("State rebase failed: %s", pull.stderr[-500:])


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def _titles_collide(candidate: str, previous: str) -> bool:
    """Conservative containment check between two metadata strings."""
    a, b = _normalize(candidate), _normalize(previous)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def metadata_collides(script: dict, video_history: list, check_last: int) -> bool:
    """True when this script's title/description matches a recently published video.

    Checked before rendering so a collision costs one cheap regeneration instead of a
    wasted encode. Duplicates are resolved by generating different content, never by
    appending a cosmetic suffix to an otherwise identical title.
    """
    if not video_history or check_last < 1:
        return False
    title = str(script.get("title", ""))
    description = str(script.get("description", "") or "")
    for previous in reversed(video_history[-check_last:]):
        if not isinstance(previous, dict):
            continue
        if _titles_collide(title, str(previous.get("title", ""))):
            return True
        if description and _titles_collide(description, str(previous.get("description", "") or "")):
            return True
    return False


def run() -> dict:
    errors = SETTINGS.check_config()
    if errors:
        raise RuntimeError("Configuration invalid: " + "; ".join(errors))

    SETTINGS.ensure_dirs()
    history_path = SETTINGS.data_dir / "content_history.json"
    video_history_path = SETTINGS.data_dir / "video_history.json"
    history = load_history(history_path)
    published_history = load_history(video_history_path)

    # Real measured channel performance, when it has been pulled. An empty or unreadable
    # cache must not stop a publishing run, but the reason is logged so a silently broken
    # feedback loop cannot masquerade as "no data yet".
    performance_path = SETTINGS.data_dir / "performance_history.json"
    try:
        performance = load_performance(performance_path)
    except AnalyticsError as exc:
        log.error("Performance cache unusable (%s); publishing without retention evidence.", exc)
        performance = None
    else:
        if performance.has_baseline:
            log.info(
                "Retention baseline: %.0f%% median across %d videos (through %s).",
                (performance.median_retention or 0.0) * 100,
                performance.videos_with_data,
                performance.covered_through or "unknown",
            )
        else:
            log.info(
                "Only %d videos with performance data; retention gate stays ungrounded.",
                performance.videos_with_data,
            )

    last_error: Exception | None = None
    for attempt in range(SETTINGS.max_attempts):
        base_topic = SETTINGS.topic or choose_topic(SETTINGS)
        topic = f"{base_topic} — fresh angle {attempt + 1}" if SETTINGS.topic and attempt else base_topic
        script = generate_script(topic, SETTINGS)
        if SETTINGS.topic:
            # An operator-supplied topic may be used verbatim as the title, but only when
            # it is publishable on its own. Truncating it to 70 chars (the old behaviour)
            # cut words in half and bypassed title validation entirely.
            try:
                script["title"] = validate_short_title(base_topic)
            except TitleRejected as exc:
                log.info(
                    "Keeping the generated title; VIDEO_TOPIC is not usable as one (%s)", exc
                )
            if script.get("scenes"):
                script["scenes"][0]["narration"] = base_topic

        if metadata_collides(script, published_history, SETTINGS.duplicate_check_last):
            log.warning(
                "Attempt %d/%d rejected: metadata collides with a recent upload (%r)",
                attempt + 1,
                SETTINGS.max_attempts,
                script.get("title", ""),
            )
            last_error = RuntimeError("Generated metadata duplicates a recent upload")
            continue

        try:
            video = render(script, SETTINGS)
            technical = validate(video, SETTINGS)
            guard_script = deepcopy(script)
            guard_script["title"] = topic
            guard = enforce(guard_script, float(technical["duration"]), history, performance)
            break
        except RuntimeError as exc:
            last_error = exc
            log.warning("Attempt %d/%d rejected: %s", attempt + 1, SETTINGS.max_attempts, exc)
            if "No unique moving video clip found" in str(exc) and attempt >= SETTINGS.max_attempts - 1:
                raise RuntimeError(
                    f"Could not produce a valid video because no unique moving video clip was found: {exc}"
                ) from exc
            continue
    else:
        if last_error and "no unique moving video clip" in str(last_error).lower():
            raise RuntimeError(
                f"Could not produce a valid video because no unique moving video clip was found: {last_error}"
            )
        raise RuntimeError(
            f"Could not produce a valid unique video after {SETTINGS.max_attempts} attempts: {last_error}"
        )

    clip_manifest = SETTINGS.output_dir / "clip_hashes.json"
    clip_hashes = json.loads(clip_manifest.read_text(encoding="utf-8")) if clip_manifest.exists() else []
    source_urls = [
        p.read_text(encoding="utf-8") for p in sorted((SETTINGS.output_dir / "scenes").glob("*.source_url"))
    ]
    created_at = datetime.now(UTC).isoformat()
    result = {
        "created_at": created_at,
        "status": "pending",
        "topic": base_topic,
        "title": script["title"],
        "video_path": str(video),
        "clip_hashes": clip_hashes,
        **technical,
        **guard,
    }

    # Persist the reservation before any external upload. A later run can reject it.
    history.append(guard)
    save_history(history_path, history)
    clip_history_path = SETTINGS.data_dir / "clip_history.json"
    clip_history = load_history(clip_history_path)
    clip_history.extend(
        {
            "hash": h,
            "source_url": source_urls[i] if i < len(source_urls) else "",
            "title": result["title"],
            "created_at": created_at,
        }
        for i, h in enumerate(clip_hashes)
    )
    clip_history_path.write_text(
        json.dumps(clip_history[-500:], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    video_history = published_history
    video_history.append(result)
    video_history_path.write_text(
        json.dumps(video_history[-500:], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    topic_index_path = SETTINGS.data_dir / "topic_index.json"
    trend_index_path = SETTINGS.data_dir / "trend_topic_index.json"
    queue_path = SETTINGS.data_dir / "search_demand_queue_us.json"
    _git_persist(
        [
            str(history_path),
            str(clip_history_path),
            str(video_history_path),
            str(topic_index_path),
            str(trend_index_path),
            str(queue_path),
        ],
        "chore: reserve generated video state",
    )

    try:
        result.update(upload(video, script, SETTINGS))
        if not SETTINGS.dry_run:
            try:
                result["meta"] = publish_meta(video, script, result)
            except Exception as exc:
                log.exception("Meta publishing failed after YouTube upload; preserving YouTube result")
                result["meta"] = {"status": "error", "reason": str(exc)}
        result["status"] = "uploaded"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = str(exc)
        video_history[-1] = result
        video_history_path.write_text(
            json.dumps(video_history[-500:], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _git_persist([str(video_history_path)], "chore: mark generated video upload failed")
        log.exception("Upload failed; failed state committed for recovery")
        raise

    video_history[-1] = result
    video_history_path.write_text(
        json.dumps(video_history[-500:], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _git_persist([str(video_history_path)], "chore: finalize generated video state")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    run()
