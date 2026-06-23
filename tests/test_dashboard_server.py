import http.client
import json
import os
import tempfile
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

from vision_bot_core.dashboard_server import (
    DashboardContext,
    build_dashboard_history_zip,
    delete_selected_dashboard_backup,
    get_dashboard_backup_file,
    get_dashboard_history_export_files,
    normalize_dashboard_tab,
    render_dashboard_html,
    restore_selected_dashboard_backup,
    update_dashboard_settings,
    make_dashboard_handler,
)
from vision_bot_core.settings_store import DEFAULT_SETTINGS, SETTING_LABELS, SETTING_LIMITS, SETTING_UNITS


def make_dashboard_context(
    settings_backup_path="",
    history_backup_path="",
    restored=None,
    deleted=None,
    log_dir="logs",
    history_entries=None,
    settings_snapshot=None,
    updated=None,
    use_real_clamp=False,
):
    if restored is None:
        restored = []
    if deleted is None:
        deleted = []
    if history_entries is None:
        history_entries = []
    if settings_snapshot is None:
        settings_snapshot = DEFAULT_SETTINGS.copy()
    if updated is None:
        updated = {}

    if use_real_clamp:
        def clamp_int(value, default, min_value, max_value):
            try:
                number = int(value)
            except (TypeError, ValueError):
                number = default
            return max(min_value, min(number, max_value))
    else:
        def clamp_int(value, default, min_value, max_value):
            return default

    return DashboardContext(
        host="127.0.0.1",
        port=8765,
        url="http://127.0.0.1:8765",
        log_dir=log_dir,
        settings_limits=SETTING_LIMITS,
        setting_labels=SETTING_LABELS,
        setting_units=SETTING_UNITS,
        history_limit_choices=(10, 50, 100),
        bot_start_time=0,
        get_settings_snapshot=lambda: dict(settings_snapshot),
        get_alert_history_snapshot=lambda limit=None: list(history_entries),
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
        update_setting=lambda name, value: updated.__setitem__(name, value),
        trim_alert_history=lambda limit: None,
        scan_cameras=lambda: "scan result",
        test_camera=lambda: {"ok": False, "message": "test result", "path": ""},
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
        delete_backup=lambda backup: deleted.append(backup) or True,
        clamp_int=clamp_int,
        log_error=lambda context, error=None: None,
        get_dashboard_password=lambda: ""
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
        self.assertIn('/delete-backup', html)
        self.assertIn('/download-backup', html)
        self.assertIn("Xem nội dung", html)
        self.assertIn("Tải xuống", html)
        self.assertIn("Khôi phục file này", html)
        self.assertIn("Đang hiển thị 2/2", html)

    def test_render_backup_tab_filters_by_settings(self):
        html = render_dashboard_html(
            make_dashboard_context(),
            active_tab="backups",
            backup_filter="settings",
        )

        self.assertIn("settings_before_setting.json", html)
        self.assertNotIn("alert_history_before_clear_history.json", html)
        self.assertIn("Đang hiển thị 1/2", html)
        self.assertIn("backup_filter=settings", html)

    def test_render_backup_tab_filters_by_history(self):
        html = render_dashboard_html(
            make_dashboard_context(),
            active_tab="backups",
            backup_filter="history",
        )

        self.assertNotIn("settings_before_setting.json", html)
        self.assertIn("alert_history_before_clear_history.json", html)
        self.assertIn("Đang hiển thị 1/2", html)
        self.assertIn("backup_filter=history", html)

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

    def test_delete_selected_dashboard_backup_uses_selected_file(self):
        deleted = []
        ctx = make_dashboard_context(deleted=deleted)

        self.assertTrue(delete_selected_dashboard_backup(ctx, "settings_before_setting.json"))

        self.assertEqual(deleted[0]["filename"], "settings_before_setting.json")

    def test_delete_selected_dashboard_backup_rejects_unknown_file(self):
        deleted = []
        ctx = make_dashboard_context(deleted=deleted)

        self.assertFalse(delete_selected_dashboard_backup(ctx, "missing.json"))
        self.assertEqual(deleted, [])

    def test_get_dashboard_backup_file_returns_only_known_existing_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_path = Path(temp_dir) / "settings_before_setting.json"
            backup_path.write_text("{}", encoding="utf-8")
            ctx = make_dashboard_context(settings_backup_path=str(backup_path))

            backup = get_dashboard_backup_file(ctx, "settings_before_setting.json")

            self.assertIsNotNone(backup)
            self.assertEqual(backup["path"], str(backup_path))
            self.assertIsNone(get_dashboard_backup_file(ctx, "missing.json"))

    def test_render_history_tab_shows_zip_download_link(self):
        html = render_dashboard_html(make_dashboard_context(), active_tab="history")

        self.assertIn('/download-history-zip', html)
        self.assertIn("Tải lịch sử .zip", html)

    def test_render_settings_tab_includes_camera_controls(self):
        html = render_dashboard_html(make_dashboard_context(), active_tab="settings")

        self.assertIn("camera_index", html)
        self.assertIn("camera_width", html)
        self.assertIn("camera_height", html)
        self.assertIn("camera_fps", html)
        self.assertIn("camera_rotation", html)
        self.assertIn("person_filter_enabled", html)
        self.assertIn("daily_summary_enabled", html)
        self.assertIn("daily_summary_hour", html)
        self.assertIn("daily_summary_minute", html)
        self.assertIn("send_screen_record", html)
        self.assertIn("send_input_camera_photo", html)
        self.assertIn("/scan-cameras", html)
        self.assertIn("/test-camera", html)

    def test_render_settings_tab_includes_quiet_hours_controls(self):
        html = render_dashboard_html(make_dashboard_context(), active_tab="settings")

        self.assertIn("quiet_hours_enabled", html)
        self.assertIn("quiet_hours_start_hour", html)
        self.assertIn("quiet_hours_end_hour", html)

    def test_render_status_tab_shows_quiet_hours_row(self):
        snapshot = DEFAULT_SETTINGS.copy()
        snapshot["quiet_hours_enabled"] = True
        snapshot["quiet_hours_start_hour"] = 22
        snapshot["quiet_hours_end_hour"] = 7
        html = render_dashboard_html(
            make_dashboard_context(settings_snapshot=snapshot),
            active_tab="status",
        )

        self.assertIn("Giờ yên lặng", html)
        self.assertIn("BẬT 22:00-07:00", html)

    def test_update_dashboard_settings_applies_quiet_hours(self):
        updated = {}
        ctx = make_dashboard_context(updated=updated, use_real_clamp=True)

        update_dashboard_settings(ctx, {
            "quiet_hours_enabled": ["true"],
            "quiet_hours_start_hour": ["23"],
            "quiet_hours_end_hour": ["6"],
        })

        self.assertTrue(updated["quiet_hours_enabled"])
        self.assertEqual(updated["quiet_hours_start_hour"], 23)
        self.assertEqual(updated["quiet_hours_end_hour"], 6)

    def test_update_dashboard_settings_clamps_quiet_hours_out_of_range(self):
        updated = {}
        ctx = make_dashboard_context(updated=updated, use_real_clamp=True)

        update_dashboard_settings(ctx, {
            "quiet_hours_start_hour": ["99"],
            "quiet_hours_end_hour": ["-5"],
        })

        self.assertEqual(updated["quiet_hours_start_hour"], 23)
        self.assertEqual(updated["quiet_hours_end_hour"], 0)

    def test_render_status_tab_includes_health_cards(self):
        html = render_dashboard_html(make_dashboard_context(), active_tab="status")

        self.assertIn("Sức khỏe hệ thống", html)
        self.assertIn("Bot", html)
        self.assertIn("ĐANG CHẠY", html)
        self.assertIn("Camera", html)
        self.assertIn("CHẾT", html)
        self.assertIn("Tóm tắt hằng ngày", html)
        self.assertIn("Lần cảnh báo gần nhất", html)

    def test_render_history_tab_paginates_alerts(self):
        entries = [
            {"id": f"alert-{index}", "timestamp": index, "analysis": f"record {index:03d}"}
            for index in range(25)
        ]
        html = render_dashboard_html(
            make_dashboard_context(history_entries=entries),
            active_tab="history",
            history_page=2,
        )

        self.assertIn("Trang 2/3", html)
        self.assertIn("Đang hiển thị 11-20/25", html)
        self.assertIn("record 014", html)
        self.assertIn("record 005", html)
        self.assertNotIn("record 024", html)
        self.assertNotIn("record 004", html)
        self.assertIn("page=1", html)
        self.assertIn("page=3", html)
        self.assertIn('name="page" value="2"', html)

    def test_render_history_tab_clamps_page_to_last_page(self):
        entries = [
            {"id": f"alert-{index}", "timestamp": index, "analysis": f"record {index:03d}"}
            for index in range(12)
        ]
        html = render_dashboard_html(
            make_dashboard_context(history_entries=entries),
            active_tab="history",
            history_page=99,
        )

        self.assertIn("Trang 2/2", html)
        self.assertIn("record 001", html)
        self.assertIn("record 000", html)
        self.assertNotIn("record 011", html)

    def test_build_dashboard_history_zip_contains_history_files_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"
            log_dir.mkdir()
            (log_dir / "alert_history.json").write_text("[]", encoding="utf-8")
            (log_dir / "alert_20260527_101010.jpg").write_bytes(b"jpg")
            (log_dir / "alert_20260527_101010.mp4").write_bytes(b"mp4")
            (log_dir / "bot_errors.log").write_text("error", encoding="utf-8")
            (log_dir / "notes.txt").write_text("skip", encoding="utf-8")
            backup_dir = log_dir / "backups"
            backup_dir.mkdir()
            (backup_dir / "settings_before_setting.json").write_text("{}", encoding="utf-8")
            ctx = make_dashboard_context(log_dir=str(log_dir))

            export_names = [archive_name for _, archive_name in get_dashboard_history_export_files(ctx)]
            zip_path, written_count = build_dashboard_history_zip(ctx)
            try:
                with zipfile.ZipFile(zip_path) as zip_file:
                    zip_names = sorted(zip_file.namelist())
            finally:
                os.remove(zip_path)

        expected_names = [
            "logs/alert_20260527_101010.jpg",
            "logs/alert_20260527_101010.mp4",
            "logs/alert_history.json",
            "logs/bot_errors.log",
        ]
        self.assertEqual(export_names, expected_names)
        self.assertEqual(zip_names, expected_names)
        self.assertEqual(written_count, len(expected_names))

    def test_dashboard_cookie_auth_required_when_password_set(self):
        ctx = make_dashboard_context()
        ctx.dashboard_password = "testpassword"
        
        handler_class = make_dashboard_handler(ctx)
        
        class TestHandler(handler_class):
            def __init__(self):
                self.headers = {}
                self.path = "/"
                import io
                self.wfile = io.BytesIO()
                self.responses = []
                self.headers_sent = {}
            def send_response(self, code, message=None):
                self.responses.append(code)
            def send_header(self, name, val):
                self.headers_sent[name] = val
            def end_headers(self):
                pass
        
        ctx.get_dashboard_password = lambda: ""
        handler = TestHandler()
        self.assertTrue(handler.check_auth())
        
        ctx.get_dashboard_password = lambda: "testpassword"
        handler = TestHandler()
        self.assertFalse(handler.check_auth())
        self.assertEqual(handler.responses, [303])
        self.assertEqual(handler.headers_sent.get("Location"), "/login")
        
        handler = TestHandler()
        handler.headers = {"Cookie": "session=wrong"}
        self.assertFalse(handler.check_auth())
        self.assertEqual(handler.responses, [303])

        # Cookie tĩnh đoán được không còn bypass được xác thực.
        handler = TestHandler()
        handler.headers = {"Cookie": "session=authorized"}
        self.assertFalse(handler.check_auth())

        # Chỉ token phiên ngẫu nhiên thật mới được chấp nhận.
        handler = TestHandler()
        handler.headers = {"Cookie": f"session={handler_class.session_token}"}
        self.assertTrue(handler.check_auth())

        handler = TestHandler()
        handler.path = "/login"
        self.assertTrue(handler.check_auth())

    def test_dashboard_session_token_is_random_per_handler(self):
        token_a = make_dashboard_handler(make_dashboard_context()).session_token
        token_b = make_dashboard_handler(make_dashboard_context()).session_token

        self.assertNotEqual(token_a, token_b)
        self.assertNotEqual(token_a, "authorized")
        self.assertGreaterEqual(len(token_a), 32)


class DashboardHttpAuthTests(unittest.TestCase):
    PASSWORD = "s3cret-pass"

    def setUp(self):
        ctx = make_dashboard_context()
        ctx.get_dashboard_password = lambda: self.PASSWORD
        self.handler_class = make_dashboard_handler(ctx)
        self.session_token = self.handler_class.session_token
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler_class)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            payload = response.read().decode("utf-8", errors="replace")
            return response.status, dict(response.getheaders()), payload
        finally:
            conn.close()

    def login_body(self, password):
        from urllib.parse import urlencode
        return urlencode({"password": password})

    def test_root_without_cookie_redirects_to_login(self):
        status, headers, _ = self.request("GET", "/")
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("Location"), "/login")

    def test_login_page_is_served_without_auth(self):
        status, _, body = self.request("GET", "/login")
        self.assertEqual(status, 200)
        self.assertIn("Đăng nhập", body)

    def test_forged_static_cookie_is_rejected(self):
        status, headers, _ = self.request("GET", "/", headers={"Cookie": "session=authorized"})
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("Location"), "/login")

    def test_login_wrong_password_shows_error(self):
        status, _, body = self.request(
            "POST",
            "/login",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=self.login_body("wrong"),
        )
        self.assertEqual(status, 200)
        self.assertIn("không chính xác", body)

    def test_login_correct_password_sets_session_cookie(self):
        status, headers, _ = self.request(
            "POST",
            "/login",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=self.login_body(self.PASSWORD),
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("Location"), "/")
        set_cookie = headers.get("Set-Cookie", "")
        self.assertIn(f"session={self.session_token}", set_cookie)
        self.assertIn("HttpOnly", set_cookie)

    def test_valid_session_cookie_grants_access(self):
        status, _, body = self.request(
            "GET",
            "/",
            headers={"Cookie": f"session={self.session_token}"},
        )
        self.assertEqual(status, 200)
        self.assertIn("Vision Bot Dashboard", body)

    def test_protected_media_without_auth_returns_401(self):
        status, _, body = self.request("GET", "/media?path=logs/secret.jpg")
        self.assertEqual(status, 401)
        self.assertIn("Unauthorized", body)


if __name__ == "__main__":
    unittest.main()
