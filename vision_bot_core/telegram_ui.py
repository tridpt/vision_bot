import telebot

from .alert_history_store import text_preview
from .status_report import format_daily_summary_schedule, format_quiet_hours_schedule
from .settings_store import (
    CAMERA_INDEX_CHOICES,
    CAMERA_ROTATION_CHOICES,
    HISTORY_LIMIT_CHOICES,
    SETTING_EXAMPLES,
    SETTING_CHOICES,
    SETTING_LABELS,
    SETTING_LIMITS,
    SETTING_UNITS,
    get_setting,
    get_settings_snapshot,
)


def on_off_label(value):
    return "BẬT" if value else "TẮT"


def format_error_log_message(log_text):
    safe_log_text = log_text.replace("```", "` ` `")
    return f"🧯 LOG LỖI GẦN NHẤT\n\n```text\n{safe_log_text}\n```"


def format_backup_list_message(backups, format_timestamp, format_size):
    if not backups:
        return "💾 BACKUP GẦN NHẤT\n\nChưa có backup nào trong logs/backups."

    lines = ["💾 BACKUP GẦN NHẤT"]
    for index, backup in enumerate(backups, start=1):
        label = str(backup.get("label", "unknown")).replace("_", " ")
        reason = str(backup.get("reason", "unknown")).replace("_", " ")
        created_at = format_timestamp(backup.get("created_at"))
        size = format_size(backup.get("size", 0))
        filename = backup.get("filename", "")
        lines.append(
            f"\n{index}. {label}\n"
            f"Lý do: {reason}\n"
            f"Thời gian: {created_at}\n"
            f"Dung lượng: {size}\n"
            f"File: {filename}"
        )
    return "\n".join(lines)


def format_alert_history_message(entries, format_timestamp):
    if not entries:
        return "🧾 LỊCH SỬ CẢNH BÁO\n\nChưa có cảnh báo nào được ghi lại."

    lines = ["🧾 LỊCH SỬ CẢNH BÁO GẦN NHẤT"]
    for index, entry in enumerate(entries, start=1):
        timestamp = entry.get("timestamp")
        video_status = entry.get("video_status") or "Không có video"
        analysis = text_preview(entry.get("analysis"))
        lines.append(
            f"\n{index}. {format_timestamp(timestamp)}\n"
            f"Video: {video_status}\n"
            f"Gemini: {analysis}"
        )
    return "\n".join(lines)


def format_settings_message():
    current = get_settings_snapshot()
    camera_resolution = "mặc định"
    if current["camera_width"] > 0 and current["camera_height"] > 0:
        camera_resolution = f"{current['camera_width']}x{current['camera_height']}"
    camera_fps = "mặc định" if current["camera_fps"] <= 0 else f"{current['camera_fps']} fps"
    return (
        "⚙️ CÀI ĐẶT VISION BOT\n\n"
        f"🎯 Độ nhạy chuyển động: {current['motion_area_threshold']} "
        "(số nhỏ nhạy hơn)\n"
        f"⏱️ Cooldown cảnh báo: {current['alert_cooldown_seconds']} giây\n"
        f"🎥 Độ dài video: {current['alert_video_seconds']} giây\n"
        f"🎞️ FPS video: {current['alert_video_fps']}\n"
        f"📹 Gửi video: {on_off_label(current['send_video'])}\n"
        f"🧠 Phân tích Gemini: {on_off_label(current['use_gemini_analysis'])}\n\n"
        f"🧍 Chỉ cảnh báo khi thấy người: {on_off_label(current['person_filter_enabled'])}\n"
        f"📅 Tóm tắt hằng ngày: {format_daily_summary_schedule(current)}\n"
        f"🌙 Giờ yên lặng: {format_quiet_hours_schedule(current)}\n"
        f"📷 Camera: index {current['camera_index']} | {camera_resolution} | {camera_fps} | xoay {current['camera_rotation']} độ\n"
        f"🧾 Giữ lịch sử: {current['alert_history_limit']} cảnh báo\n\n"
        "Bấm nút bên dưới để chỉnh. Với các mục số, bot sẽ hỏi và bạn chỉ cần nhập số mới vào khung chat."
    )


