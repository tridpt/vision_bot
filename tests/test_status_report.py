import tempfile
import time
import unittest
from pathlib import Path

from vision_bot_core.status_report import (
    StatusReportContext,
    format_duration,
    format_size,
    format_status_message,
    get_directory_size,
)


class StatusReportTests(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(format_duration(0), "0 giây")
        self.assertEqual(format_duration(65), "1 phút 5 giây")
        self.assertEqual(format_duration(3661), "1 giờ 1 phút 1 giây")

    def test_format_size(self):
        self.assertEqual(format_size(512), "512 B")
        self.assertEqual(format_size(1024), "1.0 KB")
        self.assertEqual(format_size(1024 * 1024), "1.0 MB")

    def test_get_directory_size_counts_nested_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir()
            (root / "a.bin").write_bytes(b"a" * 10)
            (nested / "b.bin").write_bytes(b"b" * 15)

            self.assertEqual(get_directory_size(str(root)), 25)
            self.assertEqual(get_directory_size(str(root / "missing")), 0)

    def test_format_status_message_uses_context_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "log.bin").write_bytes(b"x" * 1024)
            ctx = StatusReportContext(
                bot_start_time=time.time() - 65,
                dashboard_url="http://127.0.0.1:8765",
                log_dir=temp_dir,
                get_camera_status=lambda: (True, "Camera OK"),
                is_radar_active=lambda: True,
                get_last_alert_timestamp=lambda: 123,
                get_alert_history_count=lambda: 2,
                get_settings_snapshot=lambda: {"alert_history_limit": 50},
                format_timestamp=lambda timestamp: f"time-{timestamp}",
                format_settings_snapshot=lambda settings: "settings-summary",
                is_bot_running=lambda: True,
            )

            message = format_status_message(ctx)

            self.assertIn("Bot: ĐANG CHẠY", message)
            self.assertIn("Radar: BẬT", message)
            self.assertIn("Camera: SỐNG", message)
            self.assertIn("Camera OK", message)
            self.assertIn("time-123", message)
            self.assertIn("Lần cảnh báo gần nhất", message)
            self.assertIn("2/50", message)
            self.assertIn("1.0 KB", message)
            self.assertIn("http://127.0.0.1:8765", message)
            self.assertIn("settings-summary", message)


if __name__ == "__main__":
    unittest.main()
