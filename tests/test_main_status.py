from __future__ import annotations

from src.main import _resolve_upload_status


def test_dry_run_is_never_reported_as_uploaded() -> None:
    assert _resolve_upload_status({"status": "dry_run"}, dry_run=True) == "dry_run"
    assert _resolve_upload_status({"status": "dry_run"}, dry_run=False) == "dry_run"


def test_upload_requires_provider_confirmation_and_video_id() -> None:
    assert _resolve_upload_status({"status": "uploaded", "youtube_video_id": "abcdefghijk"}, dry_run=False) == "uploaded"
    assert _resolve_upload_status({"status": "skipped"}, dry_run=False) == "failed"
    assert _resolve_upload_status({"status": "uploaded"}, dry_run=False) == "failed"
