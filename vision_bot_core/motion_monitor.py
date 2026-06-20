import os
import threading
import time
from dataclasses import dataclass

from .camera_tools import (
    build_motion_gray,
    check_camera_once,
    format_camera_config,
    normalize_camera_config,
    has_large_motion,
    open_camera,
    record_alert_video,
    save_frame,
    transform_camera_frame,
    warm_up_camera,
)
from .status_report import is_within_quiet_hours

try:
    from pynput import keyboard, mouse
    PYNPUT_AVAILABLE = True
except Exception:
    PYNPUT_AVAILABLE = False


PERSON_FILTER_PROMPT = (
    "Bạn là bộ lọc cảnh báo an ninh. Chỉ trả lời đúng một từ: PERSON hoặc NO_PERSON.\n"
    "Trả lời PERSON nếu trong ảnh có con người thật, dù chỉ thấy một phần cơ thể.\n"
    "Trả lời NO_PERSON nếu không thấy người rõ ràng, chỉ thấy đồ vật, ánh sáng, rèm, màn hình, thú cưng hoặc nhiễu."
)


def parse_person_filter_result(text):
    normalized = " ".join(str(text or "").strip().upper().replace("-", "_").split())
    if not normalized:
        return False
    first_token = normalized.split(" ", 1)[0].strip(":.")
    if first_token in ("NO_PERSON", "NO"):
        return False
    if first_token == "PERSON":
        return True
    if normalized.startswith("NO_PERSON") or "NO_PERSON" in normalized:
        return False
    return "PERSON" in normalized


