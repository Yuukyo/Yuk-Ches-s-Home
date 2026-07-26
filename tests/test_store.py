from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from store import Store


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(
            sqlite_path=Path(self.temp.name) / "test-home.db"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_message_lifecycle_preserves_grave(self) -> None:
        message = self.store.create_message(
            "user",
            "最初的话",
            metadata={"quote": "上一句"},
            created_at="2024-09-01T00:00:00+00:00",
        )
        edited = self.store.update_message(
            message["id"],
            {"content": "改过的话"},
        )
        self.assertEqual(edited["content"], "改过的话")

        deleted = self.store.update_message(
            message["id"],
            {
                "status": "deleted",
                "deletion_reason": "测试",
            },
        )
        self.assertEqual(deleted["status"], "deleted")
        graves = self.store.list_messages(statuses=("deleted",))
        self.assertEqual(graves[0]["deletion_reason"], "测试")

    def test_items_and_settings_round_trip(self) -> None:
        item = self.store.create_item(
            {
                "kind": "task",
                "title": "给绿植浇水",
                "value": 3,
                "metadata": {"done": False},
            }
        )
        updated = self.store.update_item(
            item["id"],
            {"metadata": {"done": True}},
        )
        self.assertTrue(updated["metadata"]["done"])
        self.assertEqual(self.store.list_items(kind="task")[0]["title"], "给绿植浇水")

        self.store.set_setting("profile", {"ai_name": "余天骋"})
        self.assertEqual(
            self.store.get_setting("profile")["ai_name"],
            "余天骋",
        )


if __name__ == "__main__":
    unittest.main()
