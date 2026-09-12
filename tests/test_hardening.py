from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from scripts.youtube_inputs import require_publish_at, require_video_id, require_video_ids


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
