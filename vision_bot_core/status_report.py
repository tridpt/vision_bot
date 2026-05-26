import os
import time
from dataclasses import dataclass


@dataclass
class StatusReportContext:
    bot_start_time: float
    dashboard_url: str
    log_dir: str
    get_camera_status: object
    is_radar_active: object
    get_last_alert_timestamp: object
    get_alert_history_count: object
    get_settings_snapshot: object
    format_timestamp: object
    format_settings_snapshot: object
    log_error: object = None


def format_duration(seconds):
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days} ngày")
    if hours:
        parts.append(f"{hours} giờ")
    if minutes:
        parts.append(f"{minutes} phút")
    if seconds or not parts:
        parts.append(f"{seconds} giây")
    return " ".join(parts)


def get_directory_size(path, log_error=None):
    total_size = 0
    if not os.path.isdir(path):
        return 0

    for root, _, files in os.walk(path):
        for filename in files:
            file_path = os.path.join(root, filename)
            try:
                total_size += os.path.getsize(file_path)
            except OSError as e:
                if log_error is not None:
                    log_error(f"Khong doc duoc dung luong file log: {file_path}", e)
    return total_size


def format_size(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024


def format_status_message(ctx):
    camera_ok, camera_status = ctx.get_camera_status()
    radar_status = "BẬT" if ctx.is_radar_active() else "TẮT"
    camera_icon = "✅" if camera_ok else "❌"
    alert_time = ctx.format_timestamp(ctx.get_last_alert_timestamp())
    uptime = format_duration(time.time() - ctx.bot_start_time)
    alert_count = ctx.get_alert_history_count()
    logs_size = format_size(get_directory_size(ctx.log_dir, log_error=ctx.log_error))
    settings_snapshot = ctx.get_settings_snapshot()

    return (
        "📡 TRẠNG THÁI VISION BOT\n\n"
        "✅ Bot: Đang chạy và nhận lệnh Telegram\n"
        f"📍 Radar: {radar_status}\n"
        f"{camera_icon} Camera: {camera_status}\n"
        f"🚨 Lần cảnh báo gần nhất: {alert_time}\n"
        f"🧾 Cảnh báo trong lịch sử: {alert_count}/{settings_snapshot['alert_history_limit']}\n"
        f"💾 Dung lượng logs: {logs_size}\n"
        f"⏳ Uptime: {uptime}\n"
        f"🌐 Dashboard local: {ctx.dashboard_url}\n"
        f"⚙️ Setting: {ctx.format_settings_snapshot(settings_snapshot)}"
    )
