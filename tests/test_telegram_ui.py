import tempfile
import unittest
from pathlib import Path

from vision_bot_core import settings_store, telegram_ui


class TelegramUiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        settings_store.configure_settings_store(str(Path(self.temp_dir.name) / "settings.json"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_build_menus_return_inline_keyboards(self):
        self.assertTrue(telegram_ui.build_main_menu().keyboard)
        backup_buttons = [
            button
            for row in telegram_ui.build_main_menu().keyboard
            for button in row
            if button.callback_data == "menu:backups"
        ]
        restore_buttons = [
            button
            for row in telegram_ui.build_main_menu().keyboard
            for button in row
            if button.callback_data == "menu:restore_settings_confirm"
        ]
        restore_history_buttons = [
            button
            for row in telegram_ui.build_main_menu().keyboard
            for button in row
            if button.callback_data == "menu:restore_history_confirm"
        ]
        self.assertEqual(len(backup_buttons), 1)
        self.assertEqual(len(restore_buttons), 1)
        self.assertEqual(len(restore_history_buttons), 1)
        self.assertTrue(telegram_ui.build_settings_menu().keyboard)
        setting_callbacks = [
            button.callback_data
            for row in telegram_ui.build_settings_menu().keyboard
            for button in row
        ]
        self.assertIn("menu:scan_cameras", setting_callbacks)
        self.assertIn("menu:test_camera", setting_callbacks)
        self.assertIn("setting:toggle_person_filter", setting_callbacks)
        self.assertTrue(telegram_ui.build_restart_confirm_menu().keyboard)
        self.assertTrue(telegram_ui.build_clear_history_confirm_menu().keyboard)
        self.assertTrue(telegram_ui.build_restore_settings_confirm_menu().keyboard)
        self.assertTrue(telegram_ui.build_restore_history_confirm_menu().keyboard)

    def test_formatters_include_expected_sections(self):
        self.assertIn("VISION BOT", telegram_ui.format_settings_message())
        self.assertIn("Camera:", telegram_ui.format_settings_message())
        self.assertIn("LOG", telegram_ui.format_error_log_message("line"))
        self.assertIn("Video:", telegram_ui.format_alert_history_message(
            [{"timestamp": 1, "video_status": "ok", "analysis": "motion"}],
            lambda timestamp: f"time-{timestamp}",
        ))
        self.assertIn("BACKUP", telegram_ui.format_backup_list_message(
            [{"label": "settings", "reason": "before_setting", "created_at": 1, "size": 12, "filename": "settings.json"}],
            lambda timestamp: f"time-{timestamp}",
            lambda size: f"{size} B",
        ))
        self.assertIn("8000", telegram_ui.build_setting_prompt("motion_area_threshold"))
        self.assertIn("0, 90, 180, 270", telegram_ui.build_setting_prompt("camera_rotation"))

    def test_format_settings_snapshot_uses_current_values(self):
        text = telegram_ui.format_settings_snapshot({
            "motion_area_threshold": 8000,
            "alert_cooldown_seconds": 10,
            "alert_video_seconds": 7,
            "alert_video_fps": 10,
            "send_video": True,
            "use_gemini_analysis": False,
            "alert_history_limit": 50,
            "camera_index": 1,
            "camera_width": 1280,
            "camera_height": 720,
            "camera_fps": 30,
            "camera_rotation": 180,
            "person_filter_enabled": True,
        })

        self.assertIn("8000", text)
        self.assertIn("10s", text)
        self.assertIn("50", text)
        self.assertIn("1280x720", text)
        self.assertIn("180", text)
        self.assertIn("Lọc người", text)


if __name__ == "__main__":
    unittest.main()
