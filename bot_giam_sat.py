import telebot
import cv2
import sys
import os
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

# Khởi tạo kết nối
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

# Tự động ghim Menu Lệnh lên màn hình chat Telegram
bot.set_my_commands([
    telebot.types.BotCommand("/start", "Xem hướng dẫn các chức năng"),
    telebot.types.BotCommand("/auto", "🔴 BẬT Radar: Quét và báo động tự động 24/7"),
    telebot.types.BotCommand("/stop", "🟢 TẮT Radar: Cho phép camera đi ngủ")
])

# Cơ chế Threading
auto_mode_active = False
monitoring_chat_id = None
last_gray_frame = None

def ask_ai(image_path, user_question):
    img = Image.open(image_path)
    prompt = f"Bạn là bộ não an ninh. Chủ vừa yêu cầu: '{user_question}'. \n Hãy quan sát tỷ mỉ ảnh camera trực tiếp này và trả lời cực kỳ ngắn gọn, khách quan."
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[prompt, img]
    )
    return response.text

# --- TÍNH NĂNG ĐẶC BIỆT: LUỒNG CHẠY NGẦM BẮT CHUYỂN ĐỘNG THEO THỜI GIAN THỰC ---
def motion_detection_loop():
    global auto_mode_active, monitoring_chat_id, last_gray_frame
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
                time.sleep(1)
                continue
                
            # Trạng thái BẬT - Ép camera chạy liên tục không nghỉ
            if camera_stream is None:
                camera_stream = cv2.VideoCapture(0)
                time.sleep(1.5) # Để camera hấp thụ ánh sáng
                # Xả bộ nhớ đệm (buffer) bị kẹt của các giây trước đó
                for _ in range(5):
                    camera_stream.read()
                
            success, img = camera_stream.read()
            if not success:
                time.sleep(0.5)
                continue
                
            # NẾU SAU KHI VỪA CẢNH BÁO XONG: Chờ 10 giây (theo thiết lập của Boss) để không bị spam tin 
            # Nhưng KHÔNG ĐƯỢC dùng time.sleep làm kẹt luồng ở đây
            if time.time() - last_alert_time < 10:
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
            for contour in contours:
                if cv2.contourArea(contour) > 8000: 
                    co_chuyen_dong = True
                    break
                    
            # NẾU PHÁT HIỆN SỰ XÊ DỊCH LỚN TRONG PHÒNG
            if co_chuyen_dong:
                last_alert_time = time.time() # Cập nhật lại mốc thời gian vừa báo động
                cv2.imwrite("canh_bao.jpg", img)
                bot.send_message(monitoring_chat_id, "🚨 BÁO ĐỘNG KÍCH HOẠT: Phát hiện có sự dịch chuyển lớn trong phòng!")
                
                try:
                    # Chuyển ngay lệnh Tự suy luận cho Gemini phân tích
                    ans = ask_ai("canh_bao.jpg", "Báo động có sự chuyển động. Đó là con người hay một con vật? Bọn họ đang định làm gì?")
                    with open("canh_bao.jpg", 'rb') as photo:
                        bot.send_photo(monitoring_chat_id, photo, caption=f"🧠 Phân tích hiện trường:\n\n{ans}")
                except Exception as e:
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

def verify_user(message):
    """ Hàm lọc vân tay xác thực lại ID """
    user_id = message.from_user.id
    if CHIEC_CHIA_KHOA_ID_CUA_BAN != 0 and user_id != CHIEC_CHIA_KHOA_ID_CUA_BAN:
        bot.reply_to(message, "⛔ Tôi không nhận lệnh từ người lạ.")
        return False
    return True

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not verify_user(message): return
    bot.reply_to(message, "👋 Chào Boss, Trung tâm Giám sát Cơ sở.\n\n"
                          "⚙️ Dưới đây là các loại vũ khí:\n"
                          "👉 Gõ lệnh `/auto` : BẬT Lưới Laser Tự động báo động.\n"
                          "👉 Gõ lệnh `/stop` : TẮT báo động, nhường đường lại cho tự nhiên.\n"
                          "👉 Hoặc просто Nhắn bất cứ gì (Tôi sẽ tự chụp 1 tấm để giải tỏa thắc mắc).")

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
