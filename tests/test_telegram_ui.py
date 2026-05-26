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
        self.assertTrue(telegram_ui.build_settings_menu().keyboard)
        self.assertTrue(telegram_ui.build_restart_confirm_menu().keyboard)
        self.assertTrue(telegram_ui.build_clear_history_confirm_menu().keyboard)

    def test_formatters_include_expected_sections(self):
        self.assertIn("VISION BOT", telegram_ui.format_settings_message())
        self.assertIn("LOG", telegram_ui.format_error_log_message("line"))
        self.assertIn("Video:", telegram_ui.format_alert_history_message(
            [{"timestamp": 1, "video_status": "ok", "analysis": "motion"}],
            lambda timestamp: f"time-{timestamp}",
        ))
        self.assertIn("8000", telegram_ui.build_setting_prompt("motion_area_threshold"))

    def test_format_settings_snapshot_uses_current_values(self):
        text = telegram_ui.format_settings_snapshot({
            "motion_area_threshold": 8000,
            "alert_cooldown_seconds": 10,
            "alert_video_seconds": 7,
            "alert_video_fps": 10,
            "send_video": True,
            "use_gemini_analysis": False,
            "alert_history_limit": 50,
        })

        self.assertIn("8000", text)
        self.assertIn("10s", text)
        self.assertIn("50", text)


if __name__ == "__main__":
    unittest.main()
