from __future__ import annotations

import unittest

from integrations import IntegrationError, _text_from_mcp


class IntegrationParserTests(unittest.TestCase):
    def test_reads_text_content(self) -> None:
        payload = {
            "result": {
                "content": [
                    {"type": "text", "text": "第一段"},
                    {"type": "text", "text": "第二段"},
                ]
            }
        }
        self.assertEqual(_text_from_mcp(payload), "第一段\n第二段")

    def test_raises_mcp_error(self) -> None:
        payload = {
            "result": {
                "isError": True,
                "content": [{"type": "text", "text": "工具失败"}],
            }
        }
        with self.assertRaisesRegex(IntegrationError, "工具失败"):
            _text_from_mcp(payload)


if __name__ == "__main__":
    unittest.main()
