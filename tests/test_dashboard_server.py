import json
import tempfile
import unittest
from pathlib import Path

from vision_bot_core.dashboard_server import (
    DashboardContext,
    normalize_dashboard_tab,
    render_dashboard_html,
    restore_selected_dashboard_backup,
)
from vision_bot_core.settings_store import DEFAULT_SETTINGS, SETTING_LABELS, SETTING_LIMITS, SETTING_UNITS


def make_dashboard_context(settings_backup_path="", history_backup_path="", restored=None):
    if restored is None:
        restored = []

    return DashboardContext(
        host="127.0.0.1",
        port=8765,
        url="http://127.0.0.1:8765",
        log_dir="logs",
        settings_limits=SETTING_LIMITS,
        setting_labels=SETTING_LABELS,
        setting_units=SETTING_UNITS,
        history_limit_choices=(10, 50, 100),
        bot_start_time=0,
        get_settings_snapshot=lambda: DEFAULT_SETTINGS.copy(),
        get_alert_history_snapshot=lambda limit=None: [],
        get_camera_status=lambda: (False, "Camera chưa kiểm tra"),
        is_radar_active=lambda: False,
        format_size=lambda size: f"{size} B",
        get_directory_size=lambda path: 0,
        format_duration=lambda seconds: "1s",
        tail_error_log=lambda: "no error",
        format_timestamp=lambda timestamp: f"time-{timestamp}",
        last_alert_timestamp=lambda: None,
        text_preview=lambda text, max_length=320: text or "",
        is_safe_alert_media_path=lambda path: False,
        absolute_from_base=lambda path: path,
        delete_alert_history_entry=lambda alert_id: False,
        update_setting=lambda name, value: None,
        trim_alert_history=lambda limit: None,
        list_backups=lambda limit=20: [
            {
                "label": "settings",
                "reason": "before_setting",
                "created_at": 1,
                "size": 12,
                "filename": "settings_before_setting.json",
                "path": settings_backup_path,
            },
            {
                "label": "alert_history",
                "reason": "before_clear_history",
                "created_at": 2,
                "size": 24,
                "filename": "alert_history_before_clear_history.json",
                "path": history_backup_path,
            },
        ],
        restore_settings_backup=lambda backup: restored.append(("settings", backup)) or {"backup": backup},
        restore_alert_history_backup=lambda backup: restored.append(("history", backup)) or {
            "backup": backup,
            "restored_count": 2,
        },
        restore_latest_settings_backup=lambda: None,
        restore_latest_alert_history_backup=lambda: None,
        clamp_int=lambda value, default, min_value, max_value: default,
        log_error=lambda context, error=None: None,
    )


class DashboardServerTests(unittest.TestCase):
    def test_backup_tab_is_valid_dashboard_tab(self):
        self.assertEqual(normalize_dashboard_tab("backups"), "backups")

    def test_render_backup_tab_shows_backups_and_restore_forms(self):
        html = render_dashboard_html(make_dashboard_context(), active_tab="backups")

        self.assertIn("Backup", html)
        self.assertIn("settings_before_setting.json", html)
        self.assertIn("alert_history_before_clear_history.json", html)
        self.assertIn('/restore-settings-backup', html)
        self.assertIn('/restore-history-backup', html)
        self.assertIn('/restore-selected-backup', html)
        self.assertIn("Xem nội dung", html)
        self.assertIn("Khôi phục file này", html)

    def test_render_settings_backup_detail_shows_setting_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_path = Path(temp_dir) / "settings_before_setting.json"
            backup_path.write_text(json.dumps({
                "motion_area_threshold": 1234,
                "alert_cooldown_seconds": 30,
                "send_video": False,
            }), encoding="utf-8")

            html = render_dashboard_html(
                make_dashboard_context(settings_backup_path=str(backup_path)),
                active_tab="backups",
                backup_filename="settings_before_setting.json",
            )

            self.assertIn("Nội dung backup", html)
            self.assertIn("1234", html)
            self.assertIn("Gửi video cảnh báo", html)
            self.assertIn("TẮT", html)

    def test_render_history_backup_detail_shows_summary_and_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_path = Path(temp_dir) / "alert_history_before_clear_history.json"
            backup_path.write_text(json.dumps([
                {"timestamp": 2, "video_status": "Có video", "analysis": "motion one"},
                {"timestamp": 1, "video_status": "Không có video", "analysis": "motion two"},
            ]), encoding="utf-8")

            html = render_dashboard_html(
                make_dashboard_context(history_backup_path=str(backup_path)),
                active_tab="backups",
                backup_filename="alert_history_before_clear_history.json",
            )

            self.assertIn("Số cảnh báo", html)
            self.assertIn("2", html)
            self.assertIn("motion one", html)
            self.assertIn("time-2.0", html)

    def test_restore_selected_dashboard_backup_uses_selected_file(self):
        restored = []
        ctx = make_dashboard_context(restored=restored)

        result = restore_selected_dashboard_backup(ctx, "settings_before_setting.json")

        self.assertEqual(result["status"], "1")
        self.assertEqual(result["kind"], "settings")
        self.assertEqual(restored[0][0], "settings")
        self.assertEqual(restored[0][1]["filename"], "settings_before_setting.json")

    def test_restore_selected_dashboard_backup_restores_history_file(self):
        restored = []
        ctx = make_dashboard_context(restored=restored)

        result = restore_selected_dashboard_backup(ctx, "alert_history_before_clear_history.json")

        self.assertEqual(result["status"], "1")
        self.assertEqual(result["kind"], "history")
        self.assertEqual(result["count"], "2")
        self.assertEqual(restored[0][0], "history")

    def test_restore_selected_dashboard_backup_rejects_unknown_file(self):
        result = restore_selected_dashboard_backup(make_dashboard_context(), "missing.json")

        self.assertEqual(result["status"], "0")


if __name__ == "__main__":
    unittest.main()
