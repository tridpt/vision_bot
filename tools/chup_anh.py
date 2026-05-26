import cv2
import sys

# Khắc phục lỗi in chữ tiếng Việt trên Windows Terminal
sys.stdout.reconfigure(encoding='utf-8')

def capture_image():
    print("Đang bật Camera...")
    # Số 0 đại diện cho webcam mặc định. 
    # Nếu có gắn thêm camera USB ngoài, có thể thử đổi thành 1 hoặc 2.
    camera = cv2.VideoCapture(0)

    # Chờ 1 giây để camera kịp lấy sáng, chống mờ ảnh
    cv2.waitKey(1000)

    # Đọc khung hình từ camera
    kiem_tra, hinh_anh = camera.read()

    if kiem_tra:
        # Nếu đọc thành công, lưu ảnh lại
        ten_file = "anh_nha_cua.jpg"
        cv2.imwrite(ten_file, hinh_anh)
        print(f"✅ Tuyệt vời! Đã chụp ảnh thành công và lưu với tên: {ten_file}")
    else:
        print("❌ Lỗi: Không thể kết nối với camera. Hãy kiểm tra xem có phần mềm nào khác (Zoom, Meet...) đang dùng camera không.")

    # Tắt camera để giải phóng tài nguyên
    camera.release()

if __name__ == "__main__":
    capture_image()
