from __future__ import annotations

import json

from src.platform_analytics import _metric_value, build_growth_report, fetch_meta_metrics, write_growth_report


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, params, timeout))
        try:
            return next(self.responses)
        except StopIteration:
            return FakeResponse(400, {"error": {"message": "unsupported metric"}})


def test_metric_value_accepts_scalar_and_breakdown_values():
    assert _metric_value({"data": [{"name": "likes", "values": [{"value": 3}, {"value": 4}]}]}) == (7.0, "likes")
    assert _metric_value({"data": [{"name": "views", "value": 123}]}) == (123.0, "views")
    assert _metric_value({"data": []}) == (None, None)


def test_meta_metric_fallback_skips_unsupported_and_keeps_real_values():
    session = FakeSession([
        FakeResponse(400, {"error": {"message": "unsupported metric"}}),
        FakeResponse(200, {"data": [{"name": "plays", "values": [{"value": 90}]}]}),
    ])
    result = fetch_meta_metrics("instagram", "media-1", "secret-not-to-store", session=session, graph_base="https://graph.example/v99.0")
    assert result["status"] == "ok"
    assert result["metrics"]["views"] == 90
    assert result["metric_names"]["views"] == "plays"
    assert result["unavailable"]
    assert all("secret-not-to-store" not in str(row) for row in result.values())


def test_growth_report_uses_per_platform_medians_and_only_observed_metrics():
    youtube = {"videos": [
        {"video_id": "y1", "title": "A", "views": 100, "average_view_percentage": 0.2},
        {"video_id": "y2", "title": "B", "views": 200, "average_view_percentage": 0.4},
        {"video_id": "y3", "title": "C", "views": 1000, "average_view_percentage": 0.5},
    ]}
    meta = {"records": [
        {"platform": "instagram", "media_id": "i1", "title": "A", "metrics": {"views": 20, "reach": 10, "likes": 2}},
        {"platform": "instagram", "media_id": "i2", "title": "B", "metrics": {"views": 30}},
        {"platform": "instagram", "media_id": "i3", "title": "C", "metrics": {"views": 100}},
    ], "errors": []}
    report = build_growth_report(youtube, meta, generated_at="now")
    assert report["platforms"]["youtube"]["median_views"] == 200
    assert report["platforms"]["instagram"]["median_views"] == 30
    assert report["platforms"]["instagram"]["median_interactions_per_reach_pct"] == 20
    assert report["coverage"]["facebook_records"] == 0
    assert any(row["action"] == "replicate_winner_pattern" for row in report["recommendations"])


def test_report_writer_outputs_json_and_markdown(tmp_path):
    report = build_growth_report({"videos": []}, {"records": [], "errors": []}, generated_at="now")
    json_path, md_path = tmp_path / "report.json", tmp_path / "report.md"
    write_growth_report(report, json_path, md_path)
    assert json.loads(json_path.read_text())["generated_at"] == "now"
    assert "Weekly Cross-Platform Growth Report" in md_path.read_text()
