"""Regression tests for the live Meta analytics endpoint and diagnostics."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_updater():
    path = ROOT / "scripts" / "update_facebook_analytics.py"
    spec = importlib.util.spec_from_file_location("update_facebook_analytics_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FacebookInsightsEndpointTests(unittest.TestCase):
    def test_fetch_uses_current_video_insights_edge(self):
        response = Mock(status_code=200, content=b"{}", text="")
        response.json.return_value = {
            "data": [{"values": [{"value": 123}]}]
        }
        with patch.dict(os.environ, {"FB_ACCESS_TOKEN": "test-token"}, clear=False), \
             patch("requests.get", return_value=response) as get:
            module = load_updater()
            result = module.fetch("video-123")

        self.assertNotIn("status", result)
        self.assertEqual(len(get.call_args_list), len(module.METRICS))
        for call in get.call_args_list:
            url = call.args[0]
            self.assertTrue(url.endswith("/video-123/video_insights"), url)
            self.assertNotIn("/video-123/insights", url)
        requested = {call.kwargs["params"]["metric"] for call in get.call_args_list}
        self.assertEqual(requested, set(module.METRICS))

    def test_permission_error_describes_effective_token_requirements(self):
        response = Mock(status_code=403, content=b"{}", text="Permissions error")
        response.json.return_value = {
            "error": {"code": 200, "message": "Permissions error"}
        }
        with patch.dict(os.environ, {"FB_ACCESS_TOKEN": "test-token"}, clear=False), \
             patch("requests.get", return_value=response):
            module = load_updater()
            result = module.fetch("video-123")

        status = result.get("status", "")
        self.assertIn("Page access token", status)
        self.assertIn("read_insights", status)
        self.assertIn("pages_manage_engagement", status)
        self.assertIn("ANALYZE", status)
        self.assertNotIn("grant `pages_read_engagement`", status)


class FacebookDiagnosticContractTests(unittest.TestCase):
    def test_operator_diagnostic_probes_video_insights(self):
        text = (ROOT / "scripts" / "fb_token_diag.py").read_text(encoding="utf-8")
        self.assertIn('call(f"{reel_id}/video_insights"', text)
        self.assertIn("post_video_avg_time_watched", text)


if __name__ == "__main__":
    unittest.main()
