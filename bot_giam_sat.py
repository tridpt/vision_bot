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
    build_clear_history_confirm_menu,
    build_main_menu,
    build_restart_confirm_menu,
    build_setting_prompt,
    build_settings_menu,
    format_alert_history_message,
    format_error_log_message,
    format_settings_message,
    format_settings_snapshot,
    on_off_label,
)
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
pending_setting_inputs = {}
pending_setting_lock = threading.Lock()

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

    update_setting(setting_name, value)
    bot.reply_to(message, f"✅ Đã cập nhật {label}: {value}{unit}")

def set_boolean_setting(message, setting_name, value, label):
    clear_pending_setting_input(message)
    update_setting(setting_name, value)
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

def handle_pending_setting_input(message):
    setting_name = pop_pending_setting_input(message)
    if setting_name is None:
        return False

    text = message.text.strip()
    if text.lower() in ("hủy", "huy", "cancel", "/cancel"):
        bot.reply_to(message, "Đã hủy chỉnh setting.", reply_markup=build_settings_menu())
        return True

    try:
        value = int(text)
    except ValueError:
        set_pending_setting_input_from_message(message, setting_name)
        bot.reply_to(message, "Giá trị phải là số nguyên. Nhập lại hoặc gõ hủy.")
        return True

    min_value, max_value = SETTING_LIMITS[setting_name]
    label = SETTING_LABELS[setting_name]
    unit = SETTING_UNITS[setting_name]
    if not min_value <= value <= max_value:
        set_pending_setting_input_from_message(message, setting_name)
        bot.reply_to(message, f"{label} phải nằm trong khoảng {min_value}-{max_value}{unit}. Nhập lại hoặc gõ hủy.")
        return True

    update_setting(setting_name, value)
    bot.reply_to(message, f"✅ Đã cập nhật {label}: {value}{unit}", reply_markup=build_settings_menu())
    return True

def set_pending_setting_input_from_message(message, setting_name):
    with pending_setting_lock:
        pending_setting_inputs[pending_key_from_message(message)] = setting_name

def adjust_numeric_setting(setting_name, delta):
    current = get_setting(setting_name)
    min_value, max_value = SETTING_LIMITS[setting_name]
    new_value = max(min_value, min(current + delta, max_value))
    update_setting(setting_name, new_value)
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
        log_error("Khong edit duoc menu message, fallback sang send_message", e)
        bot.send_message(call.message.chat.id, text, reply_markup=reply_markup)

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


# ===============================================
# --- CÁC LỆNH GIAO TIẾP GIAO DIỆN TELEGRAM ---
# ===============================================

def is_allowed_user(user_id):
    return CHIEC_CHIA_KHOA_ID_CUA_BAN == 0 or user_id == CHIEC_CHIA_KHOA_ID_CUA_BAN

def verify_user(message):
    """ Hàm lọc vân tay xác thực lại ID """
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
                          "👉 Trong `/menu`, chọn Cài đặt hoặc Lịch sử để quản lý bot.\n"
                          "👉 Hoặc просто Nhắn bất cứ gì (Tôi sẽ tự chụp 1 tấm để giải tỏa thắc mắc).")

@bot.message_handler(commands=['menu'])
def send_menu(message):
    if not verify_user(message): return
    clear_pending_setting_input(message)
    bot.reply_to(message, "🧭 MENU ĐIỀU KHIỂN VISION BOT", reply_markup=build_main_menu())

@bot.message_handler(commands=['auto'])
def turn_on_auto(message):
    if not verify_user(message): return
    clear_pending_setting_input(message)
    global auto_mode_active, monitoring_chat_id
    auto_mode_active = True
    monitoring_chat_id = message.chat.id
    bot.reply_to(message, "🟢 Đã BẬT Radar Tự động!\n\nCamera hiện tại sẽ luôn mở. Bất kỳ loài vật sống nào tạt qua đều sẽ bị tôi bêu tên và gửi ảnh thẳng đến điện thoại chư vị!\n▶ Để tắt chống hao pin: Gõ lệnh /stop")

@bot.message_handler(commands=['stop'])
def turn_off_auto(message):
    if not verify_user(message): return
    clear_pending_setting_input(message)
    global auto_mode_active
    auto_mode_active = False
    bot.reply_to(message, "🔴 Đã TẮT Radar thụ động. Mắt camera đã tạm đóng kín.")

