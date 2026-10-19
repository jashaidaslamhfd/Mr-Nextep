from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from scripts.youtube_inputs import require_publish_at, require_video_id, require_video_ids
from src.config import Settings
from src.guards import load_history
from src.utils import is_transient_http_error, redact_secrets
import requests


def test_publish_at_is_normalized_to_utc_z():
    assert require_publish_at('2026-09-13T19:05:58+00:00') == '2026-09-13T19:05:58Z'
    assert require_publish_at('2026-09-13T19:05:58Z') == '2026-09-13T19:05:58Z'


@pytest.mark.parametrize('value', ['', 'abc', 'dQw4w9WgXcQ!'])
def test_video_id_validation_rejects_invalid_values(value):
    with pytest.raises(SystemExit, match='video ID'):
        require_video_id(value)


def test_video_id_validation_accepts_standard_id():
    assert require_video_id('dQw4w9WgXcQ') == 'dQw4w9WgXcQ'
    assert require_video_ids('dQw4w9WgXcQ, 9bZkp7q19f0') == ['dQw4w9WgXcQ', '9bZkp7q19f0']


def test_publish_at_is_required():
    with pytest.raises(SystemExit, match='required'):
        require_publish_at('')


@pytest.mark.parametrize('value', ['2026-09-13 19:05:58', '2026-09-13T19:05:58+05:00'])
def test_publish_at_requires_explicit_utc(value):
    with pytest.raises(SystemExit, match='UTC'):
        require_publish_at(value)


def test_instagram_script_is_importable_without_running_network_calls():
    path = Path(__file__).parents[1] / 'scripts' / 'publish_instagram.py'
    spec = importlib.util.spec_from_file_location('publish_instagram_under_test', path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.GRAPH.endswith('/v21.0')
    assert module.valid_https_url('https://cdn.example/video.mp4')


def test_production_configuration_defaults_to_dry_run_and_private(monkeypatch):
    for key in ("DRY_RUN", "YT_PRIVACY_STATUS", "YT_SCHEDULE_PUBLISH"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None)
    assert settings.dry_run is True
    assert settings.privacy_status == "private"


def test_history_corruption_fails_closed(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid JSON"):
        load_history(path)


def test_history_wrong_shape_fails_closed(tmp_path):
    path = tmp_path / "history.json"
    path.write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="array of objects"):
        load_history(path)


def test_api_error_redaction_removes_access_token():
    value = "Request failed: https://graph.example/video?access_token=EAAsecret123&fields=id"
    assert "EAAsecret123" not in redact_secrets(value)
    assert "access_token=[REDACTED]" in redact_secrets(value)


def test_http_400_is_not_transient_but_429_is():
    bad_request = requests.Response()
    bad_request.status_code = 400
    too_many = requests.Response()
    too_many.status_code = 429
    assert is_transient_http_error(requests.HTTPError(response=bad_request)) is False
    assert is_transient_http_error(requests.HTTPError(response=too_many)) is True


def test_repair_script_refuses_apply_without_confirmation(monkeypatch):
    import scripts.repair_old_metadata as repair

    monkeypatch.setattr("sys.argv", ["repair_old_metadata.py", "--apply"])
    with pytest.raises(SystemExit) as exc:
        repair.main()
    assert exc.value.code == 2

def test_redaction_covers_quoted_json_and_bearer_tokens():
    from src.utils import redact_secrets

    assert "json-secret" not in redact_secrets('{"access_token": "json-secret"}')
    assert "bearer-secret" not in redact_secrets("Authorization: Bearer bearer-secret")
