import unittest
from unittest.mock import patch

from vision_bot_core.motion_monitor import (
    MotionMonitor,
    MotionMonitorContext,
    parse_person_filter_result,
)


class MotionMonitorTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