@bot.message_handler(commands=['status'])
def send_status(message):
    if not verify_user(message): return
    clear_pending_setting_input(message)
    bot.reply_to(message, format_status_message(create_status_report_context()))

@bot.message_handler(commands=['history'])
def send_history(message):
    if not verify_user(message): return
    clear_pending_setting_input(message)
    send_alert_history(message.chat.id)

@bot.message_handler(commands=['settings'])
def send_settings(message):
    if not verify_user(message): return
    clear_pending_setting_input(message)
    bot.reply_to(message, format_settings_message(), reply_markup=build_settings_menu())

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

@bot.callback_query_handler(func=lambda call: call.data and (call.data.startswith("menu:") or call.data.startswith("setting:")))
def handle_menu_callback(call):
    if not verify_callback(call): return
    global auto_mode_active, monitoring_chat_id

    if call.data == "menu:main":
        bot.answer_callback_query(call.id)
        edit_menu_message(call, "🧭 MENU ĐIỀU KHIỂN VISION BOT", build_main_menu())
        return

    if call.data == "menu:auto_on":
        auto_mode_active = True
        monitoring_chat_id = call.message.chat.id
        bot.answer_callback_query(call.id, "Đã bật radar")
        edit_menu_message(call, "🟢 Đã BẬT Radar Tự động.", build_main_menu())
        return

    if call.data == "menu:auto_off":
        auto_mode_active = False
        bot.answer_callback_query(call.id, "Đã tắt radar")
        edit_menu_message(call, "🔴 Đã TẮT Radar thụ động.", build_main_menu())
        return

    if call.data == "menu:status":
        bot.answer_callback_query(call.id)
        edit_menu_message(call, format_status_message(create_status_report_context()), build_main_menu())
        return

    if call.data == "menu:capture":
        clear_pending_setting_input_from_call(call)
        bot.answer_callback_query(call.id, "Đang chụp ảnh")
        capture_and_analyze_environment(
            call.message.chat.id,
            "Hãy mô tả ngắn gọn camera hiện đang thấy gì và có điều gì đáng chú ý không?"
        )
        return

    if call.data == "menu:history":
        bot.answer_callback_query(call.id, "Đang gửi lịch sử")
        edit_menu_message(call, "🧾 Đang gửi lịch sử cảnh báo gần nhất...", build_main_menu())
        send_alert_history(call.message.chat.id)
        return

    if call.data == "menu:error_log":
        bot.answer_callback_query(call.id, "Đang đọc log lỗi")
        bot.send_message(call.message.chat.id, format_error_log_message(tail_error_log()), parse_mode="Markdown")
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
            schedule_bot_restart()
        except Exception as e:
            log_error("Khong len lich restart bot", e)
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
            clear_alert_history_files()
        except Exception as e:
            log_error("Don lich su canh bao that bai", e)
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
        if setting_name not in SETTING_LIMITS:
            bot.answer_callback_query(call.id, "Setting không hợp lệ", show_alert=True)
            return

        set_pending_setting_input(call, setting_name)
        bot.answer_callback_query(call.id, "Nhập số trong khung chat")
        bot.send_message(call.message.chat.id, build_setting_prompt(setting_name))
        return

    if call.data == "setting:toggle_video":
        update_setting("send_video", not get_setting("send_video"))
        bot.answer_callback_query(call.id, "Đã cập nhật gửi video")
        edit_menu_message(call, format_settings_message(), build_settings_menu())
        return

    if call.data == "setting:toggle_ai":
        update_setting("use_gemini_analysis", not get_setting("use_gemini_analysis"))
        bot.answer_callback_query(call.id, "Đã cập nhật Gemini")
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

        update_setting("alert_history_limit", history_limit)
        trim_alert_history(history_limit)
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
    
    capture_and_analyze_environment(message.chat.id, message.text, reply_to_message=message)

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
        print("❌ LỖI: Token vắng mặt")
    else:
        print("🚀 Khởi chạy hệ điều hành BOT GIÁM SÁT KÉP (Nhận lệnh liên tục!).")
        start_dashboard_server(create_dashboard_context())
        send_startup_notification()
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
