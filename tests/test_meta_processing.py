from __future__ import annotations

import pytest

from src import meta


class FakeSession:
    pass


def test_instagram_polling_honors_configured_interval(monkeypatch) -> None:
    responses = iter([
        {"status_code": "IN_PROGRESS", "status": "Processing"},
        {"status_code": "FINISHED", "status": "Finished"},
    ])
    sleeps: list[float] = []
    monkeypatch.setattr(meta, "_get", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(meta.time, "sleep", sleeps.append)
    monkeypatch.setenv("INSTAGRAM_PROCESSING_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("INSTAGRAM_PROCESSING_WAIT_SECONDS", "7")

    meta._wait_until_ready(FakeSession(), "container-1", "token")

    assert sleeps == [7]


def test_instagram_processing_error_is_not_published(monkeypatch) -> None:
    monkeypatch.setattr(
        meta,
        "_get",
        lambda *args, **kwargs: {"status_code": "ERROR", "status": "Video processing failed"},
    )
    monkeypatch.setenv("INSTAGRAM_PROCESSING_WAIT_SECONDS", "1")

    with pytest.raises(RuntimeError, match="Video processing failed"):
        meta._wait_until_ready(FakeSession(), "container-2", "token")


def test_instagram_polling_normalizes_status_case(monkeypatch) -> None:
    responses = iter([{"status_code": "finished"}])
    monkeypatch.setattr(meta, "_get", lambda *args, **kwargs: next(responses))

    meta._wait_until_ready(FakeSession(), "container-3", "token")
