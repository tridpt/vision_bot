# Vision Bot

Vision Bot là bot giám sát webcam chạy local trên Windows. Bot điều khiển qua Telegram, có thể chụp ảnh theo yêu cầu, bật radar phát hiện chuyển động, gửi ảnh/video cảnh báo, lưu lịch sử và có dashboard local để xem trạng thái.

## Tính năng chính

- Điều khiển bot qua Telegram bằng lệnh hoặc nút trong `/menu`.
- Chụp ảnh webcam và phân tích bằng Gemini.
- Radar phát hiện chuyển động bằng OpenCV.
- Khi có cảnh báo, bot gửi ảnh và có thể gửi video ngắn 5-10 giây.
- Lưu lịch sử cảnh báo gồm ảnh, video, thời gian, phân tích Gemini và setting lúc cảnh báo.
- Tự xóa media cũ khi lịch sử vượt giới hạn đã chọn.
- Dashboard local tại `http://127.0.0.1:8765`.
- Chỉnh setting lâu dài qua Telegram hoặc dashboard, lưu vào `settings.json`.
- Ghi lỗi nội bộ vào `logs/bot_errors.log`.
- Chống chạy trùng bot bằng mutex và script chạy nền.

## Cấu trúc thư mục

```text
vision_bot/
├─ bot_giam_sat.py              # File chạy chính của bot
├─ Chay_Bot_Ngam.vbs            # Chạy bot nền bằng pythonw
├─ Tat_Bot.bat                  # Tắt process bot đang chạy
├─ requirements.txt             # Thư viện Python cần cài
├─ settings.json                # Setting đang lưu lâu dài
├─ logs/                        # Ảnh, video, history và error log
├─ vision_bot_core/             # Code chính đã tách module
│  ├─ dashboard_server.py
│  ├─ settings_store.py
│  ├─ alert_history_store.py
│  ├─ backup_store.py
│  ├─ camera_tools.py
│  ├─ gemini_analyzer.py
│  ├─ motion_monitor.py
│  ├─ status_report.py
│  ├─ telegram_handlers.py
│  └─ telegram_ui.py
└─ tools/                       # Script thử nghiệm độc lập
   ├─ chup_anh.py
   └─ nhan_dien.py
```

## Cài đặt

Yêu cầu:

- Python 3.8 trở lên
- Webcam hoạt động được trên máy
- Telegram Bot Token
- Gemini API Key

Cài thư viện:

```powershell
pip install -r requirements.txt
```

Tạo file `.env` từ `.env.example`:

```env
TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN_HERE"
GEMINI_API_KEY="YOUR_GEMINI_API_KEY_HERE"
ALLOWED_USER_ID="YOUR_TELEGRAM_ID_HERE"
```

Ghi chú:

- `TELEGRAM_BOT_TOKEN`: lấy từ BotFather.
- `GEMINI_API_KEY`: lấy từ Google AI Studio.
- `ALLOWED_USER_ID`: Telegram user id của bạn, có thể lấy bằng bot `@userinfobot`.
- Có thể thêm `DASHBOARD_PORT=8765` nếu muốn đổi port dashboard.
- Có thể thêm `BACKUP_MAX_FILES=30` nếu muốn đổi số file backup JSON được giữ lại.

## Cách chạy

Chạy foreground để xem log trên terminal:

```powershell
python bot_giam_sat.py
```

Chạy nền trên Windows:

```text
Double click Chay_Bot_Ngam.vbs
```

Tắt bot:

```text
Double click Tat_Bot.bat
```

Dashboard local:

```text
http://127.0.0.1:8765
```

Dashboard chỉ mở trên máy đang chạy bot. Nếu dùng điện thoại không cùng máy, hãy điều khiển bằng Telegram.

## Lệnh Telegram

| Lệnh | Chức năng |
| --- | --- |
| `/start` hoặc `/help` | Xem hướng dẫn nhanh |
| `/menu` | Mở menu nút bấm |
| `/auto` | Bật radar phát hiện chuyển động |
| `/stop` | Tắt radar và nhả camera |
| `/status` | Xem trạng thái bot, radar, camera, uptime, logs, setting |
| `/history` | Gửi lịch sử cảnh báo gần nhất |
| `/settings` | Mở menu chỉnh setting |
| `/set_sensitivity <số>` | Chỉnh độ nhạy chuyển động |
| `/set_cooldown <giây>` | Chỉnh thời gian nghỉ giữa các cảnh báo |
| `/set_video_seconds <giây>` | Chỉnh độ dài video cảnh báo |
| `/set_video_fps <fps>` | Chỉnh FPS video cảnh báo |
| `/video_on` / `/video_off` | Bật hoặc tắt gửi video |
| `/ai_on` / `/ai_off` | Bật hoặc tắt phân tích Gemini khi cảnh báo |
| Nhắn text bất kỳ | Bot chụp ảnh webcam và phân tích theo nội dung bạn hỏi |

