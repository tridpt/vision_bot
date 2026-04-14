# 👁️ Vision AI Bot - Trợ lý Giám sát Camera Thông Minh

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)
![Gemini AI](https://img.shields.io/badge/AI-Google_Gemini-orange.svg)
![OpenCV](https://img.shields.io/badge/cvision-OpenCV-green.svg)

Một hệ thống trợ lý ảo thông minh chạy nội bộ, biến chiếc webcam máy tính của bạn thành một "Cỗ máy giám sát" kết nối với Telegram để phân tích hiện trường và báo động tự động. 

## 🚀 Tính năng nổi bật

- 🧠 **Trí tuệ Nhân tạo (Vision AI):** Khả năng quan sát và đọc hiểu hình ảnh sắc sảo bằng tiếng Việt thông qua mô hình [Google Gemini 2.5](https://aistudio.google.com/).
- 🚨 **Radar Báo động Chuyển động:** Bắt được sự xuất hiện của bất kỳ động vật/con người nào thông qua thuật toán tính toán ma trận ma sát tĩnh lược (OpenCV `absdiff`).
- 💬 **Điều khiển Kép qua Telegram:** Tích hợp trực tiếp lên điện thoại, yêu cầu chụp hình nhà cửa 24/7 chỉ với 1 dòng chat.
- 🥷 **Chế độ Chạy ngầm (Daemon):** Hoạt động ẩn danh siêu nhẹ trên Windows thông qua `pythonw`, không hiện cửa sổ, không tốn tài nguyên.
- 🛡️ **Tuyệt đối Bảo mật:** Tích hợp bộ khiên `.env` và cơ chế xác minh danh tính mã cứng (Telegram User ID) chặn mọi cuộc tấn công dòm ngó từ người lạ.

## 🛠️ Hướng dẫn cài đặt

### 1. Chuẩn bị
Tải dự án về máy và cài đặt các thư viện nền tảng:
```bash
pip install -r requirements.txt
```

### 2. Thiết lập Biến môi trường
Cực kỳ quan trọng: Để kích hoạt sự liên kết số, bạn cần chuẩn bị khóa để cấp cho AI.
* Đổi tên file `.env.example` thành `.env`
* Lấy mã Telegram Token từ Bot của bạn qua ứng dụng Telegram (tìm **@BotFather**).
* Lấy mã API AI qua **Google AI Studio**.
* Lấy mã ID Cá nhân qua **@userinfobot**.
* Mở file `.env` lên và điền vào các khóa bạn vừa lấy (lưu ý không up file `.env` này lên mạng):

```env
TELEGRAM_BOT_TOKEN="Your_telegram_Token..."
GEMINI_API_KEY="Your_API_KEY..."
ALLOWED_USER_ID="Your_ID"
```

## 🎮 Cách sử dụng & Điều khiển

Bạn không cần mở Terminal đen ngòm để điều khiển!

1. Nháy đúp vào `Chay_Bot_Ngam.vbs` để đưa linh hồn Bot vào trạng thái hoạt động ngầm. (Bạn có thể ném file này vào thư mục `Startup` của Windows để tự động đánh thức Bot khi PC khởi động).
2. Nếu bạn không muốn bị giám sát hoặc muốn nghỉ ngơi, bấm `Tat_Bot.bat` để quét sạch bộ nhớ.

### 🤖 Các câu lệnh tương tác trên ứng dụng Telegram
| Cú pháp / Hành động | Hiệu suất mang lại |
| :--- | :--- |
| *Nhắn bằng văn bản thường* | Chụp ngay một file ảnh hiện trường tức thì, rồi đưa bức ảnh và tin nhắn của bạn cho AI đọc hiểu. |
| `/auto` | **BẬT Lưới dò chuyển động**. Nhạy cảm với mọi sự xê dịch trong phạm vi khung hình. Nếu có đột nhập, tự động chụp hình và gửi báo động. Có thời gian trễ 10s để chống nhiễu (spam). |
| `/stop` | **TẮT Radar**. Giải phóng cổng vật lý của Camera và nhường đường cho thế giới riêng của người dùng. |

---
*Dự án phát triển dựa trên niềm đam mê sáng tạo hệ thống Hệ Điều Hành Tự Động (AI Agents).*
