import telebot
import cv2
import sys
import os
import json
import threading
import time
from PIL import Image
from google import genai
from dotenv import load_dotenv

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# --- BẢO MẬT: Load thông tin bí mật từ file .env ---
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CHIEC_CHIA_KHOA_ID_CUA_BAN = int(os.getenv("ALLOWED_USER_ID", 0))

SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {
    "motion_area_threshold": 8000,
    "alert_cooldown_seconds": 10,
    "alert_video_seconds": 7,
    "alert_video_fps": 10,
    "send_video": True,
    "use_gemini_analysis": True
}

SETTING_LIMITS = {
    "motion_area_threshold": (500, 50000),
    "alert_cooldown_seconds": (3, 3600),
    "alert_video_seconds": (5, 10),
    "alert_video_fps": (5, 30)
}

# Khởi tạo kết nối
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

# Tự động ghim Menu Lệnh lên màn hình chat Telegram
bot.set_my_commands([
    telebot.types.BotCommand("/start", "Xem hướng dẫn các chức năng"),
    telebot.types.BotCommand("/menu", "Mở menu điều khiển bằng nút bấm"),
    telebot.types.BotCommand("/auto", "🔴 BẬT Radar: Quét và báo động tự động 24/7"),
    telebot.types.BotCommand("/stop", "🟢 TẮT Radar: Cho phép camera đi ngủ"),
    telebot.types.BotCommand("/status", "Xem trạng thái bot, radar, camera và cảnh báo gần nhất"),
    telebot.types.BotCommand("/settings", "Xem cấu hình hiện tại và các lệnh chỉnh bot"),
    telebot.types.BotCommand("/set_sensitivity", "Chỉnh ngưỡng chuyển động, số nhỏ nhạy hơn"),
    telebot.types.BotCommand("/set_cooldown", "Chỉnh thời gian chống spam cảnh báo"),
    telebot.types.BotCommand("/set_video_seconds", "Chỉnh độ dài clip cảnh báo từ 5 đến 10 giây"),
    telebot.types.BotCommand("/set_video_fps", "Chỉnh FPS clip cảnh báo từ 5 đến 30"),
    telebot.types.BotCommand("/video_on", "Bật gửi video cảnh báo"),
    telebot.types.BotCommand("/video_off", "Tắt gửi video cảnh báo"),
    telebot.types.BotCommand("/ai_on", "Bật phân tích Gemini khi cảnh báo"),
    telebot.types.BotCommand("/ai_off", "Tắt phân tích Gemini khi cảnh báo")
])

# Cơ chế Threading
auto_mode_active = False
monitoring_chat_id = None
last_gray_frame = None
camera_online = False
last_camera_status = "Chưa kiểm tra camera"
last_alert_timestamp = None
settings_lock = threading.Lock()

def clamp_int(value, default, min_value, max_value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(min_value, min(number, max_value))

def normalize_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "bat", "bật")
    if value in (0, 1):
        return bool(value)
    return default

def normalize_settings(raw_settings):
    normalized = DEFAULT_SETTINGS.copy()
    if isinstance(raw_settings, dict):
        normalized.update({key: raw_settings[key] for key in DEFAULT_SETTINGS if key in raw_settings})

    for key, (min_value, max_value) in SETTING_LIMITS.items():
        normalized[key] = clamp_int(normalized[key], DEFAULT_SETTINGS[key], min_value, max_value)

    normalized["send_video"] = normalize_bool(
        normalized["send_video"],
        DEFAULT_SETTINGS["send_video"]
    )
    normalized["use_gemini_analysis"] = normalize_bool(
        normalized["use_gemini_analysis"],
        DEFAULT_SETTINGS["use_gemini_analysis"]
    )
    return normalized

def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
            return normalize_settings(json.load(file))
    except FileNotFoundError:
        return DEFAULT_SETTINGS.copy()
    except (json.JSONDecodeError, OSError):
        return DEFAULT_SETTINGS.copy()

def save_settings(settings_to_save):
    temp_file = f"{SETTINGS_FILE}.tmp"
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(settings_to_save, file, ensure_ascii=False, indent=2)
    os.replace(temp_file, SETTINGS_FILE)

settings = load_settings()

def get_setting(name):
    with settings_lock:
        return settings[name]

def get_settings_snapshot():
    with settings_lock:
        return settings.copy()

def update_setting(name, value):
    with settings_lock:
        settings[name] = value
        save_settings(settings.copy())

def on_off_label(value):
    return "BẬT" if value else "TẮT"

