from __future__ import annotations

import json

from scripts import preflight


class FakeSettings:
    def __init__(self, dry_run: bool = False, config_errors: list[str] | None = None) -> None:
        self.dry_run = dry_run
        self._config_errors = config_errors or []

    def check_config(self) -> list[str]:
        return list(self._config_errors)


def test_collect_errors_requires_tools_even_for_dry_run() -> None:
    errors = preflight.collect_errors(
        settings=FakeSettings(dry_run=True),
        environ={},
        which=lambda _name: None,
    )
    assert errors == [
        "ffmpeg is required but was not found on PATH",
        "ffprobe is required but was not found on PATH",
    ]


def test_collect_errors_names_each_missing_production_credential() -> None:
    errors = preflight.collect_errors(
        settings=FakeSettings(dry_run=False),
        environ={"GROQ_API_KEY": "example-secret"},
        which=lambda name: f"/usr/bin/{name}",
    )
    assert len(errors) == 1
    assert "Google OAuth client ID" in errors[0]
    assert "Google OAuth client secret" in errors[0]
    assert "YouTube OAuth refresh token" in errors[0]
    assert "GOOGLE_CLIENT_ID or YT_CLIENT_ID" in errors[0]
    assert all("example-secret" not in error for error in errors)


def test_collect_errors_accepts_complete_youtube_configuration() -> None:
    errors = preflight.collect_errors(
        settings=FakeSettings(dry_run=False),
        environ={
            "GROQ_API_KEY": "example-secret",
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "client-secret",
            "REFRESH_TOKEN": "refresh-token",
        },
        which=lambda name: f"/usr/bin/{name}",
    )
    assert errors == []


def test_collect_errors_accepts_youtube_aliases_and_ignores_whitespace_values() -> None:
    errors = preflight.collect_errors(
        settings=FakeSettings(dry_run=False),
        environ={
            "OPENROUTER_API_KEY": "provider-secret",
            "GOOGLE_CLIENT_ID": "   ",
            "YT_CLIENT_ID": "client-id",
            "YT_CLIENT_SECRET": "client-secret",
            "YT_REFRESH_TOKEN": "refresh-token",
        },
        which=lambda name: f"/usr/bin/{name}",
    )
    assert errors == []


def test_collect_errors_reports_partial_meta_configuration() -> None:
    errors = preflight.collect_errors(
        settings=FakeSettings(dry_run=False),
        environ={
            "GROQ_API_KEY": "provider-secret",
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "client-secret",
            "REFRESH_TOKEN": "refresh-token",
            "FACEBOOK_PAGE_ID": "page-id",
        },
        which=lambda name: f"/usr/bin/{name}",
    )
    assert any("provide both FACEBOOK_PAGE_ID and FACEBOOK_ACCESS_TOKEN" in e for e in errors)


def test_main_emits_machine_readable_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(preflight, "collect_errors", lambda: ["ffmpeg is required"])
    assert preflight.main() == 1
    output = json.loads(capsys.readouterr().out)
    assert output == {"ok": False, "errors": ["ffmpeg is required"]}
