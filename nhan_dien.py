import sys
import os
from PIL import Image
from google import genai
from dotenv import load_dotenv

# Sửa lỗi hiển thị tiếng Việt trên Terminal của Windows
sys.stdout.reconfigure(encoding='utf-8')

def analyze_image():
    load_dotenv()
    API_KEY = os.getenv("GEMINI_API_KEY")
    
    if not API_KEY:
        print("❌ Chưa tìm thấy GEMINI_API_KEY trong file .env. Hãy thêm key vào .env rồi chạy lại nhé.")
        return

    print("Đang khởi động tư duy AI và đọc ảnh...")
    
    # Khởi tạo thuật toán 
    client = genai.Client(api_key=API_KEY)

    try:
        # Tải bức ảnh bạn vừa chụp ở Bước 1
        ten_anh = "anh_nha_cua.jpg"
        img = Image.open(ten_anh)
        
        # Đưa ảnh vào mô hình AI siêu tốc Gemini 2.5 Flash
        print("Đang hỏi trí tuệ nhân tạo Gemini...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=['Dựa trên bức ảnh này, hãy miêu tả cho tôi biết có những sự vật, con người hay hiện tượng gì đang xuất hiện? Hãy mô tả thật tự nhiên bằng tiếng Việt.', img]
        )
        
        print("\n🤖 Trợ lý AI Trả lời:")
        print("="*50)
        print(response.text)
        print("="*50)
        
    except FileNotFoundError:
        print(f"❌ Không tìm thấy file '{ten_anh}'. Hãy chắc chắn bạn đã chạy file chup_anh.py trước đó nhé.")
    except Exception as e:
        print(f"❌ Đã gặp lỗi: {e}")

if __name__ == "__main__":
    analyze_image()