## Menu Telegram

Trong `/menu` có các nút chính:

- `📸 Chụp ngay`: chụp webcam và gửi ảnh/phân tích.
- `Bật/Tắt Radar`: điều khiển chế độ phát hiện chuyển động.
- `Trạng thái`: xem trạng thái chi tiết.
- `Lịch sử`: gửi cảnh báo gần nhất.
- `Xem log lỗi`: đọc các dòng lỗi mới nhất từ `logs/bot_errors.log`.
- `Cài đặt`: chỉnh setting bằng nút hoặc nhập số trong chat.
- `Restart bot`: restart process bot.
- `Dọn lịch sử`: xóa ảnh/video cảnh báo và `alert_history.json`.

## Setting

Setting được lưu vào `settings.json`, nên vẫn còn sau khi restart bot.

| Setting | Ý nghĩa | Giá trị |
| --- | --- | --- |
| `motion_area_threshold` | Độ nhạy chuyển động, số nhỏ nhạy hơn | `500-50000` |
| `alert_cooldown_seconds` | Thời gian nghỉ giữa 2 cảnh báo | `3-3600` giây |
| `alert_video_seconds` | Độ dài video cảnh báo | `5-10` giây |
| `alert_video_fps` | FPS video cảnh báo | `5-30` |
| `send_video` | Có gửi video khi cảnh báo không | Bật/Tắt |
| `use_gemini_analysis` | Có phân tích Gemini khi cảnh báo không | Bật/Tắt |
| `alert_history_limit` | Số cảnh báo giữ trong lịch sử | `10`, `50`, `100` |

Có thể chỉnh setting ở cả Telegram và dashboard. Cả hai đều lưu lâu dài vào `settings.json`.

## Dashboard Local

Dashboard có các tab:

- `Trạng thái`: radar, camera, uptime, logs size, setting hiện tại.
- `Lịch sử`: xem ảnh/video cảnh báo, lọc hôm nay/có video/không video/mới nhất, xóa từng cảnh báo.
- `Setting`: chỉnh setting trực tiếp trên web.
- `Log lỗi`: xem lỗi nội bộ gần nhất.

Dashboard không dùng mật khẩu trong phiên bản hiện tại. Vì dashboard chỉ bind `127.0.0.1`, nó chỉ mở trên chính máy chạy bot.

## Lịch sử và logs

Thư mục `logs/` chứa:

- `alert_history.json`: danh sách cảnh báo.
- `alert_*.jpg`: ảnh cảnh báo.
- `alert_*.mp4`: video cảnh báo.
- `bot_errors.log`: lỗi nội bộ của bot.
- `backups/`: backup nhỏ của `settings.json` và `alert_history.json`.

Khi lịch sử vượt giới hạn setting, bot sẽ xóa record cũ và xóa luôn ảnh/video tương ứng. Nếu muốn dọn toàn bộ, dùng nút `Dọn lịch sử` trong Telegram hoặc dashboard.

Trước khi đổi setting, cắt lịch sử hoặc dọn toàn bộ lịch sử, bot tự lưu backup JSON vào `logs/backups/`. Backup này chỉ lưu file cấu hình/lịch sử để nhẹ ổ cứng, không copy lại ảnh/video cảnh báo.

Khôi phục thủ công: tắt bot, copy file `settings_*.json` cần khôi phục thành `settings.json` hoặc copy file `alert_history_*.json` thành `logs/alert_history.json`, rồi chạy lại bot.

## Xử lý lỗi thường gặp

Camera không đọc được frame:

- Đóng Zoom, Meet, Camera app hoặc phần mềm khác đang chiếm webcam.
- Tắt radar rồi bật lại.
- Restart bot bằng menu Telegram hoặc chạy lại `Chay_Bot_Ngam.vbs`.

Không xem được dashboard trên điện thoại:

- `127.0.0.1` là địa chỉ máy đang chạy bot, điện thoại không mở được nếu không cùng máy.
- Nên dùng Telegram để điều khiển từ điện thoại.

Không nhận cảnh báo:

- Kiểm tra `/status`.
- Kiểm tra radar đang `BẬT`.
- Kiểm tra `ALLOWED_USER_ID` đúng Telegram ID của bạn.
- Xem `Xem log lỗi` trong menu.

## Ghi chú phát triển

Chạy unit test:

```powershell
python -m unittest discover -s tests
```

Kiểm tra compile nhanh:

```powershell
$files = rg --files -g "*.py"
python -m py_compile @files
```

GitHub Actions cũng tự chạy unit test và compile sau mỗi lần push. Xem kết quả ở tab `Actions` của repo trên GitHub hoặc dấu trạng thái cạnh commit.

Các module chính nên đặt trong `vision_bot_core/`. Giữ `bot_giam_sat.py` ở root để script chạy nền Windows vẫn hoạt động ổn định.
