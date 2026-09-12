"""Upload-body tests.

`privacy=getattr(settings, "privacy", "public")` read a field name that does not exist
(the field is `privacy_status`), so getattr silently returned its default and every
upload was forced public — overriding YT_PRIVACY_STATUS in both the workflow and
env.example. These tests pin the privacy contract so it cannot regress silently.
"""
from __future__ import annotations

from src.config import Settings
from src.content import fallback
from src.youtube import build_upload_body


def _script():
    return fallback("Why does memory feel familiar?")


def test_configured_private_status_is_honoured():
    settings = Settings(dry_run=False, privacy_status="private", schedule_publish=False)
    body = build_upload_body(_script(), settings)
    assert body["status"]["privacyStatus"] == "private"


def test_public_is_only_used_when_explicitly_configured():
    settings = Settings(dry_run=False, privacy_status="public", schedule_publish=False)
    body = build_upload_body(_script(), settings)
    assert body["status"]["privacyStatus"] == "public"


def test_default_privacy_status_is_private():
    assert Settings().privacy_status == "private"
    body = build_upload_body(_script(), Settings(schedule_publish=False))
    assert body["status"]["privacyStatus"] == "private"


def test_scheduling_sets_publish_at_in_utc():
    settings = Settings(dry_run=False, privacy_status="private", schedule_publish=True)
    body = build_upload_body(_script(), settings)
    assert body["status"]["publishAt"].endswith("Z")


def test_no_publish_at_when_scheduling_disabled():
    settings = Settings(dry_run=False, privacy_status="private", schedule_publish=False)
    body = build_upload_body(_script(), settings)
    assert "publishAt" not in body["status"]


def test_title_has_no_random_garnish():
    body = build_upload_body(_script(), Settings(schedule_publish=False))
    title = body["snippet"]["title"]
    assert "✨" not in title and "🔥" not in title
