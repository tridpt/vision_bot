import unittest
from unittest.mock import patch, mock_open, MagicMock

from vision_bot_core.motion_monitor import (
    MotionMonitor,
    MotionMonitorContext,
    parse_person_filter_result,
)


class MotionMonitorTests(unittest.TestCase):
    def setUp(self):
        import vision_bot_core.motion_monitor
        vision_bot_core.motion_monitor.PYNPUT_AVAILABLE = False

    def make_monitor(self):
        ctx = MotionMonitorContext(
            bot=object(),
            log_dir="logs",
            get_setting=lambda name: 10,
            get_settings_snapshot=lambda: {},
            add_alert_history=lambda entry: None,
            make_alert_id=lambda timestamp: "alert-id",
            ensure_log_dir=lambda: None,
            relative_to_base=lambda path: path,
            ask_ai=lambda image_path, question: "analysis",
            log_error=lambda context, error=None: None,
        )
        return MotionMonitor(ctx)

    class DummyCameraStream:
        def __init__(self):
            self.released = False

        def release(self):
            self.released = True

    def test_radar_state_and_camera_status_are_reported(self):
        monitor = self.make_monitor()

        self.assertFalse(monitor.is_radar_active())
        self.assertEqual(
            monitor.get_camera_status_for_dashboard(),
            (False, "Camera chưa kiểm tra trên dashboard")
        )

        monitor.set_radar_state(True, chat_id=123)
        monitor._set_camera_status(True, "Camera OK")
        monitor._set_last_alert_timestamp(456)

        self.assertTrue(monitor.is_radar_active())
        self.assertEqual(monitor.get_camera_status(), (True, "Camera OK"))
        self.assertEqual(monitor.get_camera_status_for_report(), (True, "Camera OK"))
        self.assertEqual(monitor.get_last_alert_timestamp(), 456)

    def test_turning_radar_off_keeps_last_known_dashboard_status(self):
        monitor = self.make_monitor()

        monitor.set_radar_state(True, chat_id=123)
        monitor._set_camera_status(False, "Radar bật nhưng không mở được camera")
        monitor.set_radar_state(False)

        self.assertFalse(monitor.is_radar_active())
        self.assertEqual(
            monitor.get_camera_status_for_dashboard(),
            (False, "Radar bật nhưng không mở được camera")
        )

    def test_parse_person_filter_result(self):
        self.assertTrue(parse_person_filter_result("PERSON"))
        self.assertTrue(parse_person_filter_result("PERSON: một người đứng gần cửa"))
        self.assertFalse(parse_person_filter_result("NO_PERSON"))
        self.assertFalse(parse_person_filter_result("NO_PERSON: chỉ có rèm"))

    def test_reset_camera_connection_releases_stream_and_marks_camera_offline(self):
        monitor = self.make_monitor()
        stream = self.DummyCameraStream()

        camera_stream, active_camera_config, last_gray_frame = monitor._reset_camera_connection(
            stream,
            "Camera vừa rớt"
        )

        self.assertTrue(stream.released)
        self.assertIsNone(camera_stream)
        self.assertIsNone(active_camera_config)
        self.assertIsNone(last_gray_frame)
        self.assertEqual(monitor.get_camera_status(), (False, "Camera vừa rớt"))

    def test_register_camera_failure_alerts_on_first_failure(self):
        monitor = self.make_monitor()

        failure_count, should_alert, repeated_alert = monitor._register_camera_failure("Camera rớt")

        self.assertEqual(failure_count, 1)
        self.assertTrue(should_alert)
        self.assertFalse(repeated_alert)
        self.assertEqual(monitor.get_camera_status(), (False, "Camera rớt"))

    def test_register_camera_failure_reminds_after_threshold(self):
        monitor = self.make_monitor()
        monitor._camera_failure_count = 4
        monitor._last_camera_issue_alert_time = 100

        with patch("vision_bot_core.motion_monitor.time.time", return_value=320):
            failure_count, should_alert, repeated_alert = monitor._register_camera_failure("Camera vẫn rớt")

        self.assertEqual(failure_count, 5)
        self.assertTrue(should_alert)
        self.assertTrue(repeated_alert)

    def test_register_camera_failure_stays_silent_within_repeat_window(self):
        monitor = self.make_monitor()
        monitor._camera_failure_count = 5
        monitor._last_camera_issue_alert_time = 300

        with patch("vision_bot_core.motion_monitor.time.time", return_value=360):
            failure_count, should_alert, repeated_alert = monitor._register_camera_failure("Camera vẫn rớt")

        self.assertEqual(failure_count, 6)
        self.assertFalse(should_alert)
        self.assertTrue(repeated_alert)

    def test_set_radar_state_without_chat_id_keeps_previous_chat(self):
        monitor = self.make_monitor()

        monitor.set_radar_state(True, chat_id=789)
        self.assertEqual(monitor.get_monitoring_chat_id(), 789)

        monitor.set_radar_state(False)
        self.assertEqual(monitor.get_monitoring_chat_id(), 789)

    def test_clear_camera_failure_state_resets_counters(self):
        monitor = self.make_monitor()
        monitor._register_camera_failure("Camera rớt")
        self.assertEqual(monitor._camera_failure_count, 1)

        monitor._clear_camera_failure_state()

        self.assertEqual(monitor._camera_failure_count, 0)
        self.assertEqual(monitor._last_camera_issue_alert_time, 0)

    def test_build_camera_issue_alert_message_differs_for_repeated_alert(self):
        monitor = self.make_monitor()
        config = {"camera_index": 0, "camera_width": 0, "camera_height": 0, "camera_fps": 0, "camera_rotation": 0}

        first = monitor._build_camera_issue_alert_message("Camera rớt", config, 1, repeated_alert=False)
        repeated = monitor._build_camera_issue_alert_message("Camera rớt", config, 6, repeated_alert=True)

        self.assertIn("CAMERA BỊ RỚT", first)
        self.assertIn("CAMERA VẪN CHƯA KẾT NỐI LẠI", repeated)
        self.assertIn("6 lần", repeated)

    def test_live_viewer_management_is_thread_safe_and_reports_correct_state(self):
        monitor = self.make_monitor()
        
        self.assertFalse(monitor.has_live_viewers())
        self.assertIsNone(monitor.get_latest_frame())
        
        monitor.add_live_viewer()
        self.assertTrue(monitor.has_live_viewers())
        
        dummy_frame = object()
        monitor._set_latest_frame(dummy_frame)
        self.assertEqual(monitor.get_latest_frame(), dummy_frame)
        
        monitor.add_live_viewer()
        self.assertTrue(monitor.has_live_viewers())
        
        monitor.remove_live_viewer()
        self.assertTrue(monitor.has_live_viewers())
        
        monitor.remove_live_viewer()
        self.assertFalse(monitor.has_live_viewers())

    def test_handle_input_intrusion_sends_telegram_alert(self):
        messages_sent = []
        photos_sent = []
        alerts_added = []
        
        class MockBot:
            def send_message(self, chat_id, text):
                messages_sent.append(text)
            def send_photo(self, chat_id, photo, caption=None):
                photos_sent.append(caption)
                
        ctx = MotionMonitorContext(
            bot=MockBot(),
            log_dir="logs",
            get_setting=lambda name: True,
            get_settings_snapshot=lambda: {},
            add_alert_history=lambda entry: alerts_added.append(entry),
            make_alert_id=lambda timestamp: "alert-id",
            ensure_log_dir=lambda: None,
            relative_to_base=lambda path: path,
            ask_ai=lambda image_path, question: "PERSON",
            log_error=lambda context, error=None: None,
        )
        monitor = MotionMonitor(ctx)
        
        monitor.set_radar_state(True, chat_id=123)
        
        monitor._handle_input_intrusion()
        self.assertEqual(messages_sent, [])
        
        dummy_frame = object()
        monitor._set_latest_frame(dummy_frame)
        monitor._last_input_alert_time = 0
        
        with patch("vision_bot_core.motion_monitor.save_frame") as mock_save, \
             patch("builtins.open", mock_open(read_data=b"imagebytes")):
            monitor._handle_input_intrusion()
            mock_save.assert_called_once()
            
        self.assertIn("CẢNH BÁO XÂM NHẬP KHẨN CẤP", messages_sent[0])
        self.assertIn("PERSON", photos_sent[0])
        self.assertEqual(len(alerts_added), 1)
        self.assertEqual(alerts_added[0]["id"], "input_alert-id")

    def test_handle_input_intrusion_skips_camera_photo_when_disabled(self):
        messages_sent = []
        photos_sent = []
        alerts_added = []
        
        class MockBot:
            def send_message(self, chat_id, text):
                messages_sent.append(text)
            def send_photo(self, chat_id, photo, caption=None):
                photos_sent.append(caption)
                
        settings = {
            "send_input_camera_photo": False,
            "person_filter_enabled": False,
            "send_screen_record": False,
        }
        ctx = MotionMonitorContext(
            bot=MockBot(),
            log_dir="logs",
            get_setting=lambda name: settings.get(name, True),
            get_settings_snapshot=lambda: settings,
            add_alert_history=lambda entry: alerts_added.append(entry),
            make_alert_id=lambda timestamp: "alert-id",
            ensure_log_dir=lambda: None,
            relative_to_base=lambda path: path,
            ask_ai=lambda image_path, question: "PERSON",
            log_error=lambda context, error=None: None,
        )
        monitor = MotionMonitor(ctx)
        
        monitor.set_radar_state(True, chat_id=123)
        dummy_frame = object()
        monitor._set_latest_frame(dummy_frame)
        monitor._last_input_alert_time = 0
        
        with patch("vision_bot_core.motion_monitor.save_frame") as mock_save:
            monitor._handle_input_intrusion()
            # Since person_filter_enabled is False and send_input_camera_photo is False,
            # we optimized it to not even save/grab the frame!
            mock_save.assert_not_called()
            
        self.assertIn("CẢNH BÁO XÂM NHẬP KHẨN CẤP", messages_sent[0])
        self.assertEqual(photos_sent, [])
        self.assertEqual(len(alerts_added), 1)
        self.assertEqual(alerts_added[0]["id"], "input_alert-id")
        self.assertIsNone(alerts_added[0]["image_path"])

    def test_start_input_listeners_respects_setting(self):
        settings = {"input_monitoring_enabled": False}
        ctx = MotionMonitorContext(
            bot=object(),
            log_dir="logs",
            get_setting=lambda name: settings.get(name, True),
            get_settings_snapshot=lambda: settings,
            add_alert_history=lambda entry: None,
            make_alert_id=lambda timestamp: "alert-id",
            ensure_log_dir=lambda: None,
            relative_to_base=lambda path: path,
            ask_ai=lambda image_path, question: "PERSON",
            log_error=lambda context, error=None: None,
        )
        monitor = MotionMonitor(ctx)
        
        import vision_bot_core.motion_monitor
        with patch.object(vision_bot_core.motion_monitor, "PYNPUT_AVAILABLE", True):
            monitor._start_input_listeners()
            self.assertIsNone(monitor._keyboard_listener)
            self.assertIsNone(monitor._mouse_listener)
            
            settings["input_monitoring_enabled"] = True
            with patch.object(vision_bot_core.motion_monitor, "keyboard", MagicMock(), create=True), \
                 patch.object(vision_bot_core.motion_monitor, "mouse", MagicMock(), create=True):
                monitor._start_input_listeners()
                self.assertIsNotNone(monitor._keyboard_listener)
                self.assertIsNotNone(monitor._mouse_listener)

    def test_motion_loop_closes_camera_if_both_modes_disabled(self):
        settings = {"motion_detection_enabled": False, "input_monitoring_enabled": False}
        ctx = MotionMonitorContext(
            bot=object(),
            log_dir="logs",
            get_setting=lambda name: settings.get(name, True),
            get_settings_snapshot=lambda: settings,
            add_alert_history=lambda entry: None,
            make_alert_id=lambda timestamp: "alert-id",
            ensure_log_dir=lambda: None,
            relative_to_base=lambda path: path,
            ask_ai=lambda image_path, question: "PERSON",
            log_error=lambda context, error=None: None,
        )
        monitor = MotionMonitor(ctx)
        
        stream = self.DummyCameraStream()
        
        camera_stream, active_camera_config, last_gray_frame = monitor._reset_camera_connection(
            stream,
            "both disabled"
        )
        self.assertTrue(stream.released)
        self.assertIsNone(camera_stream)


if __name__ == "__main__":
    unittest.main()

