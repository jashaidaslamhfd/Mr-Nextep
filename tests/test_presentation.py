from __future__ import annotations

import wave

from PIL import Image

from src import presentation


def test_original_ambient_bed_is_stereo_and_has_expected_duration(tmp_path):
    path = tmp_path / "ambient.wav"
    presentation._make_original_ambient(path, duration=0.25, sample_rate=8000)
    with wave.open(str(path), "rb") as audio:
        assert audio.getnchannels() == 2
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 8000
        assert abs(audio.getnframes() / audio.getframerate() - 0.25) < 0.001


def test_platform_covers_use_expected_aspect_ratios(monkeypatch, tmp_path):
    video = tmp_path / "fake.mp4"
    video.write_bytes(b"fake")
    original_run = presentation._run

    def fake_run(command):
        if command[0] == "ffmpeg":
            Image.new("RGB", (1080, 1920), (30, 45, 70)).save(command[-1], "JPEG")
        else:
            original_run(command)

    monkeypatch.setattr(presentation, "_run", fake_run)
    paths = presentation.generate_platform_thumbnails(video, "The Hidden Power of Memory", tmp_path)
    assert set(paths) == {"youtube", "instagram", "facebook"}
    with Image.open(paths["youtube"]) as image:
        assert image.size == (1280, 720)
    with Image.open(paths["instagram"]) as image:
        assert image.size == (1080, 1920)
    with Image.open(paths["facebook"]) as image:
        assert image.size == (1080, 1920)