def format_settings_message():
    current = get_settings_snapshot()
    return (
        "⚙️ CÀI ĐẶT VISION BOT\n\n"
        f"🎯 Độ nhạy chuyển động: {current['motion_area_threshold']} "
        "(số nhỏ nhạy hơn)\n"
        f"⏱️ Cooldown cảnh báo: {current['alert_cooldown_seconds']} giây\n"
        f"🎥 Độ dài video: {current['alert_video_seconds']} giây\n"
        f"🎞️ FPS video: {current['alert_video_fps']}\n"
        f"📹 Gửi video: {on_off_label(current['send_video'])}\n"
        f"🧠 Phân tích Gemini: {on_off_label(current['use_gemini_analysis'])}\n\n"
        "Lệnh chỉnh:\n"
        "/set_sensitivity 8000\n"
        "/set_cooldown 20\n"
        "/set_video_seconds 7\n"
        "/set_video_fps 10\n"
        "/video_on hoặc /video_off\n"
        "/ai_on hoặc /ai_off"
    )

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
    update_setting(setting_name, value)
    bot.reply_to(message, f"✅ Đã {on_off_label(value)} {label}.")

def adjust_numeric_setting(setting_name, delta):
    current = get_setting(setting_name)
    min_value, max_value = SETTING_LIMITS[setting_name]
    new_value = max(min_value, min(current + delta, max_value))
    update_setting(setting_name, new_value)
    return new_value

def build_main_menu():
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        telebot.types.InlineKeyboardButton("🟢 Bật Radar", callback_data="menu:auto_on"),
        telebot.types.InlineKeyboardButton("🔴 Tắt Radar", callback_data="menu:auto_off")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("📡 Trạng thái", callback_data="menu:status"),
        telebot.types.InlineKeyboardButton("⚙️ Cài đặt", callback_data="menu:settings")
    )
    return keyboard

def build_settings_menu():
    current = get_settings_snapshot()
    video_label = "📹 Tắt video" if current["send_video"] else "📹 Bật video"
    ai_label = "🧠 Tắt Gemini" if current["use_gemini_analysis"] else "🧠 Bật Gemini"

    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        telebot.types.InlineKeyboardButton("🎯 Nhạy hơn", callback_data="setting:motion_area_threshold:-1000"),
        telebot.types.InlineKeyboardButton("🎯 Ít nhạy hơn", callback_data="setting:motion_area_threshold:1000")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("⏱️ Cooldown -5s", callback_data="setting:alert_cooldown_seconds:-5"),
        telebot.types.InlineKeyboardButton("⏱️ Cooldown +5s", callback_data="setting:alert_cooldown_seconds:5")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("🎥 Video -1s", callback_data="setting:alert_video_seconds:-1"),
        telebot.types.InlineKeyboardButton("🎥 Video +1s", callback_data="setting:alert_video_seconds:1")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("🎞️ FPS -5", callback_data="setting:alert_video_fps:-5"),
        telebot.types.InlineKeyboardButton("🎞️ FPS +5", callback_data="setting:alert_video_fps:5")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton(video_label, callback_data="setting:toggle_video"),
        telebot.types.InlineKeyboardButton(ai_label, callback_data="setting:toggle_ai")
    )
    keyboard.add(telebot.types.InlineKeyboardButton("⬅️ Quay lại menu", callback_data="menu:main"))
    return keyboard

def edit_menu_message(call, text, reply_markup=None):
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=reply_markup
        )
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=reply_markup)

def ask_ai(image_path, user_question):
    img = Image.open(image_path)
    prompt = f"Bạn là bộ não an ninh. Chủ vừa yêu cầu: '{user_question}'. \n Hãy quan sát tỷ mỉ ảnh camera trực tiếp này và trả lời cực kỳ ngắn gọn, khách quan."
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[prompt, img]
    )
    return response.text

def format_timestamp(timestamp):
    if timestamp is None:
        return "Chưa có cảnh báo nào"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

def check_camera_once():
    camera = cv2.VideoCapture(0)
    try:
        time.sleep(0.5)
        if not camera.isOpened():
            return False, "Không mở được camera"
        success, _ = camera.read()
        if success:
            return True, "Mở và đọc được ảnh thử"
        return False, "Mở được camera nhưng không đọc được ảnh"
    finally:
        camera.release()

def get_camera_status_for_report():
    if auto_mode_active:
        return camera_online, last_camera_status
    return check_camera_once()

def format_status_message():
    camera_ok, camera_status = get_camera_status_for_report()
    radar_status = "BẬT" if auto_mode_active else "TẮT"
    camera_icon = "✅" if camera_ok else "❌"
    alert_time = format_timestamp(last_alert_timestamp)

    return (
        "📡 TRẠNG THÁI VISION BOT\n\n"
        "✅ Bot: Đang chạy và nhận lệnh Telegram\n"
        f"📍 Radar: {radar_status}\n"
        f"{camera_icon} Camera: {camera_status}\n"
        f"🚨 Lần cảnh báo gần nhất: {alert_time}"
    )