def build_setting_prompt(setting_name):
    label = SETTING_LABELS[setting_name]
    unit = SETTING_UNITS[setting_name]
    min_value, max_value = SETTING_LIMITS[setting_name]
    current_value = get_setting(setting_name)
    example = SETTING_EXAMPLES[setting_name]
    if setting_name in SETTING_CHOICES:
        valid_text = "Giá trị hợp lệ: " + ", ".join(str(choice) for choice in SETTING_CHOICES[setting_name])
    else:
        valid_text = f"Khoảng hợp lệ: {min_value}-{max_value}{unit}"
    return (
        f"Nhập {label} mới.\n"
        f"Hiện tại: {current_value}{unit}\n"
        f"{valid_text}\n"
        f"Ví dụ: {example}\n\n"
        "Gõ hủy để bỏ qua."
    )


def build_main_menu():
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(telebot.types.InlineKeyboardButton("📸 Chụp ngay", callback_data="menu:capture"))
    keyboard.add(
        telebot.types.InlineKeyboardButton("🟢 Bật Radar", callback_data="menu:auto_on"),
        telebot.types.InlineKeyboardButton("🔴 Tắt Radar", callback_data="menu:auto_off")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("📡 Trạng thái", callback_data="menu:status"),
        telebot.types.InlineKeyboardButton("🧾 Lịch sử", callback_data="menu:history")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("🧯 Xem log lỗi", callback_data="menu:error_log"),
        telebot.types.InlineKeyboardButton("⚙️ Cài đặt", callback_data="menu:settings")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("💾 Xem backup", callback_data="menu:backups"),
        telebot.types.InlineKeyboardButton("↩️ Khôi phục setting", callback_data="menu:restore_settings_confirm")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("↩️ Khôi phục lịch sử", callback_data="menu:restore_history_confirm"),
        telebot.types.InlineKeyboardButton("🧹 Dọn lịch sử", callback_data="menu:clear_history_confirm")
    )
    keyboard.add(telebot.types.InlineKeyboardButton("🔄 Restart bot", callback_data="menu:restart_confirm"))
    return keyboard


def build_restart_confirm_menu():
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        telebot.types.InlineKeyboardButton("✅ Restart ngay", callback_data="menu:restart_execute"),
        telebot.types.InlineKeyboardButton("⬅️ Không restart", callback_data="menu:main")
    )
    return keyboard


def build_clear_history_confirm_menu():
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        telebot.types.InlineKeyboardButton("✅ Xóa hết lịch sử", callback_data="menu:clear_history_execute"),
        telebot.types.InlineKeyboardButton("⬅️ Không xóa", callback_data="menu:main")
    )
    return keyboard


def build_restore_settings_confirm_menu():
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        telebot.types.InlineKeyboardButton("✅ Khôi phục setting", callback_data="menu:restore_settings_execute"),
        telebot.types.InlineKeyboardButton("⬅️ Không khôi phục", callback_data="menu:main")
    )
    return keyboard


def build_restore_history_confirm_menu():
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        telebot.types.InlineKeyboardButton("✅ Khôi phục lịch sử", callback_data="menu:restore_history_execute"),
        telebot.types.InlineKeyboardButton("⬅️ Không khôi phục", callback_data="menu:main")
    )
    return keyboard


