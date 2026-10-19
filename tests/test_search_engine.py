import os
import unittest
from unittest.mock import patch
import search_engine


def item(title, url, provider="mock", branch="primary", content="query documentation"):
    return {"title": title, "url": url, "content": content, "provider": provider, "branch": branch}


class SearchEngineTests(unittest.TestCase):
    def test_empty_query_returns_structured_error(self):
        result = search_engine.web_search("   ")
        self.assertFalse(result["available"])
        self.assertEqual(result["results"], [])
        self.assertIn("Nhập", result["note"])

    @patch.dict(os.environ, {"TAVILY_API_KEY": "", "BRAVE_SEARCH_API_KEY": "", "SEARCH_TIMEOUT_SECONDS": "3"}, clear=False)
    @patch("search_engine._duckduckgo", return_value=[item("Official query docs", "https://example.com/docs?utm=1", "DuckDuckGo")])
    @patch("search_engine._bing", return_value=[item("Official query docs duplicate", "https://example.com/docs#intro", "Bing")])
    @patch("search_engine._wikipedia", return_value=[])
    def test_fans_out_and_deduplicates_urls(self, wiki, bing, ddg):
        result = search_engine.web_search("query documentation", limit=5)
        self.assertTrue(result["available"])
        self.assertEqual(len(result["results"]), 1)
        self.assertIn("DuckDuckGo", result["providers"])
        self.assertGreaterEqual(result["elapsed_ms"], 0)
        self.assertEqual(ddg.call_count, 1)
        self.assertEqual(bing.call_count, 1)

    @patch.dict(os.environ, {"TAVILY_API_KEY": "", "BRAVE_SEARCH_API_KEY": "", "SEARCH_TIMEOUT_SECONDS": "3"}, clear=False)
    @patch("search_engine._duckduckgo", side_effect=RuntimeError("blocked"))
    @patch("search_engine._bing", side_effect=RuntimeError("blocked"))
    @patch("search_engine._wikipedia", side_effect=RuntimeError("blocked"))
    def test_all_providers_fail_without_crashing(self, wiki, bing, ddg):
        result = search_engine.web_search("ordinary query", limit=4)
        self.assertFalse(result["available"])
        self.assertEqual(result["results"], [])
        self.assertTrue(result["failed_providers"])
        self.assertIn("Không lấy được", result["note"])

    def test_rejects_non_http_result(self):
        self.assertIsNone(search_engine._valid_result("bad", "javascript:alert(1)", "x", "mock"))
        self.assertIsNone(search_engine._valid_result("bad", "file:///etc/passwd", "x", "mock"))

    def test_deep_search_creates_three_distinct_branches(self):
        branches = search_engine._branches("Flask bảo mật", True)
        self.assertEqual([b[0] for b in branches], ["primary", "official", "freshness"])
        self.assertEqual(len({b[1] for b in branches}), 3)


if __name__ == "__main__":
    unittest.main()
