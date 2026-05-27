import json
import tempfile
import unittest
from pathlib import Path

from vision_bot_core import alert_history_store


class AlertHistoryStoreTests(unittest.TestCase):
    def configure_store(self, temp_dir, history_limit=2):
        base_dir = Path(temp_dir)
        log_dir = base_dir / "logs"
        errors = []
        alert_history_store.configure_alert_history_store(
            base_dir=str(base_dir),
            log_dir=str(log_dir),
            alert_history_file=str(log_dir / "alert_history.json"),
            get_history_limit=lambda: history_limit,
            log_error=lambda context, error=None: errors.append((context, error)),
        )
        return base_dir, log_dir, errors

    def test_add_alert_history_trims_old_records_and_deletes_media(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _, log_dir, errors = self.configure_store(temp_dir, history_limit=2)
            log_dir.mkdir(parents=True, exist_ok=True)
            old_image = log_dir / "alert_old.jpg"
            old_video = log_dir / "alert_old.mp4"
            old_image.write_bytes(b"image")
            old_video.write_bytes(b"video")

            alert_history_store.add_alert_history({
                "id": "old",
                "image_path": "logs/alert_old.jpg",
                "video_path": "logs/alert_old.mp4",
            })
            alert_history_store.add_alert_history({"id": "new-1"})
            alert_history_store.add_alert_history({"id": "new-2"})

            history = alert_history_store.get_alert_history_snapshot()

            self.assertEqual([entry["id"] for entry in history], ["new-2", "new-1"])
            self.assertFalse(old_image.exists())
            self.assertFalse(old_video.exists())
            self.assertEqual(errors, [])

    def test_delete_alert_history_entry_removes_record_and_media(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _, log_dir, _ = self.configure_store(temp_dir, history_limit=10)
            log_dir.mkdir(parents=True, exist_ok=True)
            image = log_dir / "alert_delete.jpg"
            image.write_bytes(b"image")

            alert_history_store.add_alert_history({
                "id": "delete-me",
                "image_path": "logs/alert_delete.jpg",
            })

            self.assertTrue(alert_history_store.delete_alert_history_entry("delete-me"))
            self.assertEqual(alert_history_store.get_alert_history_snapshot(), [])
            self.assertFalse(image.exists())

    def test_restore_alert_history_from_file_saves_backup_entries_with_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root, log_dir, _ = self.configure_store(temp_dir, history_limit=10)
            backup_file = root / "alert_history_backup.json"
            backup_file.write_text(json.dumps([
                {"id": "keep-1"},
                {"id": "keep-2"},
                {"bad": "entry"},
                "not-a-dict",
            ]), encoding="utf-8")

            restored = alert_history_store.restore_alert_history_from_file(str(backup_file), limit=2)

            self.assertEqual([entry.get("id") for entry in restored], ["keep-1", "keep-2"])
            saved = json.loads((log_dir / "alert_history.json").read_text(encoding="utf-8"))
            self.assertEqual([entry.get("id") for entry in saved], ["keep-1", "keep-2"])


if __name__ == "__main__":
    unittest.main()
