import telebot
import sys
import os
import logging
import subprocess
import threading
import time
from logging.handlers import RotatingFileHandler
from vision_bot_core.alert_history_store import (
    absolute_from_base,
    add_alert_history,
    clear_alert_history_files as clear_alert_history_files_unprotected,
    configure_alert_history_store,
    delete_alert_history_entry,
    ensure_log_dir,
    get_alert_history_count,
    get_alert_history_snapshot,
    get_recent_alert_history,
    is_safe_alert_media_path,
    load_alert_history_from_file,
    make_alert_id,
    relative_to_base,
    restore_alert_history,
    text_preview,
    trim_alert_history as trim_alert_history_unprotected,
)
from vision_bot_core.backup_store import backup_json_files, get_latest_backup, list_backups
from vision_bot_core.camera_tools import (
    format_camera_config,
    format_camera_scan_results,
    read_camera_frame,
    save_frame,
    scan_camera_indices,
)
from vision_bot_core.dashboard_server import DashboardContext, start_dashboard_server
from vision_bot_core.gemini_analyzer import ask_ai, configure_gemini_analyzer
from vision_bot_core.motion_monitor import MotionMonitor, MotionMonitorContext
from vision_bot_core.settings_store import (
    HISTORY_LIMIT_CHOICES,
    SETTING_LABELS,
    SETTING_LIMITS,
    SETTING_UNITS,
    clamp_int,
    configure_settings_store,
    get_setting,
    get_settings_snapshot,
    restore_settings_from_file,
    update_setting as save_setting,
)
from vision_bot_core.status_report import (
    StatusReportContext,
    format_duration,
    format_size,
    format_status_message,
    get_directory_size,
    get_daily_summary_schedule,
)
from vision_bot_core.telegram_ui import (
    format_alert_history_message,
    format_settings_snapshot,
)
from vision_bot_core.telegram_handlers import TelegramHandlerContext, register_telegram_handlers
from dotenv import load_dotenv

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SINGLE_INSTANCE_MUTEX_NAME = "Local\\VisionBot_Surveillance_SingleInstance"
_single_instance_mutex_handle = None

def ensure_single_instance():
    global _single_instance_mutex_handle
    if os.name != "nt":
        return

    import ctypes

    error_already_exists = 183
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p

    mutex_handle = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX_NAME)
    if not mutex_handle:
        return

    _single_instance_mutex_handle = mutex_handle
    if ctypes.get_last_error() == error_already_exists:
        if sys.stdout:
            print("Vision bot da dang chay. Thoat instance thu hai.")
        sys.exit(0)

ensure_single_instance()
BOT_START_TIME = time.time()

