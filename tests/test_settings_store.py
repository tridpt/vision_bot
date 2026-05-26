import json
import tempfile
import unittest
from pathlib import Path

from vision_bot_core import settings_store


class SettingsStoreTests(unittest.TestCase):
    def test_update_setting_persists_to_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"

            settings_store.configure_settings_store(str(settings_path))
            settings_store.update_setting("alert_cooldown_seconds", 25)

            self.assertEqual(settings_store.get_setting("alert_cooldown_seconds"), 25)
            saved = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["alert_cooldown_seconds"], 25)

            settings_store.configure_settings_store(str(settings_path))
            self.assertEqual(settings_store.get_setting("alert_cooldown_seconds"), 25)

    def test_restore_settings_from_file_persists_normalized_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path = root / "settings.json"
            backup_path = root / "settings_backup.json"
            backup_path.write_text(json.dumps({
                "alert_cooldown_seconds": 30,
                "alert_history_limit": 100,
                "send_video": False,
            }), encoding="utf-8")

            settings_store.configure_settings_store(str(settings_path))
            restored = settings_store.restore_settings_from_file(str(backup_path))

            self.assertEqual(restored["alert_cooldown_seconds"], 30)
            self.assertEqual(restored["alert_history_limit"], 100)
            self.assertFalse(restored["send_video"])

            saved = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["alert_cooldown_seconds"], 30)
            self.assertEqual(settings_store.get_setting("alert_cooldown_seconds"), 30)

    def test_normalize_settings_clamps_values_and_snaps_history_limit(self):
        normalized = settings_store.normalize_settings({
            "motion_area_threshold": 1,
            "alert_cooldown_seconds": 9999,
            "alert_video_seconds": "8",
            "alert_video_fps": "bad",
            "alert_history_limit": 73,
            "send_video": "off",
            "use_gemini_analysis": "yes",
        })

        self.assertEqual(normalized["motion_area_threshold"], 500)
        self.assertEqual(normalized["alert_cooldown_seconds"], 3600)
        self.assertEqual(normalized["alert_video_seconds"], 8)
        self.assertEqual(normalized["alert_video_fps"], 10)
        self.assertEqual(normalized["alert_history_limit"], 50)
        self.assertFalse(normalized["send_video"])
        self.assertTrue(normalized["use_gemini_analysis"])


if __name__ == "__main__":
    unittest.main()