CAMERA_RECONNECT_ALERT_FAILURE_THRESHOLD = 5
CAMERA_RECONNECT_ALERT_REPEAT_SECONDS = 120


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
        self._camera_failure_count = 0
        self._last_camera_issue_alert_time = 0
        self._thread = None
        self._live_viewers = 0
        self._last_frame = None
        self._keyboard_listener = None
        self._mouse_listener = None
        self._last_input_alert_time = 0

    def add_live_viewer(self):
        with self._lock:
            self._live_viewers += 1

    def remove_live_viewer(self):
        with self._lock:
            self._live_viewers = max(0, self._live_viewers - 1)

    def has_live_viewers(self):
        with self._lock:
            return self._live_viewers > 0

    def get_latest_frame(self):
        with self._lock:
            return self._last_frame

    def _set_latest_frame(self, frame):
        with self._lock:
            self._last_frame = frame

    def _start_input_listeners(self):
        if not PYNPUT_AVAILABLE:
            return
        try:
            if self._keyboard_listener is None:
                self._keyboard_listener = keyboard.Listener(on_press=self._on_input_activity)
                self._keyboard_listener.start()
            if self._mouse_listener is None:
                self._mouse_listener = mouse.Listener(on_click=self._on_input_activity)
                self._mouse_listener.start()
        except Exception as e:
            self.ctx.log_error("Khong khoi dong duoc pynput listeners", e)

    def _stop_input_listeners(self):
        try:
            if self._keyboard_listener is not None:
                self._keyboard_listener.stop()
                self._keyboard_listener = None
            if self._mouse_listener is not None:
                self._mouse_listener.stop()
                self._mouse_listener = None
        except Exception as e:
            self.ctx.log_error("Khong dung duoc pynput listeners", e)

    def _on_input_activity(self, *args, **kwargs):
        if len(args) == 4:
            pressed = args[3]
            if not pressed:
                return
        threading.Thread(target=self._handle_input_intrusion, daemon=True).start()

    def _handle_input_intrusion(self):
        auto_mode_active, monitoring_chat_id = self._get_monitoring_state()
        if not auto_mode_active or monitoring_chat_id is None:
            return

        now = time.time()
        with self._lock:
            if now - self._last_input_alert_time < 15:
                return
            self._last_input_alert_time = now

        img = self.get_latest_frame()
        if img is None:
            time.sleep(0.5)
            img = self.get_latest_frame()

        if img is None:
            return

        self.ctx.ensure_log_dir()
        alert_id = self.ctx.make_alert_id(now)
        image_path = os.path.join(self.ctx.log_dir, f"alert_input_{alert_id}.jpg")
        save_frame(image_path, img)

        is_person = False
        analysis = "Gemini đang tắt"
        if self.ctx.get_setting("person_filter_enabled"):
            try:
                person_filter_answer = self.ctx.ask_ai(image_path, PERSON_FILTER_PROMPT)
                is_person = parse_person_filter_result(person_filter_answer)
            except Exception as e:
                self.ctx.log_error("Loi khi loc nguoi cho canh bao ban phim", e)
                is_person = True
        else:
            is_person = True

        if not is_person:
            try:
                os.remove(image_path)
            except OSError:
                pass
            return

        try:
            self.ctx.bot.send_message(
                monitoring_chat_id,
                "🚨 CẢNH BÁO XÂM NHẬP KHẨN CẤP!\n"
                "Phát hiện có hoạt động tác động trên Bàn phím/Chuột máy tính của bạn!"
            )
        except Exception as e:
            self.ctx.log_error("Khong gui duoc tin nhan canh bao nhap ban phim", e)

        if self.ctx.get_setting("use_gemini_analysis"):
            try:
                analysis = self.ctx.ask_ai(
                    image_path,
                    "Có người đang gõ bàn phím hoặc chạm chuột máy tính của tôi. "
                    "Hãy nhìn vào bức ảnh này và mô tả xem họ là ai (mô tả đặc điểm nhận dạng) và họ đang làm gì?"
                )
                with open(image_path, 'rb') as photo:
                    self.ctx.bot.send_photo(
                        monitoring_chat_id,
                        photo,
                        caption=f"🧠 Phân tích kẻ xâm nhập:\n\n{analysis}"
                    )
            except Exception as e:
                self.ctx.log_error("Gemini loi phan tich xam nhap ban phim", e)
                analysis = f"Lỗi Gemini: {e}"
                try:
                    with open(image_path, 'rb') as photo:
                        self.ctx.bot.send_photo(
                            monitoring_chat_id,
                            photo,
                            caption=f"📸 Ảnh kẻ xâm nhập\n⚠️ Lỗi Gemini: {e}"
                        )
                except Exception as send_err:
                    self.ctx.log_error("Khong gui duoc anh sau khi Gemini loi", send_err)
        else:
            try:
                with open(image_path, 'rb') as photo:
                    self.ctx.bot.send_photo(
                        monitoring_chat_id,
                        photo,
                        caption="📸 Ảnh kẻ xâm nhập tại thời điểm tác động bàn phím/chuột"
                    )
            except Exception as e:
                self.ctx.log_error("Khong gui duoc anh canh bao ban phim", e)

        self.ctx.add_alert_history({
            "id": f"input_{alert_id}",
            "timestamp": now,
            "image_path": self.ctx.relative_to_base(image_path),
            "video_path": None,
            "video_status": "Không ghi video cho sự kiện phím/chuột",
            "analysis": f"[BÀN PHÍM/CHUỘT] {analysis}",
            "settings": self.ctx.get_settings_snapshot()
        })

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
            
            if active and self._monitoring_chat_id is not None:
                self._start_input_listeners()
            else:
                self._stop_input_listeners()

    def is_radar_active(self):
        with self._lock:
            return self._auto_mode_active

    def get_camera_status_for_report(self):
        if self.is_radar_active():
            return self.get_camera_status()
        return check_camera_once(camera_config=self.ctx.get_settings_snapshot())

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

    def get_monitoring_chat_id(self):
        with self._lock:
            return self._monitoring_chat_id

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

    def _clear_camera_failure_state(self):
        with self._lock:
            self._camera_failure_count = 0
            self._last_camera_issue_alert_time = 0

    def _register_camera_failure(self, status):
        now = time.time()
        with self._lock:
            self._camera_online = False
            self._last_camera_status = status
            self._camera_failure_count += 1
            failure_count = self._camera_failure_count
            should_alert = failure_count == 1 or (
                failure_count >= CAMERA_RECONNECT_ALERT_FAILURE_THRESHOLD
                and now - self._last_camera_issue_alert_time >= CAMERA_RECONNECT_ALERT_REPEAT_SECONDS
            )
            repeated_alert = failure_count > 1
            if should_alert:
                self._last_camera_issue_alert_time = now
            return failure_count, should_alert, repeated_alert

    def _build_camera_issue_alert_message(self, status, camera_config, failure_count, repeated_alert=False):
        camera_text = format_camera_config(camera_config)
        if repeated_alert:
            return (
                "⚠️ CAMERA VẪN CHƯA KẾT NỐI LẠI\n\n"
                f"{status}\n"
                f"Đã thử reconnect {failure_count} lần với {camera_text}.\n"
                "Bot sẽ tiếp tục thử lại."
            )
        return (
            "⚠️ CAMERA BỊ RỚT\n\n"
            f"{status}\n"
            f"Bot sẽ tự reconnect {camera_text}."
        )

    def _send_camera_issue_alert(self, monitoring_chat_id, status, camera_config, failure_count, repeated_alert=False):
        try:
            self.ctx.bot.send_message(
                monitoring_chat_id,
                self._build_camera_issue_alert_message(
                    status,
                    camera_config,
                    failure_count,
                    repeated_alert=repeated_alert
                )
            )
        except Exception as e:
            self.ctx.log_error("Khong gui duoc canh bao camera", e)

    def _reset_camera_connection(self, camera_stream, status):
        if camera_stream is not None:
            try:
                camera_stream.release()
            except Exception as e:
                self.ctx.log_error("Khong giai phong duoc camera", e)
        self._set_camera_status(False, status)
        return None, None, None

    def _motion_detection_loop(self):
        camera_stream = None
        active_camera_config = None
        last_gray_frame = None
        last_alert_time = 0
        last_camera_error_log_time = 0

        while True:
            try:
                auto_mode_active, monitoring_chat_id = self._get_monitoring_state()
                has_viewers = self.has_live_viewers()
                if not (auto_mode_active and monitoring_chat_id is not None) and not has_viewers:
                    camera_stream, active_camera_config, last_gray_frame = self._reset_camera_connection(
                        camera_stream,
                        "Camera đang nghỉ vì radar tắt và không có live stream"
                    )
                    self._clear_camera_failure_state()
                    self._set_latest_frame(None)
                    time.sleep(0.5)
                    continue

                camera_config = normalize_camera_config(self.ctx.get_settings_snapshot())
                if camera_stream is not None and camera_config != active_camera_config:
                    camera_stream, active_camera_config, last_gray_frame = self._reset_camera_connection(
                        camera_stream,
                        "Đang áp dụng cấu hình camera mới"
                    )
                    self._clear_camera_failure_state()

                if camera_stream is None:
                    try:
                        camera_stream = open_camera(camera_config=camera_config)
                        active_camera_config = camera_config
                        time.sleep(1.5)
                        if not camera_stream.isOpened():
                            raise RuntimeError(
                                f"Radar bật nhưng không mở được {format_camera_config(camera_config)}"
                            )
                        warm_up_camera(camera_stream, delay_seconds=0, buffer_reads=5)
                    except Exception as e:
                        status = f"Radar bật nhưng không mở được {format_camera_config(camera_config)}"
                        camera_stream, active_camera_config, last_gray_frame = self._reset_camera_connection(
                            camera_stream,
                            status
                        )
                        failure_count, should_alert, repeated_alert = self._register_camera_failure(status)
                        if should_alert:
                            self._send_camera_issue_alert(
                                monitoring_chat_id,
                                status,
                                camera_config,
                                failure_count,
                                repeated_alert=repeated_alert
                            )
                        if time.time() - last_camera_error_log_time > 60:
                            self.ctx.log_error(status, e)
                            last_camera_error_log_time = time.time()
                        time.sleep(2)
                        continue

                try:
                    success, img = camera_stream.read()
                except Exception as e:
                    success = False
                    read_error = e
                else:
                    read_error = None
                if not success:
                    status = f"Radar bật nhưng không đọc được ảnh từ {format_camera_config(active_camera_config)}"
                    camera_stream, active_camera_config, last_gray_frame = self._reset_camera_connection(
                        camera_stream,
                        status
                    )
                    failure_count, should_alert, repeated_alert = self._register_camera_failure(status)
                    if should_alert:
                        self._send_camera_issue_alert(
                            monitoring_chat_id,
                            status,
                            active_camera_config or camera_config,
                            failure_count,
                            repeated_alert=repeated_alert
                        )
                    if time.time() - last_camera_error_log_time > 60:
                        self.ctx.log_error(status, read_error)
                        last_camera_error_log_time = time.time()
                    time.sleep(1)
                    continue
                img = transform_camera_frame(img, active_camera_config)
                self._set_latest_frame(img)
                if auto_mode_active and monitoring_chat_id is not None:
                    self._set_camera_status(True, f"Camera đang mở bởi radar ({format_camera_config(active_camera_config)})")
                else:
                    self._set_camera_status(True, f"Camera đang mở bởi live stream ({format_camera_config(active_camera_config)})")
                self._clear_camera_failure_state()

                if not (auto_mode_active and monitoring_chat_id is not None):
                    last_gray_frame = None
                    fps_delay = 1.0 / active_camera_config["camera_fps"] if active_camera_config["camera_fps"] > 0 else 0.05
                    time.sleep(fps_delay)
                    continue

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
                    if is_within_quiet_hours(self.ctx.get_settings_snapshot()):
                        last_gray_frame = gray
                        time.sleep(0.1)
                        continue

                    last_alert_time = time.time()
                    self._set_last_alert_timestamp(last_alert_time)
                    alert_id = self.ctx.make_alert_id(last_alert_time)
                    self.ctx.ensure_log_dir()
                    image_path = os.path.join(self.ctx.log_dir, f"alert_{alert_id}.jpg")
                    video_path = None
                    video_status = "Không ghi video"
                    analysis = "Gemini đang tắt"
                    save_frame(image_path, img)

                    if self.ctx.get_setting("person_filter_enabled"):
                        try:
                            person_filter_answer = self.ctx.ask_ai(image_path, PERSON_FILTER_PROMPT)
                            if not parse_person_filter_result(person_filter_answer):
                                try:
                                    os.remove(image_path)
                                except OSError as e:
                                    self.ctx.log_error("Khong xoa duoc anh motion bi loc bo", e)
                                last_gray_frame = gray
                                continue
                        except Exception as e:
                            self.ctx.log_error("Gemini loi khi loc canh bao co nguoi", e)

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
                            video_fps,
                            camera_config=active_camera_config
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