# --- BẢO MẬT: Load thông tin bí mật từ file .env ---
load_dotenv(os.path.join(BASE_DIR, ".env"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CHIEC_CHIA_KHOA_ID_CUA_BAN = int(os.getenv("ALLOWED_USER_ID", 0))
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")

def env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
ALERT_HISTORY_FILE = os.path.join(LOG_DIR, "alert_history.json")
ERROR_LOG_FILE = os.path.join(LOG_DIR, "bot_errors.log")
BACKUP_DIR = os.path.join(LOG_DIR, "backups")
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = env_int("DASHBOARD_PORT", 8765)
DASHBOARD_URL = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"
HISTORY_PREVIEW_LIMIT = 3
BACKUP_MAX_FILES = env_int("BACKUP_MAX_FILES", 30)
configure_settings_store(SETTINGS_FILE)
configure_gemini_analyzer(GEMINI_API_KEY)

def setup_error_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    handler = RotatingFileHandler(
        ERROR_LOG_FILE,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8"
    )
    handler.setLevel(logging.ERROR)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    logger = logging.getLogger("vision_bot")
    logger.setLevel(logging.ERROR)
    logger.addHandler(handler)
    logger.propagate = False
    return logger

error_logger = setup_error_logging()

def log_error(context, error=None):
    if error is None:
        error_logger.error(context)
    else:
        error_logger.exception("%s: %s", context, error)

def backup_runtime_state(reason, include_settings=True, include_history=True):
    file_specs = []
    if include_settings:
        file_specs.append(("settings", SETTINGS_FILE))
    if include_history:
        file_specs.append(("alert_history", ALERT_HISTORY_FILE))

    return backup_json_files(
        file_specs,
        BACKUP_DIR,
        reason=reason,
        max_backups=BACKUP_MAX_FILES,
        log_error=log_error
    )

def update_setting(name, value):
    backup_runtime_state(f"before_setting_{name}", include_settings=True, include_history=False)
    save_setting(name, value)

def trim_alert_history(limit):
    backup_runtime_state(f"before_trim_history_{limit}", include_settings=False, include_history=True)
    trim_alert_history_unprotected(limit)

def clear_alert_history_files():
    backup_runtime_state("before_clear_history", include_settings=False, include_history=True)
    clear_alert_history_files_unprotected()

def restore_latest_settings_backup():
    latest_backup = get_latest_backup(BACKUP_DIR, label="settings", log_error=log_error)
    if latest_backup is None:
        return None

    return restore_settings_backup(latest_backup)

def restore_settings_backup(backup):
    backup_runtime_state("before_restore_settings", include_settings=True, include_history=False)
    restored_settings = restore_settings_from_file(backup["path"])
    return {
        "backup": backup,
        "settings": restored_settings,
    }

def restore_latest_alert_history_backup():
    latest_backup = get_latest_backup(BACKUP_DIR, label="alert_history", log_error=log_error)
    if latest_backup is None:
        return None

    return restore_alert_history_backup(latest_backup)

def restore_alert_history_backup(backup):
    history_limit = get_setting("alert_history_limit")
    restored_history = load_alert_history_from_file(backup["path"], limit=history_limit)
    backup_runtime_state("before_restore_history", include_settings=False, include_history=True)
    restored_history = restore_alert_history(restored_history)
    return {
        "backup": backup,
        "restored_count": len(restored_history),
        "history_limit": history_limit,
    }

def delete_backup(backup):
    backup_path = backup.get("path")
    filename = backup.get("filename")
    if not backup_path or not filename:
        return False

    absolute_backup_dir = os.path.abspath(BACKUP_DIR)
    absolute_backup_path = os.path.abspath(backup_path)
    if os.path.commonpath([absolute_backup_dir, absolute_backup_path]) != absolute_backup_dir:
        raise RuntimeError("Duong dan backup khong hop le, da huy thao tac xoa.")
    if os.path.basename(absolute_backup_path) != filename or not filename.endswith(".json"):
        raise RuntimeError("Ten file backup khong hop le, da huy thao tac xoa.")
    if not os.path.isfile(absolute_backup_path):
        return False

    os.remove(absolute_backup_path)
    return True

configure_alert_history_store(
    base_dir=BASE_DIR,
    log_dir=LOG_DIR,
    alert_history_file=ALERT_HISTORY_FILE,
    get_history_limit=lambda: get_setting("alert_history_limit"),
    log_error=log_error
)

def schedule_bot_restart():
    restart_script = os.path.join(BASE_DIR, "Chay_Bot_Ngam.vbs")
    if not os.path.exists(restart_script):
        raise FileNotFoundError(restart_script)

    command = (
        "Start-Sleep -Seconds 3; "
        f"Start-Process -FilePath 'wscript.exe' -ArgumentList '\"{restart_script}\"' -WindowStyle Hidden"
    )
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=BASE_DIR,
        creationflags=creation_flags
    )

# Khởi tạo kết nối
telebot.apihelper.CONNECT_TIMEOUT = 60
telebot.apihelper.READ_TIMEOUT = 180
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Tự động ghim Menu Lệnh lên màn hình chat Telegram
bot.set_my_commands([
    telebot.types.BotCommand("/start", "Xem hướng dẫn các chức năng"),
    telebot.types.BotCommand("/menu", "Mở menu điều khiển bằng nút bấm"),
    telebot.types.BotCommand("/auto", "🔴 BẬT Radar: Quét và báo động tự động 24/7"),
    telebot.types.BotCommand("/stop", "🟢 TẮT Radar: Cho phép camera đi ngủ"),
    telebot.types.BotCommand("/status", "Xem trạng thái bot, radar, camera, tóm tắt và cảnh báo gần nhất"),
    telebot.types.BotCommand("/settings", "Chỉnh độ nhạy, video, Gemini, camera và tóm tắt"),
    telebot.types.BotCommand("/person_filter_on", "Chỉ cảnh báo khi thấy người"),
    telebot.types.BotCommand("/person_filter_off", "Tắt lọc người"),
    telebot.types.BotCommand("/daily_summary_on", "Bật tóm tắt trạng thái hằng ngày"),
    telebot.types.BotCommand("/daily_summary_off", "Tắt tóm tắt trạng thái hằng ngày"),
    telebot.types.BotCommand("/set_daily_summary_hour", "Chỉnh giờ tóm tắt hằng ngày"),
    telebot.types.BotCommand("/set_daily_summary_minute", "Chỉnh phút tóm tắt hằng ngày"),
    telebot.types.BotCommand("/quiet_hours_on", "Bật giờ yên lặng: radar quét nhưng không báo động"),
    telebot.types.BotCommand("/quiet_hours_off", "Tắt giờ yên lặng"),
    telebot.types.BotCommand("/set_quiet_start", "Chỉnh giờ bắt đầu yên lặng"),
    telebot.types.BotCommand("/set_quiet_end", "Chỉnh giờ kết thúc yên lặng"),
    telebot.types.BotCommand("/scan_cameras", "Quét camera index 0-5"),
    telebot.types.BotCommand("/test_camera", "Chụp thử camera hiện tại"),
    telebot.types.BotCommand("/set_camera_index", "Chọn camera 0, 1 hoặc 2"),
    telebot.types.BotCommand("/set_camera_width", "Chỉnh chiều rộng camera"),
    telebot.types.BotCommand("/set_camera_height", "Chỉnh chiều cao camera"),
    telebot.types.BotCommand("/set_camera_fps", "Chỉnh FPS camera"),
    telebot.types.BotCommand("/set_camera_rotation", "Xoay ảnh camera 0/90/180/270 độ")
])

def tail_error_log(max_lines=20):
    if not os.path.exists(ERROR_LOG_FILE):
        return "Chưa có log lỗi nào."

    try:
        with open(ERROR_LOG_FILE, "r", encoding="utf-8") as file:
            lines = file.readlines()
    except OSError as e:
        log_error("Khong doc duoc bot_errors.log", e)
        return f"Không đọc được log lỗi: {e}"

    ignored_levels = (" [DEBUG] ", " [INFO] ", " [WARNING] ")
    lines = [
        line.rstrip()
        for line in lines
        if not any(level in line for level in ignored_levels)
    ][-max_lines:]
    if not lines:
        return "Chưa có log lỗi nào."
    return "\n".join(lines)

def send_alert_history(chat_id, limit=HISTORY_PREVIEW_LIMIT):
    entries = get_recent_alert_history(limit)
    try:
        bot.send_message(chat_id, format_alert_history_message(entries, format_timestamp))
    except Exception as e:
        log_error("Khong gui duoc summary lich su canh bao", e)
        return

    for index, entry in enumerate(entries, start=1):
        timestamp = format_timestamp(entry.get("timestamp"))
        image_path = absolute_from_base(entry.get("image_path"))
        video_path = absolute_from_base(entry.get("video_path"))

        if image_path and os.path.exists(image_path):
            try:
                with open(image_path, "rb") as photo:
                    bot.send_photo(chat_id, photo, caption=f"📸 Cảnh báo #{index} - {timestamp}")
            except Exception as e:
                log_error(f"Khong gui duoc anh lich su #{index}", e)

        if video_path and os.path.exists(video_path):
            try:
                with open(video_path, "rb") as video:
                    bot.send_video(chat_id, video, caption=f"🎥 Video cảnh báo #{index}", timeout=150)
            except Exception as e:
                log_error(f"Khong gui duoc video lich su #{index}", e)


def run_camera_action_with_radar_paused(action):
    was_auto = motion_monitor.is_radar_active()
    if was_auto:
        motion_monitor.set_radar_state(False)
        time.sleep(1.5)

    try:
        return action()
    finally:
        if was_auto:
            motion_monitor.set_radar_state(True)


def build_camera_scan_message():
    settings_snapshot = get_settings_snapshot()
    results = run_camera_action_with_radar_paused(
        lambda: scan_camera_indices(range(6), camera_config=settings_snapshot)
    )
    return format_camera_scan_results(
        results,
        current_index=settings_snapshot["camera_index"]
    )


def capture_camera_test_image():
    settings_snapshot = get_settings_snapshot()
    success, img = run_camera_action_with_radar_paused(
        lambda: read_camera_frame(warmup_seconds=1, camera_config=settings_snapshot)
    )
    camera_text = format_camera_config(settings_snapshot)
    if not success:
        return {
            "ok": False,
            "message": f"Không đọc được ảnh từ {camera_text}.",
            "path": "",
        }

    os.makedirs(LOG_DIR, exist_ok=True)
    image_path = os.path.join(LOG_DIR, "camera_test.jpg")
    save_frame(image_path, img)
    return {
        "ok": True,
        "message": f"Test camera OK\n{camera_text}",
        "path": image_path,
    }


def scan_cameras_for_chat(chat_id):
    bot.send_message(chat_id, "🔎 Đang quét camera index 0-5...")

    try:
        bot.send_message(chat_id, build_camera_scan_message())
    except Exception as e:
        log_error("Quet camera that bai", e)
        bot.send_message(chat_id, f"❌ Không quét được camera: {e}")


def test_camera_for_chat(chat_id):
    settings_snapshot = get_settings_snapshot()
    bot.send_message(chat_id, f"🧪 Đang chụp thử {format_camera_config(settings_snapshot)}...")

    try:
        result = capture_camera_test_image()
    except Exception as e:
        log_error("Chup thu camera that bai", e)
        bot.send_message(chat_id, f"❌ Không chụp thử được camera: {e}")
        return

    if not result["ok"]:
        bot.send_message(chat_id, f"❌ {result['message']}")
        return

    try:
        with open(result["path"], "rb") as photo:
            bot.send_photo(
                chat_id,
                photo,
                caption=f"🧪 {result['message']}"
            )
    except Exception as e:
        log_error("Khong gui duoc anh test camera", e)
        bot.send_message(chat_id, f"⚠️ Đã chụp thử camera nhưng gửi Telegram thất bại: {e}")


def dashboard_scan_cameras():
    try:
        return build_camera_scan_message()
    except Exception as e:
        log_error("Dashboard quet camera that bai", e)
        return f"Không quét được camera: {e}"


def dashboard_test_camera():
    try:
        return capture_camera_test_image()
    except Exception as e:
        log_error("Dashboard chup thu camera that bai", e)
        return {
            "ok": False,
            "message": f"Không chụp thử được camera: {e}",
            "path": "",
        }


def capture_and_analyze_environment(chat_id, question, reply_to_message=None):
    if reply_to_message is None:
        bot.send_message(chat_id, "👁️ Đang chụp ảnh phân tích theo lệnh...")
    else:
        bot.reply_to(reply_to_message, "👁️ Đang chụp ảnh phân tích theo lệnh...")

    was_auto = motion_monitor.is_radar_active()
    if was_auto:
        motion_monitor.set_radar_state(False)
        time.sleep(1.5)

    success = False
    try:
        success, img = read_camera_frame(
            warmup_seconds=1,
            camera_config=get_settings_snapshot()
        )
    finally:
        if was_auto:
            motion_monitor.set_radar_state(True)

    if not success:
        error_message = "❌ Lỗi: Không thể khởi động Camera. Có rào cản từ hệ thống."
        log_error("Khong the chup anh theo yeu cau: camera khong doc duoc frame")
        if reply_to_message is None:
            bot.send_message(chat_id, error_message)
        else:
            bot.reply_to(reply_to_message, error_message)
        return

    image_path = os.path.join(BASE_DIR, "anh_telegram.jpg")
    save_frame(image_path, img)

    try:
        answer = ask_ai(image_path, question)
        caption = f"🤖:\n\n{answer}"
    except Exception as e:
        log_error("Gemini loi khi chup anh theo yeu cau", e)
        caption = f"📸 Ảnh đã chụp\n⚠️ Lỗi Tín hiệu Não từ Google: {e}"

    try:
        with open(image_path, 'rb') as photo:
            bot.send_photo(chat_id, photo, caption=caption)
    except Exception as e:
        log_error("Khong gui duoc anh chup theo yeu cau", e)

def format_timestamp(timestamp):
    if timestamp is None:
        return "Chưa có cảnh báo nào"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

def create_motion_monitor_context():
    return MotionMonitorContext(
        bot=bot,
        log_dir=LOG_DIR,
        get_setting=get_setting,
        get_settings_snapshot=get_settings_snapshot,
        add_alert_history=add_alert_history,
        make_alert_id=make_alert_id,
        ensure_log_dir=ensure_log_dir,
        relative_to_base=relative_to_base,
        ask_ai=ask_ai,
        log_error=log_error
    )

motion_monitor = MotionMonitor(create_motion_monitor_context())

def create_status_report_context():
    return StatusReportContext(
        bot_start_time=BOT_START_TIME,
        dashboard_url=DASHBOARD_URL,
        log_dir=LOG_DIR,
        get_camera_status=motion_monitor.get_camera_status_for_report,
        is_bot_running=lambda: True,
        is_radar_active=motion_monitor.is_radar_active,
        get_last_alert_timestamp=motion_monitor.get_last_alert_timestamp,
        get_alert_history_count=get_alert_history_count,
        get_settings_snapshot=get_settings_snapshot,
        format_timestamp=format_timestamp,
        format_settings_snapshot=format_settings_snapshot,
        log_error=log_error
    )

def create_dashboard_context():
    return DashboardContext(
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        url=DASHBOARD_URL,
        log_dir=LOG_DIR,
        settings_limits=SETTING_LIMITS,
        setting_labels=SETTING_LABELS,
        setting_units=SETTING_UNITS,
        history_limit_choices=HISTORY_LIMIT_CHOICES,
        bot_start_time=BOT_START_TIME,
        get_settings_snapshot=get_settings_snapshot,
        get_alert_history_snapshot=get_alert_history_snapshot,
        get_camera_status=motion_monitor.get_camera_status_for_dashboard,
        is_bot_running=lambda: True,
        is_radar_active=motion_monitor.is_radar_active,
        format_size=format_size,
        get_directory_size=lambda path: get_directory_size(path, log_error=log_error),
        format_duration=format_duration,
        tail_error_log=tail_error_log,
        format_timestamp=format_timestamp,
        last_alert_timestamp=motion_monitor.get_last_alert_timestamp,
        text_preview=text_preview,
        is_safe_alert_media_path=is_safe_alert_media_path,
        absolute_from_base=absolute_from_base,
        delete_alert_history_entry=delete_alert_history_entry,
        update_setting=update_setting,
        trim_alert_history=trim_alert_history,
        scan_cameras=dashboard_scan_cameras,
        test_camera=dashboard_test_camera,
        list_backups=get_recent_backups,
        restore_settings_backup=restore_settings_backup,
        restore_alert_history_backup=restore_alert_history_backup,
        restore_latest_settings_backup=restore_latest_settings_backup,
        restore_latest_alert_history_backup=restore_latest_alert_history_backup,
        delete_backup=delete_backup,
        clamp_int=clamp_int,
        log_error=log_error,
        add_live_viewer=motion_monitor.add_live_viewer,
        remove_live_viewer=motion_monitor.remove_live_viewer,
        get_latest_frame=motion_monitor.get_latest_frame,
        dashboard_password=DASHBOARD_PASSWORD
    )

def send_startup_notification():
    if CHIEC_CHIA_KHOA_ID_CUA_BAN == 0:
        log_error("Khong gui startup notification vi ALLOWED_USER_ID chua duoc cau hinh.")
        return

    started_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(BOT_START_TIME))
    try:
        bot.send_message(
            CHIEC_CHIA_KHOA_ID_CUA_BAN,
            "✅ Vision Bot đã online.\n"
            f"🕒 Khởi động lúc: {started_at}\n"
            f"🌐 Dashboard local: {DASHBOARD_URL}\n"
            "Gõ /menu để mở bảng điều khiển."
        )
    except Exception as e:
        log_error("Khong gui duoc startup notification", e)

