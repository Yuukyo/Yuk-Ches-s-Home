from __future__ import annotations

import re
import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.screen_targets: list[str] = []

    def handle_starttag(self, _tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"])
        if attributes.get("data-screen"):
            self.screen_targets.append(attributes["data-screen"])


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "templates" / "index.html").read_text(
            encoding="utf-8"
        )
        cls.javascript = (ROOT / "static" / "js" / "app.js").read_text(
            encoding="utf-8"
        )
        cls.css = (ROOT / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )
        cls.parser = IdCollector()
        cls.parser.feed(cls.html)
        cls.ids = set(cls.parser.ids)

    def test_no_duplicate_ids(self) -> None:
        duplicates = [
            key
            for key, count in Counter(self.parser.ids).items()
            if count > 1
        ]
        self.assertEqual(duplicates, [])

    def test_javascript_id_references_exist(self) -> None:
        referenced = set(
            re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', self.javascript)
        )
        dynamic_ids = set(
            re.findall(r'id=["\']([A-Za-z0-9_-]+)["\']', self.javascript)
        )
        missing = sorted(referenced - self.ids - dynamic_ids)
        self.assertEqual(missing, [])

    def test_navigation_targets_exist(self) -> None:
        missing = sorted(set(self.parser.screen_targets) - self.ids)
        self.assertEqual(missing, [])

    def test_mobile_layout_and_required_assets_exist(self) -> None:
        self.assertIn('name="viewport"', self.html)
        self.assertIn("@media", self.css)
        self.assertIn("/static/css/style.css", self.html)
        self.assertIn("/static/js/app.js", self.html)


if __name__ == "__main__":
    unittest.main()
