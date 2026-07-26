from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

import app as home_app
from store import Store


class AppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        home_app.store = Store(
            sqlite_path=Path(self.temp.name) / "api-test.db"
        )
        home_app.app.config.update(TESTING=True)
        self.client = home_app.app.test_client()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_health_and_bootstrap(self) -> None:
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.get_json()["ok"])
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Content-Security-Policy", page.headers)
        css_response = self.client.get("/static/css/style.css")
        js_response = self.client.get("/static/js/app.js")
        try:
            self.assertEqual(css_response.status_code, 200)
            self.assertEqual(js_response.status_code, 200)
        finally:
            css_response.close()
            js_response.close()
        bootstrap = self.client.get("/api/bootstrap").get_json()
        self.assertEqual(bootstrap["messages"], [])
        self.assertEqual(bootstrap["items"], [])

    def test_item_crud(self) -> None:
        response = self.client.post(
            "/api/items",
            json={
                "kind": "task",
                "title": "整理书架",
                "value": 4,
                "metadata": {"done": False},
            },
        )
        self.assertEqual(response.status_code, 201)
        item = response.get_json()
        changed = self.client.patch(
            f"/api/items/{item['id']}",
            json={"metadata": {"done": True}},
        ).get_json()
        self.assertTrue(changed["metadata"]["done"])

    def test_ovo_import_is_ordered_and_deduplicated(self) -> None:
        payload = {
            "type": "uwu-chat-history",
            "version": 1,
            "charName": "余天骋",
            "history": [
                {
                    "id": "ovo-2",
                    "role": "assistant",
                    "content": "我在。",
                    "timestamp": 1725148801000,
                },
                {
                    "id": "ovo-1",
                    "role": "user",
                    "parts": [{"type": "text", "text": "回家吧。"}],
                    "timestamp": "2024-09-01T00:00:00Z",
                },
            ],
        }

        def upload():
            return {
                "file": (
                    io.BytesIO(json.dumps(payload).encode("utf-8")),
                    "ovo.json",
                ),
                "mode": "append",
            }

        first = self.client.post(
            "/api/import/ovo",
            data=upload(),
            content_type="multipart/form-data",
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["imported"], 2)

        second = self.client.post(
            "/api/import/ovo",
            data=upload(),
            content_type="multipart/form-data",
        )
        self.assertEqual(second.get_json()["imported"], 0)
        self.assertEqual(second.get_json()["skipped"], 2)

        messages = home_app.store.list_messages()
        self.assertEqual([item["content"] for item in messages], ["回家吧。", "我在。"])

        exported = self.client.get("/api/export/chat").get_json()
        self.assertEqual(exported["type"], "uwu-chat-history")
        self.assertEqual(len(exported["history"]), 2)


if __name__ == "__main__":
    unittest.main()