def build_status_message():
    return format_status_message(create_status_report_context())

_daily_summary_thread = None


def get_daily_summary_target_chat_id():
    if CHIEC_CHIA_KHOA_ID_CUA_BAN != 0:
        return CHIEC_CHIA_KHOA_ID_CUA_BAN
    return motion_monitor.get_monitoring_chat_id()


def daily_status_summary_loop():
    last_sent_marker = None
    last_missing_target_log_time = 0
    while True:
        try:
            settings_snapshot = get_settings_snapshot()
            enabled, hour, minute = get_daily_summary_schedule(settings_snapshot)
            if not enabled:
                last_sent_marker = None
                time.sleep(30)
                continue

            now = time.localtime()
            current_marker = time.strftime("%Y-%m-%d", now)
            if now.tm_hour == hour and now.tm_min == minute and last_sent_marker != current_marker:
                target_chat_id = get_daily_summary_target_chat_id()
                if target_chat_id:
                    try:
                        bot.send_message(target_chat_id, build_status_message())
                    except Exception as e:
                        log_error("Khong gui duoc tom tat trang thai hang ngay", e)
                    finally:
                        last_sent_marker = current_marker
                else:
                    if time.time() - last_missing_target_log_time > 3600:
                        log_error("Khong gui duoc tom tat trang thai hang ngay vi chua co chat dich")
                        last_missing_target_log_time = time.time()
        except Exception as e:
            log_error("Loi trong vong lap daily_status_summary_loop", e)
        time.sleep(30)


