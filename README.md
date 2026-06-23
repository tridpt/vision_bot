# Vision Bot

[![CI](https://github.com/YOUR_USERNAME/vision_bot/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/vision_bot/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

Vision Bot là bot giám sát webcam chạy local trên Windows. Bot điều khiển qua Telegram, có thể chụp ảnh theo yêu cầu, bật radar phát hiện chuyển động, gửi ảnh/video cảnh báo, lưu lịch sử và có dashboard local để xem trạng thái.

## Tính năng chính

- Điều khiển bot qua Telegram bằng lệnh hoặc nút trong `/menu`.
- Chụp ảnh webcam và phân tích bằng Gemini.
- Radar phát hiện chuyển động bằng OpenCV.
- Giờ yên lặng: trong khung giờ chọn, radar vẫn quét nhưng bot không gửi cảnh báo (hỗ trợ khung vắt qua nửa đêm).
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

## Cài đặt (Hướng dẫn chi tiết cho người mới)

Nếu bạn là người hoàn toàn mới, hãy làm theo từng bước sau:

### Bước 1: Cài đặt phần mềm cơ bản
1. Cài đặt **Python** (phiên bản 3.8 trở lên) từ [python.org](https://www.python.org/downloads/). **Quan trọng:** Khi cài đặt, nhớ tích vào ô **"Add Python to PATH"**.
2. Tải mã nguồn Bot về máy (chọn `Code` -> `Download ZIP` rồi giải nén).

### Bước 2: Lấy các mã cấu hình bí mật (API Keys)
Bot cần 3 mã bí mật để hoạt động. Hãy lấy và lưu ra Notepad:
1. **Telegram Bot Token:**
   - Mở Telegram, tìm kiếm `@BotFather`.
   - Nhắn `/newbot`, đặt tên cho Bot của bạn.
   - BotFather sẽ cấp cho bạn một chuỗi dài (vd: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`). Đây là Token.
2. **Telegram User ID:**
   - Mở Telegram, tìm kiếm `@userinfobot` và nhấn Start.
   - Nó sẽ trả về ID của bạn (một dãy số, vd: `123456789`). ID này giúp Bot chỉ nhận lệnh từ bạn, chặn người lạ.
3. **Gemini API Key (Bộ não AI):**
   - Truy cập [Google AI Studio](https://aistudio.google.com/).
   - Đăng nhập bằng tài khoản Google, nhấn **"Get API key"** -> **"Create API key"** để lấy mã.

### Bước 3: Cấu hình Bot
1. Mở thư mục Vision Bot bạn vừa giải nén.
2. Đổi tên file `.env.example` thành `.env` (xóa chữ `.example`).
3. Mở file `.env` bằng Notepad và điền 3 mã bạn vừa lấy vào:
   ```env
   TELEGRAM_BOT_TOKEN="Điền_Token_Vào_Đây"
   GEMINI_API_KEY="Điền_Gemini_Key_Vào_Đây"
   ALLOWED_USER_ID="Điền_User_ID_Vào_Đây"
   DASHBOARD_PASSWORD="Tao_Mot_Mat_Khau_Cho_Dashboard_Tuy_Y"
   ```

### Bước 4: Cài đặt thư viện và Cloudflared
1. Mở thư mục chứa Bot. Nhấn chuột phải vào vùng trống -> chọn **Open in Terminal** (hoặc Open PowerShell window here).
2. Gõ lệnh sau để cài thư viện:
   ```powershell
   pip install -r requirements.txt
   ```
3. Tạo thư mục `bin` bên trong thư mục `vision_bot`. Tải file `cloudflared-windows-amd64.exe` từ [Cloudflare](https://github.com/cloudflare/cloudflared/releases) và đổi tên thành `cloudflared.exe`, bỏ vào thư mục `bin`. (Đây là phần mềm giúp bạn xem Dashboard từ xa mà không cần mở Port modem).

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
| `/quiet_hours_on` / `/quiet_hours_off` | Bật hoặc tắt giờ yên lặng |
| `/set_quiet_start <giờ>` | Chỉnh giờ bắt đầu yên lặng (0-23) |
| `/set_quiet_end <giờ>` | Chỉnh giờ kết thúc yên lặng (0-23) |
| Nhắn text bất kỳ | Bot chụp ảnh webcam và phân tích theo nội dung bạn hỏi |

## Menu Telegram

Trong `/menu` có các nút chính:

- `📸 Chụp ngay`: chụp webcam và gửi ảnh/phân tích.
- `Bật/Tắt Radar`: điều khiển chế độ phát hiện chuyển động.
- `Trạng thái`: xem trạng thái chi tiết.
- `Lịch sử`: gửi cảnh báo gần nhất.
- `Xem log lỗi`: đọc các dòng lỗi mới nhất từ `logs/bot_errors.log`.
- `Cài đặt`: chỉnh setting bằng nút hoặc nhập số trong chat.
- `Xem backup`: liệt kê vài backup JSON gần nhất.
- `Khôi phục setting`: khôi phục `settings.json` từ backup setting gần nhất.
- `Khôi phục lịch sử`: khôi phục `alert_history.json` từ backup lịch sử gần nhất.
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
| `quiet_hours_enabled` | Bật giờ yên lặng (radar quét nhưng không báo động) | Bật/Tắt |
| `quiet_hours_start_hour` | Giờ bắt đầu yên lặng | `0-23` |
| `quiet_hours_end_hour` | Giờ kết thúc yên lặng | `0-23` |
| `alert_history_limit` | Số cảnh báo giữ trong lịch sử | `10`, `50`, `100` |

Có thể chỉnh setting ở cả Telegram và dashboard. Cả hai đều lưu lâu dài vào `settings.json`.

## Dashboard Local

Dashboard có các tab:

- `Trạng thái`: radar, camera, uptime, logs size, setting hiện tại.
- `Lịch sử`: xem ảnh/video cảnh báo theo từng trang 10 cảnh báo, lọc hôm nay/có video/không video/mới nhất, xóa từng cảnh báo, tải toàn bộ lịch sử thành file `.zip`.
- `Setting`: chỉnh setting trực tiếp trên web.
- `Backup`: lọc backup theo loại, xem/tải nội dung từng backup, khôi phục hoặc xóa một backup cụ thể.
- `Log lỗi`: xem lỗi nội bộ gần nhất.

Dashboard yêu cầu đăng nhập bằng `DASHBOARD_PASSWORD`. Khi bật cloudflared tunnel, dashboard sẽ có thêm một URL công khai `https://...trycloudflare.com`, nên việc đặt mật khẩu mạnh là bắt buộc để tránh người lạ xem được camera. Phiên đăng nhập dùng token ngẫu nhiên sinh mới mỗi lần bot khởi động, nên restart bot sẽ buộc đăng nhập lại. Nếu để trống `DASHBOARD_PASSWORD`, dashboard sẽ không yêu cầu mật khẩu (chỉ nên dùng khi không bật tunnel và chỉ truy cập local).

## Lịch sử và logs

Thư mục `logs/` chứa:

- `alert_history.json`: danh sách cảnh báo.
- `alert_*.jpg`: ảnh cảnh báo.
- `alert_*.mp4`: video cảnh báo.
- `bot_errors.log`: lỗi nội bộ của bot.
- `backups/`: backup nhỏ của `settings.json` và `alert_history.json`.

Khi lịch sử vượt giới hạn setting, bot sẽ xóa record cũ và xóa luôn ảnh/video tương ứng. Nếu muốn dọn toàn bộ, dùng nút `Dọn lịch sử` trong Telegram hoặc dashboard.

Có thể tải nhanh `alert_history.json`, ảnh/video cảnh báo và `bot_errors.log` còn trong `logs/` bằng nút `Tải lịch sử .zip` ở tab `Lịch sử` của dashboard.

Trước khi đổi setting, cắt lịch sử, dọn toàn bộ lịch sử hoặc khôi phục setting, bot tự lưu backup JSON vào `logs/backups/`. Backup này chỉ lưu file cấu hình/lịch sử để nhẹ ổ cứng, không copy lại ảnh/video cảnh báo.

Khôi phục nhanh: vào Telegram `/menu` > `Khôi phục setting` để lấy backup `settings_*.json` gần nhất, hoặc `Khôi phục lịch sử` để lấy backup `alert_history_*.json` gần nhất. Backup lịch sử chỉ chứa danh sách cảnh báo, không chứa lại ảnh/video nếu file media đã bị xóa khỏi `logs/`.

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

Soát lint bằng Ruff:

```powershell
ruff check .
```

Cấu hình lint nằm trong `ruff.toml`. Quy tắc E701 được bỏ qua vì các handler dùng style guard-clause một dòng (`if not verify_user(message): return`) một cách nhất quán.

Kiểm tra compile nhanh:

```powershell
$files = rg --files -g "*.py"
python -m py_compile @files
```

GitHub Actions cũng tự chạy lint, unit test và compile sau mỗi lần push. Xem kết quả ở tab `Actions` của repo trên GitHub hoặc dấu trạng thái cạnh commit.

Các module chính nên đặt trong `vision_bot_core/`. Giữ `bot_giam_sat.py` ở root để script chạy nền Windows vẫn hoạt động ổn định.
