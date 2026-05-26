import json
import tempfile
import unittest
from pathlib import Path

from vision_bot_core.backup_store import (
    backup_json_files,
    get_latest_backup,
    list_backups,
    prune_backups,
    safe_name_part,
)


class BackupStoreTests(unittest.TestCase):
    def test_backup_json_files_copies_existing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup_dir = root / "backups"
            settings_file = root / "settings.json"
            history_file = root / "alert_history.json"
            settings_file.write_text(json.dumps({"cooldown": 10}), encoding="utf-8")
            history_file.write_text(json.dumps([{"id": "a"}]), encoding="utf-8")

            backups = backup_json_files(
                [
                    ("settings", str(settings_file)),
                    ("alert_history", str(history_file)),
                    ("missing", str(root / "missing.json")),
                ],
                str(backup_dir),
                reason="before_clear_history",
                max_backups=10,
            )

            self.assertEqual(len(backups), 2)
            self.assertTrue(all(Path(path).exists() for path in backups))
            self.assertEqual(len(list(backup_dir.glob("*.json"))), 2)

    def test_prune_backups_keeps_newest_files_under_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_dir = Path(temp_dir) / "backups"
            backup_dir.mkdir()
            for index in range(5):
                (backup_dir / f"backup_{index}.json").write_text("{}", encoding="utf-8")

            prune_backups(str(backup_dir), max_backups=3)

            self.assertEqual(len(list(backup_dir.glob("*.json"))), 3)

    def test_safe_name_part_removes_path_unsafe_characters(self):
        self.assertEqual(safe_name_part("Before Setting: cooldown/sec"), "before_setting__cooldown_sec")
        self.assertEqual(safe_name_part(""), "backup")

    def test_list_backups_returns_newest_entries_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup_dir = root / "backups"
            source = root / "settings.json"
            source.write_text("{}", encoding="utf-8")

            backup_json_files([("settings", str(source))], str(backup_dir), reason="first", max_backups=10)
            backup_json_files([("settings", str(source))], str(backup_dir), reason="second", max_backups=10)

            backups = list_backups(str(backup_dir), limit=1)

            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0]["label"], "settings")
            self.assertEqual(backups[0]["reason"], "second")
            self.assertTrue(backups[0]["filename"].endswith(".json"))

    def test_get_latest_backup_filters_by_label(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup_dir = root / "backups"
            settings_file = root / "settings.json"
            history_file = root / "alert_history.json"
            settings_file.write_text("{}", encoding="utf-8")
            history_file.write_text("[]", encoding="utf-8")

            backup_json_files([("settings", str(settings_file))], str(backup_dir), reason="setting", max_backups=10)
            backup_json_files([("alert_history", str(history_file))], str(backup_dir), reason="history", max_backups=10)

            latest_settings = get_latest_backup(str(backup_dir), label="settings")

            self.assertIsNotNone(latest_settings)
            self.assertEqual(latest_settings["label"], "settings")
            self.assertEqual(latest_settings["reason"], "setting")


if __name__ == "__main__":
    unittest.main()