def record_alert_video(camera_stream, first_frame, video_path, duration_seconds, fps):
    height, width = first_frame.shape[:2]
    width -= width % 2
    height -= height % 2
    frame_size = (width, height)
    writer = cv2.VideoWriter(
        video_path,
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        frame_size
    )
    if not writer.isOpened():
        return False, "Không tạo được file video"

    frames_written = 0
    read_failed = False
    next_frame_time = time.time()
    end_time = time.time() + duration_seconds
    frame = first_frame

    try:
        while time.time() < end_time:
            writer.write(frame[:height, :width])
            frames_written += 1

            success, frame = camera_stream.read()
            if not success:
                read_failed = True
                break

            next_frame_time += 1 / fps
            delay = next_frame_time - time.time()
            if delay > 0:
                time.sleep(delay)
    finally:
        writer.release()

    if frames_written == 0 or not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return False, "Video rỗng hoặc không ghi được frame nào"
    if read_failed:
        return True, "Camera dừng sớm, đã gửi phần video ghi được"
    return True, f"Đã ghi clip {duration_seconds} giây"

# --- TÍNH NĂNG ĐẶC BIỆT: LUỒNG CHẠY NGẦM BẮT CHUYỂN ĐỘNG THEO THỜI GIAN THỰC ---
def motion_detection_loop():
    global auto_mode_active, monitoring_chat_id, last_gray_frame
    global camera_online, last_camera_status, last_alert_timestamp
    camera_stream = None
    last_alert_time = 0 # Lưu thời điểm cảnh báo cuối cùng
    
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
                camera_stream = cv2.VideoCapture(0)
                time.sleep(1.5) # Để camera hấp thụ ánh sáng
                if not camera_stream.isOpened():
                    camera_online = False
                    last_camera_status = "Radar bật nhưng không mở được camera"
                    camera_stream.release()
                    camera_stream = None
                    time.sleep(2)
                    continue
                # Xả bộ nhớ đệm (buffer) bị kẹt của các giây trước đó
                for _ in range(5):
                    camera_stream.read()
                
            success, img = camera_stream.read()
            if not success:
                camera_online = False
                last_camera_status = "Radar bật nhưng không đọc được ảnh từ camera"
                time.sleep(0.5)
                continue
            camera_online = True
            last_camera_status = "Camera đang mở bởi radar"
                
            # NẾU SAU KHI VỪA CẢNH BÁO XONG: Chờ 10 giây (theo thiết lập của Boss) để không bị spam tin 
            # Nhưng KHÔNG ĐƯỢC dùng time.sleep làm kẹt luồng ở đây
            if time.time() - last_alert_time < get_setting("alert_cooldown_seconds"):
                last_gray_frame = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (21, 21), 0)
                time.sleep(0.1)
                continue
                
            # Thuật toán Dò sự xê dịch: Chuyển ảnh màu về khung xám
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)
            
            if last_gray_frame is None:
                last_gray_frame = gray
                continue
                
            # Đem "trừ" hai khoảng khắc liên tiếp cho nhau 
            diff = cv2.absdiff(last_gray_frame, gray)
            thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1]
            thresh = cv2.dilate(thresh, None, iterations=2)
            
            contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            co_chuyen_dong = False
            motion_area_threshold = get_setting("motion_area_threshold")
            for contour in contours:
                if cv2.contourArea(contour) > motion_area_threshold:
                    co_chuyen_dong = True
                    break
                    
            # NẾU PHÁT HIỆN SỰ XÊ DỊCH LỚN TRONG PHÒNG
            if co_chuyen_dong:
                last_alert_time = time.time() # Cập nhật lại mốc thời gian vừa báo động
                last_alert_timestamp = last_alert_time
                cv2.imwrite("canh_bao.jpg", img)
                bot.send_message(monitoring_chat_id, "🚨 BÁO ĐỘNG KÍCH HOẠT: Phát hiện có sự dịch chuyển lớn trong phòng!")

                if get_setting("send_video"):
                    video_path = "canh_bao.mp4"
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
                            bot.send_message(monitoring_chat_id, f"⚠️ Đã ghi video nhưng gửi Telegram thất bại: {e}")
                    else:
                        bot.send_message(monitoring_chat_id, f"⚠️ Không ghi được video cảnh báo: {video_status}")

                if get_setting("use_gemini_analysis"):
                    try:
                        # Chuyển ngay lệnh Tự suy luận cho Gemini phân tích
                        ans = ask_ai("canh_bao.jpg", "Báo động có sự chuyển động. Đó là con người hay một con vật? Bọn họ đang định làm gì?")
                        with open("canh_bao.jpg", 'rb') as photo:
                            bot.send_photo(monitoring_chat_id, photo, caption=f"🧠 Phân tích hiện trường:\n\n{ans}")
                    except Exception as e:
                        try:
                            with open("canh_bao.jpg", 'rb') as photo:
                                bot.send_photo(monitoring_chat_id, photo, caption=f"📸 Ảnh cảnh báo\n⚠️ Gemini lỗi: {e}")
                        except Exception:
                            pass
                else:
                    try:
                        with open("canh_bao.jpg", 'rb') as photo:
                            bot.send_photo(monitoring_chat_id, photo, caption="📸 Ảnh cảnh báo")
                    except Exception:
                        pass
                
                last_gray_frame = gray
                continue
                
            last_gray_frame = gray
            # Quét siêu nhanh để camera cập nhật đúng thời gian thực
            time.sleep(0.1)
        except Exception as e:
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
    bot.reply_to(message, "👋 Chào Boss, Trung tâm Giám sát Cơ sở.\n\n"
                          "⚙️ Dưới đây là các loại vũ khí:\n"
                          "👉 Gõ lệnh `/menu` : Mở bảng điều khiển bằng nút bấm.\n"
                          "👉 Gõ lệnh `/auto` : BẬT Lưới Laser Tự động báo động.\n"
                          "👉 Gõ lệnh `/stop` : TẮT báo động, nhường đường lại cho tự nhiên.\n"
                          "👉 Gõ lệnh `/status` : Kiểm tra bot, radar, camera và cảnh báo gần nhất.\n"
                          "👉 Gõ lệnh `/settings` : Xem và chỉnh cấu hình bot.\n"
                          "👉 Hoặc просто Nhắn bất cứ gì (Tôi sẽ tự chụp 1 tấm để giải tỏa thắc mắc).")