def start_daily_status_summary_scheduler():
    global _daily_summary_thread
    if _daily_summary_thread is not None and _daily_summary_thread.is_alive():
        return _daily_summary_thread

    _daily_summary_thread = threading.Thread(target=daily_status_summary_loop, daemon=True)
    _daily_summary_thread.start()
    return _daily_summary_thread

def get_recent_backups(limit=5):
    return list_backups(BACKUP_DIR, limit=limit, log_error=log_error)

def create_telegram_handler_context():
    return TelegramHandlerContext(
        bot=bot,
        allowed_user_id=CHIEC_CHIA_KHOA_ID_CUA_BAN,
        get_setting=get_setting,
        update_setting=update_setting,
        trim_alert_history=trim_alert_history,
        clear_alert_history_files=clear_alert_history_files,
        set_radar_state=motion_monitor.set_radar_state,
        build_status_message=build_status_message,
        list_backups=get_recent_backups,
        restore_latest_settings_backup=restore_latest_settings_backup,
        restore_latest_alert_history_backup=restore_latest_alert_history_backup,
        format_timestamp=format_timestamp,
        format_size=format_size,
        send_alert_history=send_alert_history,
        capture_and_analyze_environment=capture_and_analyze_environment,
        scan_cameras=scan_cameras_for_chat,
        test_camera=test_camera_for_chat,
        schedule_bot_restart=schedule_bot_restart,
        tail_error_log=tail_error_log,
        log_error=log_error,
        get_dashboard_url=lambda: cloudflared_tunnel.get_url() or DASHBOARD_URL
    )

from vision_bot_core.cloudflared_tunnel import CloudflaredTunnel
cloudflared_tunnel = CloudflaredTunnel(DASHBOARD_PORT, logger=log_error)

motion_monitor.start()
start_daily_status_summary_scheduler()
register_telegram_handlers(create_telegram_handler_context())

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
        print("❌ LỖI: Token vắng mặt")
    else:
        print("🚀 Khởi chạy hệ điều hành BOT GIÁM SÁT KÉP (Nhận lệnh liên tục!).")
        cloudflared_tunnel.start()
        start_dashboard_server(create_dashboard_context())
        send_startup_notification()
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        finally:
            cloudflared_tunnel.stop()