def build_settings_menu():
    current = get_settings_snapshot()
    video_label = "📹 Tắt video" if current["send_video"] else "📹 Bật video"
    ai_label = "🧠 Tắt Gemini" if current["use_gemini_analysis"] else "🧠 Bật Gemini"
    person_filter_label = "🧍 Tắt lọc người" if current["person_filter_enabled"] else "🧍 Bật lọc người"
    daily_summary_label = "📅 Tắt tóm tắt" if current["daily_summary_enabled"] else "📅 Bật tóm tắt"
    quiet_hours_label = "🌙 Tắt giờ yên lặng" if current["quiet_hours_enabled"] else "🌙 Bật giờ yên lặng"
    camera_index_buttons = [
        telebot.types.InlineKeyboardButton(
            f"{'✅ ' if current['camera_index'] == choice else ''}Cam {choice}",
            callback_data=f"setting:select:camera_index:{choice}"
        )
        for choice in CAMERA_INDEX_CHOICES
    ]
    camera_rotation_buttons = [
        telebot.types.InlineKeyboardButton(
            f"{'✅ ' if current['camera_rotation'] == choice else ''}{choice}°",
            callback_data=f"setting:select:camera_rotation:{choice}"
        )
        for choice in CAMERA_ROTATION_CHOICES
    ]
    history_buttons = [
        telebot.types.InlineKeyboardButton(
            f"{'✅ ' if current['alert_history_limit'] == choice else ''}{choice} cảnh báo",
            callback_data=f"setting:history_limit:{choice}"
        )
        for choice in HISTORY_LIMIT_CHOICES
    ]

    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        telebot.types.InlineKeyboardButton("🎯 Nhập độ nhạy", callback_data="setting:input:motion_area_threshold"),
        telebot.types.InlineKeyboardButton("⏱️ Nhập cooldown", callback_data="setting:input:alert_cooldown_seconds")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("🎥 Nhập giây video", callback_data="setting:input:alert_video_seconds"),
        telebot.types.InlineKeyboardButton("🎞️ Nhập FPS", callback_data="setting:input:alert_video_fps")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton(video_label, callback_data="setting:toggle_video"),
        telebot.types.InlineKeyboardButton(ai_label, callback_data="setting:toggle_ai")
    )
    keyboard.add(telebot.types.InlineKeyboardButton(person_filter_label, callback_data="setting:toggle_person_filter"))
    keyboard.add(telebot.types.InlineKeyboardButton(daily_summary_label, callback_data="setting:toggle_daily_summary"))
    keyboard.add(
        telebot.types.InlineKeyboardButton("📅 Nhập giờ tóm tắt", callback_data="setting:input:daily_summary_hour"),
        telebot.types.InlineKeyboardButton("📅 Nhập phút tóm tắt", callback_data="setting:input:daily_summary_minute")
    )
    keyboard.add(telebot.types.InlineKeyboardButton(quiet_hours_label, callback_data="setting:toggle_quiet_hours"))
    keyboard.add(
        telebot.types.InlineKeyboardButton("🌙 Nhập giờ bắt đầu", callback_data="setting:input:quiet_hours_start_hour"),
        telebot.types.InlineKeyboardButton("🌙 Nhập giờ kết thúc", callback_data="setting:input:quiet_hours_end_hour")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("📷 Nhập rộng", callback_data="setting:input:camera_width"),
        telebot.types.InlineKeyboardButton("📷 Nhập cao", callback_data="setting:input:camera_height")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("📷 Nhập FPS camera", callback_data="setting:input:camera_fps"),
        telebot.types.InlineKeyboardButton("📷 Nhập camera index", callback_data="setting:input:camera_index")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("🔎 Quét camera", callback_data="menu:scan_cameras"),
        telebot.types.InlineKeyboardButton("🧪 Test camera", callback_data="menu:test_camera")
    )
    keyboard.add(*camera_index_buttons)
    keyboard.add(*camera_rotation_buttons)
    keyboard.add(*history_buttons)
    keyboard.add(telebot.types.InlineKeyboardButton("⬅️ Quay lại menu", callback_data="menu:main"))
    return keyboard


def format_settings_snapshot(settings_snapshot):
    return (
        f"Độ nhạy {settings_snapshot['motion_area_threshold']} | "
        f"Cooldown {settings_snapshot['alert_cooldown_seconds']}s | "
        f"Video {settings_snapshot['alert_video_seconds']}s/{settings_snapshot['alert_video_fps']}fps | "
        f"Gửi video {on_off_label(settings_snapshot['send_video'])} | "
        f"Gemini {on_off_label(settings_snapshot['use_gemini_analysis'])} | "
        f"Lọc người {on_off_label(settings_snapshot['person_filter_enabled'])} | "
        f"Tóm tắt {format_daily_summary_schedule(settings_snapshot)} | "
        f"Yên lặng {format_quiet_hours_schedule(settings_snapshot)} | "
        f"Camera {settings_snapshot['camera_index']} "
        f"{settings_snapshot['camera_width']}x{settings_snapshot['camera_height']} "
        f"{settings_snapshot['camera_fps']}fps xoay {settings_snapshot['camera_rotation']}° | "
        f"Giữ lịch sử {settings_snapshot['alert_history_limit']}"
    )