@bot.message_handler(commands=['menu'])
def send_menu(message):
    if not verify_user(message): return
    bot.reply_to(message, "🧭 MENU ĐIỀU KHIỂN VISION BOT", reply_markup=build_main_menu())

@bot.message_handler(commands=['auto'])
def turn_on_auto(message):
    if not verify_user(message): return
    global auto_mode_active, monitoring_chat_id
    auto_mode_active = True
    monitoring_chat_id = message.chat.id
    bot.reply_to(message, "🟢 Đã BẬT Radar Tự động!\n\nCamera hiện tại sẽ luôn mở. Bất kỳ loài vật sống nào tạt qua đều sẽ bị tôi bêu tên và gửi ảnh thẳng đến điện thoại chư vị!\n▶ Để tắt chống hao pin: Gõ lệnh /stop")

@bot.message_handler(commands=['stop'])
def turn_off_auto(message):
    if not verify_user(message): return
    global auto_mode_active
    auto_mode_active = False
    bot.reply_to(message, "🔴 Đã TẮT Radar thụ động. Mắt camera đã tạm đóng kín.")

@bot.message_handler(commands=['status'])
def send_status(message):
    if not verify_user(message): return
    bot.reply_to(message, format_status_message())

@bot.message_handler(commands=['settings'])
def send_settings(message):
    if not verify_user(message): return
    bot.reply_to(message, format_settings_message())

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
        edit_menu_message(call, format_status_message(), build_main_menu())
        return

    if call.data == "menu:settings":
        bot.answer_callback_query(call.id)
        edit_menu_message(call, format_settings_message(), build_settings_menu())
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
    global auto_mode_active
    
    question = message.text
    bot.reply_to(message, "👁️ Đang chụp ảnh phân tích theo lệnh...")
    
    # 💥 HACK: Nếu đang bật Auto mà chủ nhấn lệnh chèn ngang, tạm Tắt luồng Auto 2s để "cướp" quyền Camera
    was_auto = auto_mode_active
    if was_auto:
        auto_mode_active = False
        time.sleep(1.5) # Chờ thread kia nhả camera
        
    camera = cv2.VideoCapture(0)
    time.sleep(1) # Load sáng
    success, img = camera.read()
    camera.release()
    
    # Trả tài nguyên lại cho mạch tự động
    if was_auto:
        auto_mode_active = True
        
    if success:
        cv2.imwrite("anh_telegram.jpg", img)
        try:
            answer = ask_ai("anh_telegram.jpg", question)
            with open("anh_telegram.jpg", 'rb') as photo:
                bot.send_photo(message.chat.id, photo, caption=f"🤖:\n\n{answer}")
        except Exception as e:
            bot.reply_to(message, f"❌ Lỗi Tín hiệu Não từ Google: {e}")
    else:
        bot.reply_to(message, "❌ Lỗi: Không thể khởi động Camera. Có rào cản từ hệ thống.")

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
        print("❌ LỖI: Token vắng mặt")
    else:
        print("🚀 Khởi chạy hệ điều hành BOT GIÁM SÁT KÉP (Nhận lệnh liên tục!).")
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
