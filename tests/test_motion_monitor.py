import unittest

from vision_bot_core.motion_monitor import MotionMonitor, MotionMonitorContext


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


if __name__ == "__main__":
    unittest.main()
