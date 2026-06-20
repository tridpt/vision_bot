import os
import threading
import time
from dataclasses import dataclass

from .settings_store import (
    HISTORY_LIMIT_CHOICES,
    SETTING_LABELS,
    SETTING_LIMITS,
    SETTING_CHOICES,
    SETTING_UNITS,
)
from .telegram_ui import (
    build_clear_history_confirm_menu,
    build_main_menu,
    build_restart_confirm_menu,
    build_restore_history_confirm_menu,
    build_restore_settings_confirm_menu,
    build_setting_prompt,
    build_settings_menu,
    format_backup_list_message,
    format_error_log_message,
    format_settings_message,
    on_off_label,
)


@dataclass
class TelegramHandlerContext:
    bot: object
    allowed_user_id: int
    get_setting: object
    update_setting: object
    trim_alert_history: object
    clear_alert_history_files: object
    set_radar_state: object
    build_status_message: object
    list_backups: object
    restore_latest_settings_backup: object
    restore_latest_alert_history_backup: object
    format_timestamp: object
    format_size: object
    send_alert_history: object
    capture_and_analyze_environment: object
    scan_cameras: object
    test_camera: object
    schedule_bot_restart: object
    tail_error_log: object
    log_error: object
    get_dashboard_url: object


def register_telegram_handlers(ctx):
    pending_setting_inputs = {}
    pending_setting_lock = threading.Lock()
    bot = ctx.bot

    def is_allowed_user(user_id):
        return ctx.allowed_user_id == 0 or user_id == ctx.allowed_user_id

    def verify_user(message):
        user_id = message.from_user.id
        if not is_allowed_user(user_id):
            bot.reply_to(message, "⛔ Tôi không nhận lệnh từ người lạ.")
            return False
        return True

    def verify_callback(call):
        if not is_allowed_user(call.from_user.id):
            bot.answer_callback_query(call.id, "Tôi không nhận lệnh từ người lạ.", show_alert=True)
            return False
        return True

    def parse_int_argument(message, command_name):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, f"Thiếu giá trị. Ví dụ: {command_name} 10")
            return None
        try:
            return int(parts[1].strip())
        except ValueError:
            bot.reply_to(message, "Giá trị phải là số nguyên.")
            return None

    def set_numeric_setting(message, setting_name, command_name, label, unit=""):
        clear_pending_setting_input(message)
        value = parse_int_argument(message, command_name)
        if value is None:
            return

        min_value, max_value = SETTING_LIMITS[setting_name]
        if not min_value <= value <= max_value:
            bot.reply_to(message, f"{label} phải nằm trong khoảng {min_value}-{max_value}{unit}.")
            return

        ctx.update_setting(setting_name, value)
        bot.reply_to(message, f"✅ Đã cập nhật {label}: {value}{unit}")

    def set_choice_setting(message, setting_name, command_name, label):
        clear_pending_setting_input(message)
        value = parse_int_argument(message, command_name)
        if value is None:
            return

        choices = SETTING_CHOICES.get(setting_name)
        if choices is None or value not in choices:
            bot.reply_to(message, f"{label} phải là một trong các giá trị: {', '.join(str(choice) for choice in choices or [])}.")
            return

        ctx.update_setting(setting_name, value)
        unit = SETTING_UNITS.get(setting_name, "")
        bot.reply_to(message, f"✅ Đã cập nhật {label}: {value}{unit}")

    def set_boolean_setting(message, setting_name, value, label):
        clear_pending_setting_input(message)
        ctx.update_setting(setting_name, value)
        bot.reply_to(message, f"✅ Đã {on_off_label(value)} {label}.")

    def pending_key_from_message(message):
        return (message.chat.id, message.from_user.id)

    def pending_key_from_call(call):
        return (call.message.chat.id, call.from_user.id)

    def set_pending_setting_input(call, setting_name):
        with pending_setting_lock:
            pending_setting_inputs[pending_key_from_call(call)] = setting_name

    def pop_pending_setting_input(message):
        with pending_setting_lock:
            return pending_setting_inputs.pop(pending_key_from_message(message), None)

    def clear_pending_setting_input(message):
        with pending_setting_lock:
            pending_setting_inputs.pop(pending_key_from_message(message), None)

    def clear_pending_setting_input_from_call(call):
        with pending_setting_lock:
            pending_setting_inputs.pop(pending_key_from_call(call), None)

    def set_pending_setting_input_from_message(message, setting_name):
        with pending_setting_lock:
            pending_setting_inputs[pending_key_from_message(message)] = setting_name

    def handle_pending_setting_input(message):
        setting_name = pop_pending_setting_input(message)
        if setting_name is None:
            return False

        text = message.text.strip()
        if text.lower() in ("hủy", "huy", "cancel", "/cancel"):
            bot.reply_to(message, "Đã hủy chỉnh setting.", reply_markup=build_settings_menu())
            return True

        if setting_name == "dashboard_password":
            ctx.update_setting("dashboard_password", text)
            bot.reply_to(message, f"✅ Đã đổi mật khẩu Dashboard thành: `{text}`", parse_mode="Markdown", reply_markup=build_settings_menu())
            return True

        try:
            value = int(text)
        except ValueError:
            set_pending_setting_input_from_message(message, setting_name)
            bot.reply_to(message, "Giá trị phải là số nguyên. Nhập lại hoặc gõ hủy.")
            return True

        if setting_name not in SETTING_LIMITS:
            bot.reply_to(message, "Lỗi: Setting này không hỗ trợ nhập số.")
            return True

        min_value, max_value = SETTING_LIMITS[setting_name]
        label = SETTING_LABELS[setting_name]
        unit = SETTING_UNITS[setting_name]
        if not min_value <= value <= max_value:
            set_pending_setting_input_from_message(message, setting_name)
            bot.reply_to(message, f"{label} phải nằm trong khoảng {min_value}-{max_value}{unit}. Nhập lại hoặc gõ hủy.")
            return True

        choices = SETTING_CHOICES.get(setting_name)
        if choices is not None and value not in choices:
            set_pending_setting_input_from_message(message, setting_name)
            bot.reply_to(message, f"{label} phải là một trong các giá trị: {', '.join(str(choice) for choice in choices)}. Nhập lại hoặc gõ hủy.")
            return True

        ctx.update_setting(setting_name, value)
        bot.reply_to(message, f"✅ Đã cập nhật {label}: {value}{unit}", reply_markup=build_settings_menu())
        return True

    def adjust_numeric_setting(setting_name, delta):
        current = ctx.get_setting(setting_name)
        min_value, max_value = SETTING_LIMITS[setting_name]
        new_value = max(min_value, min(current + delta, max_value))
        ctx.update_setting(setting_name, new_value)
        return new_value

    def edit_menu_message(call, text, reply_markup=None):
        try:
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=reply_markup
            )
        except Exception as e:
            ctx.log_error("Khong edit duoc menu message, fallback sang send_message", e)
            bot.send_message(call.message.chat.id, text, reply_markup=reply_markup)

    @bot.message_handler(commands=['start', 'help'])
    def send_welcome(message):
        if not verify_user(message): return
        clear_pending_setting_input(message)
        bot.reply_to(message, "👋 Chào Boss, Trung tâm Giám sát Cơ sở.\n\n"
                              "⚙️ Dưới đây là các loại vũ khí:\n"
                              "👉 Gõ lệnh `/menu` : Mở bảng điều khiển bằng nút bấm.\n"
                              "👉 Gõ lệnh `/auto` : BẬT Lưới Laser Tự động báo động.\n"
                              "👉 Gõ lệnh `/stop` : TẮT báo động, nhường đường lại cho tự nhiên.\n"
                              "👉 Gõ lệnh `/status` : Kiểm tra bot, radar, camera và cảnh báo gần nhất.\n"
                              "👉 Gõ lệnh `/daily_summary_on` : Nhận tóm tắt trạng thái hằng ngày.\n"
                              "👉 Trong `/menu`, chọn Cài đặt hoặc Lịch sử để quản lý bot.\n"
                              "👉 Hoặc chỉ cần nhắn bất cứ gì (Tôi sẽ tự chụp 1 tấm để giải tỏa thắc mắc).")

    @bot.message_handler(commands=['menu'])
    def send_menu(message):
        if not verify_user(message): return
        clear_pending_setting_input(message)
        bot.reply_to(message, "🧭 MENU ĐIỀU KHIỂN VISION BOT", reply_markup=build_main_menu())

    @bot.message_handler(commands=['auto'])
    def turn_on_auto(message):
        if not verify_user(message): return
        clear_pending_setting_input(message)
        ctx.set_radar_state(True, message.chat.id)
        bot.reply_to(message, "🟢 Đã BẬT Radar Tự động!\n\nCamera hiện tại sẽ luôn mở. Bất kỳ loài vật sống nào tạt qua đều sẽ bị tôi bêu tên và gửi ảnh thẳng đến điện thoại chư vị!\n▶ Để tắt chống hao pin: Gõ lệnh /stop")

    @bot.message_handler(commands=['stop'])
    def turn_off_auto(message):
        if not verify_user(message): return
        clear_pending_setting_input(message)
        ctx.set_radar_state(False)
        bot.reply_to(message, "🔴 Đã TẮT Radar thụ động. Mắt camera đã tạm đóng kín.")

    @bot.message_handler(commands=['status'])
    def send_status(message):
        if not verify_user(message): return
        clear_pending_setting_input(message)
        bot.reply_to(message, ctx.build_status_message())

    @bot.message_handler(commands=['history'])
    def send_history(message):
        if not verify_user(message): return
        clear_pending_setting_input(message)
        ctx.send_alert_history(message.chat.id)

    @bot.message_handler(commands=['dashboard'])
    def send_dashboard_link(message):
        if not verify_user(message): return
        clear_pending_setting_input(message)
        url = ctx.get_dashboard_url()
        pw = ctx.get_setting("dashboard_password")
        bot.reply_to(message, f"🔗 **Dashboard Online**\n\nLink truy cập: {url}\n\n*Mật khẩu hiện tại:* `{pw}`\n_(Dùng lệnh `/set_password <mật_khẩu_mới>` để đổi)_", parse_mode="Markdown")

    @bot.message_handler(commands=['set_password'])
    def set_password(message):
        if not verify_user(message): return
        clear_pending_setting_input(message)
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "Thiếu giá trị. Ví dụ: /set_password 123456")
            return
        new_pw = parts[1].strip()
        ctx.update_setting("dashboard_password", new_pw)
        bot.reply_to(message, f"✅ Đã đổi mật khẩu Dashboard thành: `{new_pw}`", parse_mode="Markdown")

    @bot.message_handler(commands=['settings'])
    def send_settings(message):
        if not verify_user(message): return
        clear_pending_setting_input(message)
        bot.reply_to(message, format_settings_message(), reply_markup=build_settings_menu())

    @bot.message_handler(commands=['scan_cameras'])
    def scan_cameras(message):
        if not verify_user(message): return
        clear_pending_setting_input(message)
        ctx.scan_cameras(message.chat.id)

    @bot.message_handler(commands=['test_camera'])
    def test_camera(message):
        if not verify_user(message): return
        clear_pending_setting_input(message)
        ctx.test_camera(message.chat.id)

    @bot.message_handler(commands=['set_sensitivity'])
    def set_sensitivity(message):
        if not verify_user(message): return
        set_numeric_setting(
            message,
            "motion_area_threshold",
            "/set_sensitivity",
            "độ nhạy chuyển động"
        )

    @bot.message_handler(commands=['set_cooldown'])
    def set_cooldown(message):
        if not verify_user(message): return
        set_numeric_setting(
            message,
            "alert_cooldown_seconds",
            "/set_cooldown",
            "cooldown cảnh báo",
            " giây"
        )

    @bot.message_handler(commands=['set_video_seconds'])
    def set_video_seconds(message):
        if not verify_user(message): return
        set_numeric_setting(
            message,
            "alert_video_seconds",
            "/set_video_seconds",
            "độ dài video",
            " giây"
        )

    @bot.message_handler(commands=['set_video_fps'])
    def set_video_fps(message):
        if not verify_user(message): return
        set_numeric_setting(
            message,
            "alert_video_fps",
            "/set_video_fps",
            "FPS video"
        )

    @bot.message_handler(commands=['set_camera_index'])
    def set_camera_index(message):
        if not verify_user(message): return
        set_choice_setting(
            message,
            "camera_index",
            "/set_camera_index",
            "camera index"
        )

    @bot.message_handler(commands=['set_camera_width'])
    def set_camera_width(message):
        if not verify_user(message): return
        set_numeric_setting(
            message,
            "camera_width",
            "/set_camera_width",
            "chiều rộng camera",
            " px"
        )

    @bot.message_handler(commands=['set_camera_height'])
    def set_camera_height(message):
        if not verify_user(message): return
        set_numeric_setting(
            message,
            "camera_height",
            "/set_camera_height",
            "chiều cao camera",
            " px"
        )

    @bot.message_handler(commands=['set_camera_fps'])
    def set_camera_fps(message):
        if not verify_user(message): return
        set_numeric_setting(
            message,
            "camera_fps",
            "/set_camera_fps",
            "FPS camera",
            " fps"
        )

    @bot.message_handler(commands=['set_camera_rotation'])
    def set_camera_rotation(message):
        if not verify_user(message): return
        set_choice_setting(
            message,
            "camera_rotation",
            "/set_camera_rotation",
            "góc xoay camera"
        )

    @bot.message_handler(commands=['video_on'])
    def turn_video_on(message):
        if not verify_user(message): return
        set_boolean_setting(message, "send_video", True, "gửi video cảnh báo")

    @bot.message_handler(commands=['video_off'])
    def turn_video_off(message):
        if not verify_user(message): return
        set_boolean_setting(message, "send_video", False, "gửi video cảnh báo")

    @bot.message_handler(commands=['ai_on'])
    def turn_ai_on(message):
        if not verify_user(message): return
        set_boolean_setting(message, "use_gemini_analysis", True, "phân tích Gemini khi cảnh báo")

    @bot.message_handler(commands=['ai_off'])
    def turn_ai_off(message):
        if not verify_user(message): return
        set_boolean_setting(message, "use_gemini_analysis", False, "phân tích Gemini khi cảnh báo")

    @bot.message_handler(commands=['person_filter_on'])
    def turn_person_filter_on(message):
        if not verify_user(message): return
        set_boolean_setting(message, "person_filter_enabled", True, "lọc chỉ cảnh báo khi thấy người")

    @bot.message_handler(commands=['person_filter_off'])
    def turn_person_filter_off(message):
        if not verify_user(message): return
        set_boolean_setting(message, "person_filter_enabled", False, "lọc chỉ cảnh báo khi thấy người")

    @bot.message_handler(commands=['daily_summary_on'])
    def turn_daily_summary_on(message):
        if not verify_user(message): return
        set_boolean_setting(message, "daily_summary_enabled", True, "tóm tắt trạng thái hằng ngày")

    @bot.message_handler(commands=['daily_summary_off'])
    def turn_daily_summary_off(message):
        if not verify_user(message): return
        set_boolean_setting(message, "daily_summary_enabled", False, "tóm tắt trạng thái hằng ngày")

    @bot.message_handler(commands=['quiet_hours_on'])
    def turn_quiet_hours_on(message):
        if not verify_user(message): return
        set_boolean_setting(message, "quiet_hours_enabled", True, "giờ yên lặng")

    @bot.message_handler(commands=['quiet_hours_off'])
    def turn_quiet_hours_off(message):
        if not verify_user(message): return
        set_boolean_setting(message, "quiet_hours_enabled", False, "giờ yên lặng")

    @bot.message_handler(commands=['motion_on'])
    def turn_motion_on(message):
        if not verify_user(message): return
        set_boolean_setting(message, "motion_detection_enabled", True, "giám sát chuyển động camera")

    @bot.message_handler(commands=['motion_off'])
    def turn_motion_off(message):
        if not verify_user(message): return
        if not ctx.get_setting("input_monitoring_enabled"):
            bot.reply_to(message, "⚠️ Bạn không thể tắt cả 2 chế độ giám sát cùng lúc. Radar cần ít nhất 1 chế độ hoạt động!")
            return
        set_boolean_setting(message, "motion_detection_enabled", False, "giám sát chuyển động camera")

    @bot.message_handler(commands=['input_on'])
    def turn_input_on(message):
        if not verify_user(message): return
        set_boolean_setting(message, "input_monitoring_enabled", True, "giám sát bàn phím/chuột")

    @bot.message_handler(commands=['input_off'])
    def turn_input_off(message):
        if not verify_user(message): return
        if not ctx.get_setting("motion_detection_enabled"):
            bot.reply_to(message, "⚠️ Bạn không thể tắt cả 2 chế độ giám sát cùng lúc. Radar cần ít nhất 1 chế độ hoạt động!")
            return
        set_boolean_setting(message, "input_monitoring_enabled", False, "giám sát bàn phím/chuột")

    @bot.message_handler(commands=['screen_record_on'])
    def turn_screen_record_on(message):
        if not verify_user(message): return
        set_boolean_setting(message, "send_screen_record", True, "gửi video quay màn hình khi đụng phím/chuột")

    @bot.message_handler(commands=['screen_record_off'])
    def turn_screen_record_off(message):
        if not verify_user(message): return
        set_boolean_setting(message, "send_screen_record", False, "gửi video quay màn hình khi đụng phím/chuột")

    @bot.message_handler(commands=['input_photo_on'])
    def turn_input_photo_on(message):
        if not verify_user(message): return
        set_boolean_setting(message, "send_input_camera_photo", True, "gửi ảnh camera khi đụng phím/chuột")

    @bot.message_handler(commands=['input_photo_off'])
    def turn_input_photo_off(message):
        if not verify_user(message): return
        set_boolean_setting(message, "send_input_camera_photo", False, "gửi ảnh camera khi đụng phím/chuột")

    @bot.message_handler(commands=['set_quiet_start'])
    def set_quiet_start(message):
        if not verify_user(message): return
        set_numeric_setting(
            message,
            "quiet_hours_start_hour",
            "/set_quiet_start",
            "giờ bắt đầu yên lặng",
            " giờ"
        )

    @bot.message_handler(commands=['set_quiet_end'])
    def set_quiet_end(message):
        if not verify_user(message): return
        set_numeric_setting(
            message,
            "quiet_hours_end_hour",
            "/set_quiet_end",
            "giờ kết thúc yên lặng",
            " giờ"
        )

    @bot.message_handler(commands=['set_daily_summary_hour'])
    def set_daily_summary_hour(message):
        if not verify_user(message): return
        set_numeric_setting(
            message,
            "daily_summary_hour",
            "/set_daily_summary_hour",
            "giờ tóm tắt hằng ngày",
        )

    @bot.message_handler(commands=['set_daily_summary_minute'])
    def set_daily_summary_minute(message):
        if not verify_user(message): return
        set_numeric_setting(
            message,
            "daily_summary_minute",
            "/set_daily_summary_minute",
            "phút tóm tắt hằng ngày",
        )

    @bot.callback_query_handler(func=lambda call: call.data and (call.data.startswith("menu:") or call.data.startswith("setting:")))
    def handle_menu_callback(call):
        if not verify_callback(call): return

        if call.data == "menu:main":
            bot.answer_callback_query(call.id)
            edit_menu_message(call, "🧭 MENU ĐIỀU KHIỂN VISION BOT", build_main_menu())
            return

        if call.data == "menu:auto_on":
            ctx.set_radar_state(True, call.message.chat.id)
            bot.answer_callback_query(call.id, "Đã bật radar")
            edit_menu_message(call, "🟢 Đã BẬT Radar Tự động.", build_main_menu())
            return

        if call.data == "menu:auto_off":
            ctx.set_radar_state(False)
            bot.answer_callback_query(call.id, "Đã tắt radar")
            edit_menu_message(call, "🔴 Đã TẮT Radar thụ động.", build_main_menu())
            return

        if call.data == "menu:status":
            bot.answer_callback_query(call.id)
            edit_menu_message(call, ctx.build_status_message(), build_main_menu())
            return

        if call.data == "menu:dashboard":
            bot.answer_callback_query(call.id, "Đang tạo link Dashboard")
            url = ctx.get_dashboard_url()
            pw = ctx.get_setting("dashboard_password")
            bot.send_message(
                call.message.chat.id, 
                f"🔗 **Dashboard Online**\n\nLink truy cập: {url}\n\n*Mật khẩu hiện tại:* `{pw}`\n_(Dùng lệnh `/set_password <mật_khẩu_mới>` để đổi)_", 
                parse_mode="Markdown"
            )
            return

        if call.data == "menu:capture":
            clear_pending_setting_input_from_call(call)
            bot.answer_callback_query(call.id, "Đang chụp ảnh")
            ctx.capture_and_analyze_environment(
                call.message.chat.id,
                "Hãy mô tả ngắn gọn camera hiện đang thấy gì và có điều gì đáng chú ý không?"
            )
            return

        if call.data == "menu:scan_cameras":
            clear_pending_setting_input_from_call(call)
            bot.answer_callback_query(call.id, "Đang quét camera")
            edit_menu_message(call, "🔎 Đang quét camera index 0-5...", build_settings_menu())
            ctx.scan_cameras(call.message.chat.id)
            return

        if call.data == "menu:test_camera":
            clear_pending_setting_input_from_call(call)
            bot.answer_callback_query(call.id, "Đang chụp thử camera")
            ctx.test_camera(call.message.chat.id)
            return

        if call.data == "menu:history":
            bot.answer_callback_query(call.id, "Đang gửi lịch sử")
            edit_menu_message(call, "🧾 Đang gửi lịch sử cảnh báo gần nhất...", build_main_menu())
            ctx.send_alert_history(call.message.chat.id)
            return

        if call.data == "menu:error_log":
            bot.answer_callback_query(call.id, "Đang đọc log lỗi")
            bot.send_message(call.message.chat.id, format_error_log_message(ctx.tail_error_log()), parse_mode="Markdown")
            return

        if call.data == "menu:backups":
            bot.answer_callback_query(call.id, "Đang đọc backup")
            backups = ctx.list_backups()
            bot.send_message(
                call.message.chat.id,
                format_backup_list_message(backups, ctx.format_timestamp, ctx.format_size)
            )
            return

        if call.data == "menu:restore_settings_confirm":
            clear_pending_setting_input_from_call(call)
            bot.answer_callback_query(call.id)
            edit_menu_message(
                call,
                "↩️ KHÔI PHỤC SETTING\n\nBot sẽ lấy file backup setting gần nhất trong logs/backups và ghi lại vào settings.json. Setting hiện tại sẽ được backup trước khi khôi phục. Bạn chắc chắn muốn làm?",
                build_restore_settings_confirm_menu()
            )
            return

        if call.data == "menu:restore_settings_execute":
            clear_pending_setting_input_from_call(call)
            try:
                restore_result = ctx.restore_latest_settings_backup()
            except Exception as e:
                ctx.log_error("Khoi phuc setting that bai", e)
                bot.answer_callback_query(call.id, "Khôi phục setting thất bại", show_alert=True)
                edit_menu_message(call, f"❌ Không thể khôi phục setting: {e}", build_main_menu())
                return

            if restore_result is None:
                bot.answer_callback_query(call.id, "Chưa có backup setting", show_alert=True)
                edit_menu_message(call, "💾 Chưa có backup setting nào để khôi phục.", build_main_menu())
                return

            backup = restore_result["backup"]
            bot.answer_callback_query(call.id, "Đã khôi phục setting")
            edit_menu_message(
                call,
                "✅ Đã khôi phục setting gần nhất.\n\n"
                f"File: {backup['filename']}\n"
                f"Thời gian backup: {ctx.format_timestamp(backup.get('created_at'))}\n\n"
                f"{format_settings_message()}",
                build_settings_menu()
            )
            return

        if call.data == "menu:restore_history_confirm":
            clear_pending_setting_input_from_call(call)
            bot.answer_callback_query(call.id)
            edit_menu_message(
                call,
                "↩️ KHÔI PHỤC LỊCH SỬ\n\nBot sẽ lấy file backup alert_history gần nhất trong logs/backups và ghi lại vào logs/alert_history.json. Lịch sử hiện tại sẽ được backup trước khi khôi phục.\n\nLưu ý: backup chỉ chứa danh sách cảnh báo, không chứa lại ảnh/video nếu file media đã bị xóa khỏi logs. Bạn chắc chắn muốn làm?",
                build_restore_history_confirm_menu()
            )
            return

        if call.data == "menu:restore_history_execute":
            clear_pending_setting_input_from_call(call)
            try:
                restore_result = ctx.restore_latest_alert_history_backup()
            except Exception as e:
                ctx.log_error("Khoi phuc lich su canh bao that bai", e)
                bot.answer_callback_query(call.id, "Khôi phục lịch sử thất bại", show_alert=True)
                edit_menu_message(call, f"❌ Không thể khôi phục lịch sử: {e}", build_main_menu())
                return

            if restore_result is None:
                bot.answer_callback_query(call.id, "Chưa có backup lịch sử", show_alert=True)
                edit_menu_message(call, "💾 Chưa có backup lịch sử nào để khôi phục.", build_main_menu())
                return

            backup = restore_result["backup"]
            restored_count = restore_result["restored_count"]
            history_limit = restore_result["history_limit"]
            bot.answer_callback_query(call.id, "Đã khôi phục lịch sử")
            edit_menu_message(
                call,
                "✅ Đã khôi phục lịch sử gần nhất.\n\n"
                f"File: {backup['filename']}\n"
                f"Thời gian backup: {ctx.format_timestamp(backup.get('created_at'))}\n"
                f"Số cảnh báo đã khôi phục: {restored_count}/{history_limit}\n\n"
                "Bấm Lịch sử để xem lại các cảnh báo vừa khôi phục.",
                build_main_menu()
            )
            return

        if call.data == "menu:restart_confirm":
            bot.answer_callback_query(call.id)
            edit_menu_message(
                call,
                "🔄 RESTART BOT\n\nBot sẽ tự tắt process hiện tại và mở lại sau vài giây. Bạn chắc chắn muốn restart?",
                build_restart_confirm_menu()
            )
            return

        if call.data == "menu:restart_execute":
            try:
                ctx.schedule_bot_restart()
            except Exception as e:
                ctx.log_error("Khong len lich restart bot", e)
                bot.answer_callback_query(call.id, "Restart thất bại", show_alert=True)
                edit_menu_message(call, f"❌ Không thể restart bot: {e}", build_main_menu())
                return

            bot.answer_callback_query(call.id, "Đang restart bot")
            edit_menu_message(call, "🔄 Bot đang restart. Chờ vài giây rồi gõ /menu để kiểm tra lại.")
            time.sleep(0.5)
            os._exit(0)

        if call.data == "menu:clear_history_confirm":
            bot.answer_callback_query(call.id)
            edit_menu_message(
                call,
                "🧹 DỌN LỊCH SỬ\n\nThao tác này sẽ xóa toàn bộ ảnh, video cảnh báo và file lịch sử trong thư mục logs. Bạn chắc chắn muốn xóa?",
                build_clear_history_confirm_menu()
            )
            return

        if call.data == "menu:clear_history_execute":
            try:
                ctx.clear_alert_history_files()
            except Exception as e:
                ctx.log_error("Don lich su canh bao that bai", e)
                bot.answer_callback_query(call.id, "Xóa lịch sử thất bại", show_alert=True)
                edit_menu_message(call, f"❌ Không thể dọn lịch sử: {e}", build_main_menu())
                return

            bot.answer_callback_query(call.id, "Đã dọn lịch sử")
            edit_menu_message(call, "✅ Đã xóa toàn bộ lịch sử cảnh báo.", build_main_menu())
            return

        if call.data == "menu:settings":
            bot.answer_callback_query(call.id)
            edit_menu_message(call, format_settings_message(), build_settings_menu())
            return

        if call.data.startswith("setting:input:"):
            setting_name = call.data.split(":", 2)[2]
            if setting_name not in SETTING_LIMITS and setting_name != "dashboard_password":
                bot.answer_callback_query(call.id, "Setting không hợp lệ", show_alert=True)
                return

            set_pending_setting_input(call, setting_name)
            bot.answer_callback_query(call.id, "Nhập số trong khung chat")
            bot.send_message(call.message.chat.id, build_setting_prompt(setting_name))
            return

        if call.data == "setting:toggle_video":
            ctx.update_setting("send_video", not ctx.get_setting("send_video"))
            bot.answer_callback_query(call.id, "Đã cập nhật gửi video")
            edit_menu_message(call, format_settings_message(), build_settings_menu())
            return

        if call.data == "setting:toggle_ai":
            ctx.update_setting("use_gemini_analysis", not ctx.get_setting("use_gemini_analysis"))
            bot.answer_callback_query(call.id, "Đã cập nhật Gemini")
            edit_menu_message(call, format_settings_message(), build_settings_menu())
            return

        if call.data == "setting:toggle_person_filter":
            ctx.update_setting("person_filter_enabled", not ctx.get_setting("person_filter_enabled"))
            bot.answer_callback_query(call.id, "Đã cập nhật lọc người")
            edit_menu_message(call, format_settings_message(), build_settings_menu())
            return

        if call.data == "setting:toggle_daily_summary":
            ctx.update_setting("daily_summary_enabled", not ctx.get_setting("daily_summary_enabled"))
            bot.answer_callback_query(call.id, "Đã cập nhật tóm tắt hằng ngày")
            edit_menu_message(call, format_settings_message(), build_settings_menu())
            return

        if call.data == "setting:toggle_quiet_hours":
            ctx.update_setting("quiet_hours_enabled", not ctx.get_setting("quiet_hours_enabled"))
            bot.answer_callback_query(call.id, "Đã cập nhật giờ yên lặng")
            edit_menu_message(call, format_settings_message(), build_settings_menu())
            return

        if call.data == "setting:toggle_motion":
            current_motion = ctx.get_setting("motion_detection_enabled")
            if current_motion and not ctx.get_setting("input_monitoring_enabled"):
                bot.answer_callback_query(call.id, "⚠️ Phải có ít nhất 1 chế độ giám sát được bật!", show_alert=True)
                return
            ctx.update_setting("motion_detection_enabled", not current_motion)
            bot.answer_callback_query(call.id, "Đã cập nhật giám sát camera")
            edit_menu_message(call, format_settings_message(), build_settings_menu())
            return

        if call.data == "setting:toggle_input":
            current_input = ctx.get_setting("input_monitoring_enabled")
            if current_input and not ctx.get_setting("motion_detection_enabled"):
                bot.answer_callback_query(call.id, "⚠️ Phải có ít nhất 1 chế độ giám sát được bật!", show_alert=True)
                return
            ctx.update_setting("input_monitoring_enabled", not current_input)
            bot.answer_callback_query(call.id, "Đã cập nhật giám sát phím/chuột")
            edit_menu_message(call, format_settings_message(), build_settings_menu())
            return

        if call.data == "setting:toggle_screen_record":
            ctx.update_setting("send_screen_record", not ctx.get_setting("send_screen_record"))
            bot.answer_callback_query(call.id, "Đã cập nhật quay màn hình")
            edit_menu_message(call, format_settings_message(), build_settings_menu())
            return

        if call.data == "setting:toggle_input_camera_photo":
            ctx.update_setting("send_input_camera_photo", not ctx.get_setting("send_input_camera_photo"))
            bot.answer_callback_query(call.id, "Đã cập nhật gửi ảnh camera đụng phím")
            edit_menu_message(call, format_settings_message(), build_settings_menu())
            return

        if call.data.startswith("setting:select:"):
            parts = call.data.split(":")
            if len(parts) != 4:
                bot.answer_callback_query(call.id, "Nút chọn không hợp lệ", show_alert=True)
                return

            setting_name = parts[2]
            try:
                value = int(parts[3])
            except ValueError:
                bot.answer_callback_query(call.id, "Giá trị nút không hợp lệ", show_alert=True)
                return

            choices = SETTING_CHOICES.get(setting_name)
            if choices is None or value not in choices:
                bot.answer_callback_query(call.id, "Giá trị nút không hợp lệ", show_alert=True)
                return

            ctx.update_setting(setting_name, value)
            bot.answer_callback_query(call.id, f"Đã cập nhật {SETTING_LABELS.get(setting_name, setting_name)}")
            edit_menu_message(call, format_settings_message(), build_settings_menu())
            return

        if call.data.startswith("setting:history_limit:"):
            try:
                history_limit = int(call.data.rsplit(":", 1)[1])
            except ValueError:
                bot.answer_callback_query(call.id, "Giá trị lịch sử không hợp lệ", show_alert=True)
                return

            if history_limit not in HISTORY_LIMIT_CHOICES:
                bot.answer_callback_query(call.id, "Chỉ hỗ trợ 10, 50 hoặc 100 cảnh báo", show_alert=True)
                return

            ctx.update_setting("alert_history_limit", history_limit)
            ctx.trim_alert_history(history_limit)
            bot.answer_callback_query(call.id, f"Giữ {history_limit} cảnh báo gần nhất")
            edit_menu_message(call, format_settings_message(), build_settings_menu())
            return

        parts = call.data.split(":")
        if len(parts) == 3 and parts[0] == "setting":
            setting_name = parts[1]
            try:
                delta = int(parts[2])
            except ValueError:
                bot.answer_callback_query(call.id, "Giá trị nút không hợp lệ", show_alert=True)
                return

            if setting_name not in SETTING_LIMITS:
                bot.answer_callback_query(call.id, "Setting không hợp lệ", show_alert=True)
                return

            new_value = adjust_numeric_setting(setting_name, delta)
            bot.answer_callback_query(call.id, f"Đã cập nhật: {new_value}")
            edit_menu_message(call, format_settings_message(), build_settings_menu())

    @bot.message_handler(func=lambda message: True)
    def handle_user_message(message):
        if not verify_user(message): return

        if handle_pending_setting_input(message):
            return

        ctx.capture_and_analyze_environment(message.chat.id, message.text, reply_to_message=message)
