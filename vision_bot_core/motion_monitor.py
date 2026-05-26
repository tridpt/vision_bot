import os
import threading
import time
from dataclasses import dataclass

from .camera_tools import (
    build_motion_gray,
    check_camera_once,
    has_large_motion,
    open_camera,
    record_alert_video,
    save_frame,
    warm_up_camera,
)


@dataclass
class MotionMonitorContext:
    bot: object
    log_dir: str
    get_setting: object
    get_settings_snapshot: object
    add_alert_history: object
    make_alert_id: object
    ensure_log_dir: object
    relative_to_base: object
    ask_ai: object
    log_error: object


class MotionMonitor:
    def __init__(self, ctx):
        self.ctx = ctx
        self._lock = threading.Lock()
        self._auto_mode_active = False
        self._monitoring_chat_id = None
        self._camera_online = False
        self._last_camera_status = "Chưa kiểm tra camera"
        self._last_alert_timestamp = None
        self._thread = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return self._thread

        self._thread = threading.Thread(target=self._motion_detection_loop, daemon=True)
        self._thread.start()
        return self._thread

    def set_radar_state(self, active, chat_id=None):
        with self._lock:
            self._auto_mode_active = active
            if chat_id is not None:
                self._monitoring_chat_id = chat_id

    def is_radar_active(self):
        with self._lock:
            return self._auto_mode_active

    def get_camera_status_for_report(self):
        if self.is_radar_active():
            return self.get_camera_status()
        return check_camera_once()

    def get_camera_status_for_dashboard(self):
        with self._lock:
            if self._auto_mode_active:
                return self._camera_online, self._last_camera_status
            if self._last_camera_status and self._last_camera_status != "Chưa kiểm tra camera":
                return self._camera_online, self._last_camera_status
        return False, "Camera chưa kiểm tra trên dashboard"

    def get_camera_status(self):
        with self._lock:
            return self._camera_online, self._last_camera_status

    def get_last_alert_timestamp(self):
        with self._lock:
            return self._last_alert_timestamp

    def _get_monitoring_state(self):
        with self._lock:
            return self._auto_mode_active, self._monitoring_chat_id

    def _set_camera_status(self, online, status):
        with self._lock:
            self._camera_online = online
            self._last_camera_status = status

    def _set_last_alert_timestamp(self, timestamp):
        with self._lock:
            self._last_alert_timestamp = timestamp

    def _motion_detection_loop(self):
        camera_stream = None
        last_gray_frame = None
        last_alert_time = 0
        last_camera_error_log_time = 0

        while True:
            try:
                auto_mode_active, monitoring_chat_id = self._get_monitoring_state()
                if not auto_mode_active or monitoring_chat_id is None:
                    if camera_stream is not None:
                        camera_stream.release()
                        camera_stream = None
                        last_gray_frame = None
                        self._set_camera_status(False, "Camera đang nghỉ vì radar tắt")
                    time.sleep(1)
                    continue

                if camera_stream is None:
                    camera_stream = open_camera()
                    time.sleep(1.5)
                    if not camera_stream.isOpened():
                        status = "Radar bật nhưng không mở được camera"
                        self._set_camera_status(False, status)
                        if time.time() - last_camera_error_log_time > 60:
                            self.ctx.log_error(status)
                            last_camera_error_log_time = time.time()
                        camera_stream.release()
                        camera_stream = None
                        time.sleep(2)
                        continue
                    warm_up_camera(camera_stream, delay_seconds=0, buffer_reads=5)

                success, img = camera_stream.read()
                if not success:
                    status = "Radar bật nhưng không đọc được ảnh từ camera"
                    self._set_camera_status(False, status)
                    if time.time() - last_camera_error_log_time > 60:
                        self.ctx.log_error(status)
                        last_camera_error_log_time = time.time()
                    time.sleep(0.5)
                    continue
                self._set_camera_status(True, "Camera đang mở bởi radar")

                if time.time() - last_alert_time < self.ctx.get_setting("alert_cooldown_seconds"):
                    last_gray_frame = build_motion_gray(img)
                    time.sleep(0.1)
                    continue

                gray = build_motion_gray(img)

                if last_gray_frame is None:
                    last_gray_frame = gray
                    continue

                motion_area_threshold = self.ctx.get_setting("motion_area_threshold")
                co_chuyen_dong = has_large_motion(last_gray_frame, gray, motion_area_threshold)

                if co_chuyen_dong:
                    last_alert_time = time.time()
                    self._set_last_alert_timestamp(last_alert_time)
                    alert_id = self.ctx.make_alert_id(last_alert_time)
                    self.ctx.ensure_log_dir()
                    image_path = os.path.join(self.ctx.log_dir, f"alert_{alert_id}.jpg")
                    video_path = None
                    video_status = "Không ghi video"
                    analysis = "Gemini đang tắt"
                    save_frame(image_path, img)
                    self.ctx.bot.send_message(monitoring_chat_id, "🚨 BÁO ĐỘNG KÍCH HOẠT: Phát hiện có sự dịch chuyển lớn trong phòng!")

                    if self.ctx.get_setting("send_video"):
                        video_path = os.path.join(self.ctx.log_dir, f"alert_{alert_id}.mp4")
                        video_seconds = self.ctx.get_setting("alert_video_seconds")
                        video_fps = self.ctx.get_setting("alert_video_fps")
                        video_ready, video_status = record_alert_video(
                            camera_stream,
                            img,
                            video_path,
                            video_seconds,
                            video_fps
                        )
                        if video_ready:
                            try:
                                with open(video_path, 'rb') as video:
                                    self.ctx.bot.send_video(
                                        monitoring_chat_id,
                                        video,
                                        caption=f"🎥 Clip cảnh báo {video_seconds} giây\n{video_status}"
                                    )
                            except Exception as e:
                                self.ctx.log_error("Da ghi video canh bao nhung gui Telegram that bai", e)
                                self.ctx.bot.send_message(monitoring_chat_id, f"⚠️ Đã ghi video nhưng gửi Telegram thất bại: {e}")
                        else:
                            self.ctx.bot.send_message(monitoring_chat_id, f"⚠️ Không ghi được video cảnh báo: {video_status}")
                            video_path = None
                    else:
                        video_status = "Đã tắt gửi video trong setting"

                    if self.ctx.get_setting("use_gemini_analysis"):
                        try:
                            analysis = self.ctx.ask_ai(image_path, "Báo động có sự chuyển động. Đó là con người hay một con vật? Bọn họ đang định làm gì?")
                            with open(image_path, 'rb') as photo:
                                self.ctx.bot.send_photo(monitoring_chat_id, photo, caption=f"🧠 Phân tích hiện trường:\n\n{analysis}")
                        except Exception as e:
                            self.ctx.log_error("Gemini loi khi phan tich canh bao", e)
                            analysis = f"Gemini lỗi: {e}"
                            try:
                                with open(image_path, 'rb') as photo:
                                    self.ctx.bot.send_photo(monitoring_chat_id, photo, caption=f"📸 Ảnh cảnh báo\n⚠️ Gemini lỗi: {e}")
                            except Exception as send_error:
                                self.ctx.log_error("Khong gui duoc anh canh bao sau khi Gemini loi", send_error)
                    else:
                        try:
                            with open(image_path, 'rb') as photo:
                                self.ctx.bot.send_photo(monitoring_chat_id, photo, caption="📸 Ảnh cảnh báo")
                        except Exception as e:
                            self.ctx.log_error("Khong gui duoc anh canh bao khi tat Gemini", e)

                    self.ctx.add_alert_history({
                        "id": alert_id,
                        "timestamp": last_alert_time,
                        "image_path": self.ctx.relative_to_base(image_path),
                        "video_path": self.ctx.relative_to_base(video_path) if video_path else None,
                        "video_status": video_status,
                        "analysis": analysis,
                        "settings": self.ctx.get_settings_snapshot()
                    })

                    last_gray_frame = gray
                    continue

                last_gray_frame = gray
                time.sleep(0.1)
            except Exception as e:
                self.ctx.log_error("Loi trong vong lap motion_detection_loop", e)
                time.sleep(5)
