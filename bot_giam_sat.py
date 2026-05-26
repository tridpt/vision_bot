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
    make_alert_id,
    relative_to_base,
    text_preview,
    trim_alert_history as trim_alert_history_unprotected,
)
from vision_bot_core.backup_store import backup_json_files
from vision_bot_core.camera_tools import (
    build_motion_gray,
    check_camera_once,
    has_large_motion,
    open_camera,
    read_camera_frame,
    record_alert_video,
    save_frame,
    warm_up_camera,
)
from vision_bot_core.dashboard_server import DashboardContext, start_dashboard_server
from vision_bot_core.gemini_analyzer import ask_ai, configure_gemini_analyzer
from vision_bot_core.settings_store import (
    HISTORY_LIMIT_CHOICES,
    SETTING_LABELS,
    SETTING_LIMITS,
    SETTING_UNITS,
    clamp_int,
    configure_settings_store,
    get_setting,
    get_settings_snapshot,
    update_setting as save_setting,
)
from vision_bot_core.status_report import (
    StatusReportContext,
    format_duration,
    format_size,
    format_status_message,
    get_directory_size,
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
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Tự động ghim Menu Lệnh lên màn hình chat Telegram
bot.set_my_commands([
    telebot.types.BotCommand("/start", "Xem hướng dẫn các chức năng"),
    telebot.types.BotCommand("/menu", "Mở menu điều khiển bằng nút bấm"),
    telebot.types.BotCommand("/auto", "🔴 BẬT Radar: Quét và báo động tự động 24/7"),
    telebot.types.BotCommand("/stop", "🟢 TẮT Radar: Cho phép camera đi ngủ"),
    telebot.types.BotCommand("/status", "Xem trạng thái bot, radar, camera và cảnh báo gần nhất")
])

# Cơ chế Threading
auto_mode_active = False
monitoring_chat_id = None
last_gray_frame = None
camera_online = False
last_camera_status = "Chưa kiểm tra camera"
last_alert_timestamp = None

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
                    bot.send_video(chat_id, video, caption=f"🎥 Video cảnh báo #{index}")
            except Exception as e:
                log_error(f"Khong gui duoc video lich su #{index}", e)

def capture_and_analyze_environment(chat_id, question, reply_to_message=None):
    global auto_mode_active

    if reply_to_message is None:
        bot.send_message(chat_id, "👁️ Đang chụp ảnh phân tích theo lệnh...")
    else:
        bot.reply_to(reply_to_message, "👁️ Đang chụp ảnh phân tích theo lệnh...")

    was_auto = auto_mode_active
    if was_auto:
        auto_mode_active = False
        time.sleep(1.5)

    success = False
    try:
        success, img = read_camera_frame(warmup_seconds=1)
    finally:
        if was_auto:
            auto_mode_active = True

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

def get_camera_status_for_report():
    if auto_mode_active:
        return camera_online, last_camera_status
    return check_camera_once()

def get_camera_status_for_dashboard():
    if auto_mode_active:
        return camera_online, last_camera_status
    if last_camera_status and last_camera_status != "Chưa kiểm tra camera":
        return camera_online, last_camera_status
    return False, "Camera chưa kiểm tra trên dashboard"

def is_radar_active():
    return auto_mode_active

def get_last_alert_timestamp():
    return last_alert_timestamp

def create_status_report_context():
    return StatusReportContext(
        bot_start_time=BOT_START_TIME,
        dashboard_url=DASHBOARD_URL,
        log_dir=LOG_DIR,
        get_camera_status=get_camera_status_for_report,
        is_radar_active=is_radar_active,
        get_last_alert_timestamp=get_last_alert_timestamp,
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
        get_camera_status=get_camera_status_for_dashboard,
        is_radar_active=is_radar_active,
        format_size=format_size,
        get_directory_size=lambda path: get_directory_size(path, log_error=log_error),
        format_duration=format_duration,
        tail_error_log=tail_error_log,
        format_timestamp=format_timestamp,
        last_alert_timestamp=get_last_alert_timestamp,
        text_preview=text_preview,
        is_safe_alert_media_path=is_safe_alert_media_path,
        absolute_from_base=absolute_from_base,
        delete_alert_history_entry=delete_alert_history_entry,
        update_setting=update_setting,
        trim_alert_history=trim_alert_history,
        clamp_int=clamp_int,
        log_error=log_error
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

# --- TÍNH NĂNG ĐẶC BIỆT: LUỒNG CHẠY NGẦM BẮT CHUYỂN ĐỘNG THEO THỜI GIAN THỰC ---
def motion_detection_loop():
    global auto_mode_active, monitoring_chat_id, last_gray_frame
    global camera_online, last_camera_status, last_alert_timestamp
    camera_stream = None
    last_alert_time = 0 # Lưu thời điểm cảnh báo cuối cùng
    last_camera_error_log_time = 0
    
    while True:
        try:
            # Nếu đang ở Trạng thái TẮT, giải phóng camera ngay lập tức
            if not auto_mode_active or monitoring_chat_id is None:
                if camera_stream is not None:
                    camera_stream.release()
                    camera_stream = None
                    last_gray_frame = None
                    camera_online = False
                    last_camera_status = "Camera đang nghỉ vì radar tắt"
                time.sleep(1)
                continue
                
            # Trạng thái BẬT - Ép camera chạy liên tục không nghỉ
            if camera_stream is None:
                camera_stream = open_camera()
                time.sleep(1.5) # Để camera hấp thụ ánh sáng
                if not camera_stream.isOpened():
                    camera_online = False
                    last_camera_status = "Radar bật nhưng không mở được camera"
                    if time.time() - last_camera_error_log_time > 60:
                        log_error(last_camera_status)
                        last_camera_error_log_time = time.time()
                    camera_stream.release()
                    camera_stream = None
                    time.sleep(2)
                    continue
                # Xả bộ nhớ đệm (buffer) bị kẹt của các giây trước đó
                warm_up_camera(camera_stream, delay_seconds=0, buffer_reads=5)
                
            success, img = camera_stream.read()
            if not success:
                camera_online = False
                last_camera_status = "Radar bật nhưng không đọc được ảnh từ camera"
                if time.time() - last_camera_error_log_time > 60:
                    log_error(last_camera_status)
                    last_camera_error_log_time = time.time()
                time.sleep(0.5)
                continue
            camera_online = True
            last_camera_status = "Camera đang mở bởi radar"
                
            # NẾU SAU KHI VỪA CẢNH BÁO XONG: Chờ 10 giây (theo thiết lập của Boss) để không bị spam tin 
            # Nhưng KHÔNG ĐƯỢC dùng time.sleep làm kẹt luồng ở đây
            if time.time() - last_alert_time < get_setting("alert_cooldown_seconds"):
                last_gray_frame = build_motion_gray(img)
                time.sleep(0.1)
                continue
                
            # Thuật toán Dò sự xê dịch: Chuyển ảnh màu về khung xám
            gray = build_motion_gray(img)
            
            if last_gray_frame is None:
                last_gray_frame = gray
                continue
                
            motion_area_threshold = get_setting("motion_area_threshold")
            co_chuyen_dong = has_large_motion(last_gray_frame, gray, motion_area_threshold)
                    
            # NẾU PHÁT HIỆN SỰ XÊ DỊCH LỚN TRONG PHÒNG
            if co_chuyen_dong:
                last_alert_time = time.time() # Cập nhật lại mốc thời gian vừa báo động
                last_alert_timestamp = last_alert_time
                alert_id = make_alert_id(last_alert_time)
                ensure_log_dir()
                image_path = os.path.join(LOG_DIR, f"alert_{alert_id}.jpg")
                video_path = None
                video_status = "Không ghi video"
                analysis = "Gemini đang tắt"
                save_frame(image_path, img)
                bot.send_message(monitoring_chat_id, "🚨 BÁO ĐỘNG KÍCH HOẠT: Phát hiện có sự dịch chuyển lớn trong phòng!")

                if get_setting("send_video"):
                    video_path = os.path.join(LOG_DIR, f"alert_{alert_id}.mp4")
                    video_seconds = get_setting("alert_video_seconds")
                    video_fps = get_setting("alert_video_fps")
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
                                bot.send_video(
                                    monitoring_chat_id,
                                    video,
                                    caption=f"🎥 Clip cảnh báo {video_seconds} giây\n{video_status}"
                                )
                        except Exception as e:
                            log_error("Da ghi video canh bao nhung gui Telegram that bai", e)
                            bot.send_message(monitoring_chat_id, f"⚠️ Đã ghi video nhưng gửi Telegram thất bại: {e}")
                    else:
                        bot.send_message(monitoring_chat_id, f"⚠️ Không ghi được video cảnh báo: {video_status}")
                        video_path = None
                else:
                    video_status = "Đã tắt gửi video trong setting"

                if get_setting("use_gemini_analysis"):
                    try:
                        # Chuyển ngay lệnh Tự suy luận cho Gemini phân tích
                        analysis = ask_ai(image_path, "Báo động có sự chuyển động. Đó là con người hay một con vật? Bọn họ đang định làm gì?")
                        with open(image_path, 'rb') as photo:
                            bot.send_photo(monitoring_chat_id, photo, caption=f"🧠 Phân tích hiện trường:\n\n{analysis}")
                    except Exception as e:
                        log_error("Gemini loi khi phan tich canh bao", e)
                        analysis = f"Gemini lỗi: {e}"
                        try:
                            with open(image_path, 'rb') as photo:
                                bot.send_photo(monitoring_chat_id, photo, caption=f"📸 Ảnh cảnh báo\n⚠️ Gemini lỗi: {e}")
                        except Exception as send_error:
                            log_error("Khong gui duoc anh canh bao sau khi Gemini loi", send_error)
                else:
                    try:
                        with open(image_path, 'rb') as photo:
                            bot.send_photo(monitoring_chat_id, photo, caption="📸 Ảnh cảnh báo")
                    except Exception as e:
                        log_error("Khong gui duoc anh canh bao khi tat Gemini", e)

                add_alert_history({
                    "id": alert_id,
                    "timestamp": last_alert_time,
                    "image_path": relative_to_base(image_path),
                    "video_path": relative_to_base(video_path) if video_path else None,
                    "video_status": video_status,
                    "analysis": analysis,
                    "settings": get_settings_snapshot()
                })
                
                last_gray_frame = gray
                continue
                
            last_gray_frame = gray
            # Quét siêu nhanh để camera cập nhật đúng thời gian thực
            time.sleep(0.1)
        except Exception as e:
            log_error("Loi trong vong lap motion_detection_loop", e)
            time.sleep(5)

# Bật luồng chạy ngầm đa nhiệm (Luôn song hành với Telegram)
t = threading.Thread(target=motion_detection_loop, daemon=True)
t.start()


def set_radar_state(active, chat_id=None):
    global auto_mode_active, monitoring_chat_id
    auto_mode_active = active
    if chat_id is not None:
        monitoring_chat_id = chat_id

def build_status_message():
    return format_status_message(create_status_report_context())

def create_telegram_handler_context():
    return TelegramHandlerContext(
        bot=bot,
        allowed_user_id=CHIEC_CHIA_KHOA_ID_CUA_BAN,
        get_setting=get_setting,
        update_setting=update_setting,
        trim_alert_history=trim_alert_history,
        clear_alert_history_files=clear_alert_history_files,
        set_radar_state=set_radar_state,
        build_status_message=build_status_message,
        send_alert_history=send_alert_history,
        capture_and_analyze_environment=capture_and_analyze_environment,
        schedule_bot_restart=schedule_bot_restart,
        tail_error_log=tail_error_log,
        log_error=log_error
    )

register_telegram_handlers(create_telegram_handler_context())

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
        print("❌ LỖI: Token vắng mặt")
    else:
        print("🚀 Khởi chạy hệ điều hành BOT GIÁM SÁT KÉP (Nhận lệnh liên tục!).")
        start_dashboard_server(create_dashboard_context())
        send_startup_notification()
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
