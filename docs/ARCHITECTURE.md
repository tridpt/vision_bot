# Kiến trúc Vision Bot

Tài liệu này giải thích **dự án hoạt động thế nào ở bên trong**: vai trò từng module, cách
chúng được lắp ráp, mô hình đa luồng, luồng dữ liệu của một cảnh báo, cách lưu trữ và mô
hình bảo mật. Nếu bạn chỉ cần cài đặt và sử dụng, hãy đọc [`README.md`](../README.md).

---

## 1. Tổng quan

Vision Bot là một ứng dụng giám sát **chạy local trên Windows**, gồm 4 mảng chính:

1. **Đầu vào cảm biến** — webcam (OpenCV) và bàn phím/chuột (pynput).
2. **Bộ não phân tích** — Google Gemini phân tích ảnh và lọc "có người hay không".
3. **Kênh điều khiển & thông báo** — Telegram (lệnh + nút bấm) và Dashboard web local.
4. **Lưu trữ** — `settings.json`, lịch sử cảnh báo, ảnh/video, backup JSON, log lỗi.

Toàn bộ chạy trong **một tiến trình Python duy nhất** với nhiều luồng (thread) phối hợp.

```
                 ┌──────────────────────────────────────────────┐
                 │              bot_giam_sat.py                   │
                 │        (Composition Root - lắp ráp)            │
                 └──────────────────────────────────────────────┘
                     │ tạo & "tiêm" Context cho từng thành phần
   ┌─────────────┬───┴───────────┬──────────────┬─────────────────┐
   ▼             ▼               ▼              ▼                 ▼
MotionMonitor  Dashboard     Telegram        Stores           Cloudflared
(camera +      Server        Handlers     (settings/history/   Tunnel
 phím/chuột)   (HTTP+auth)   (lệnh/nút)    backup)             (tùy chọn)
   │             │               │              │
   └─── ask_ai (Gemini) ◄────────┴── camera_tools (OpenCV) ──────┘
```

---

## 2. Composition Root & Dependency Injection

Điểm thiết kế quan trọng nhất: **`bot_giam_sat.py` là "composition root"** — nơi duy nhất
khởi tạo tài nguyên thật (bot Telegram, đường dẫn file, logger, snapshot setting...) và
"tiêm" chúng vào từng module thông qua các **dataclass Context**.

Mỗi module lõi định nghĩa một `*Context` liệt kê đúng những thứ nó cần (hàm, giá trị), ví dụ:

- `MotionMonitorContext` — `bot`, `log_dir`, `get_setting`, `add_alert_history`, `ask_ai`...
- `DashboardContext` — các hàm đọc trạng thái, đổi setting, quản lý backup, `get_dashboard_password`...
- `TelegramHandlerContext` — `bot`, `allowed_user_id`, các callback điều khiển radar/setting...
- `StatusReportContext` — các hàm lấy uptime, kích thước log, trạng thái camera...

**Lợi ích:**
- Module lõi **không phụ thuộc biến global** → dễ test (chỉ cần tạo Context giả).
- Tách bạch rõ ràng giữa "logic" (trong `vision_bot_core/`) và "lắp ráp" (ở root).
- `bot_giam_sat.py` phải nằm ở thư mục gốc để script chạy nền Windows (`Chay_Bot_Ngam.vbs`)
  hoạt động ổn định.

---

## 3. Mô hình đa luồng (threading)

Bot dùng nhiều luồng nền (daemon thread) để các tác vụ không chặn nhau:

| Luồng | Nguồn | Nhiệm vụ |
| --- | --- | --- |
| **Main / polling** | `bot.infinity_polling()` | Nhận lệnh Telegram, chạy mãi |
| **Motion detection** | `MotionMonitor._motion_detection_loop` | Vòng lặp đọc camera, so sánh frame, kích cảnh báo |
| **Input listeners** | pynput `keyboard`/`mouse` Listener | Bắt sự kiện phím/chuột |
| **Input intrusion** | tạo theo từng sự kiện | Xử lý cảnh báo đụng phím/chuột |
| **Dashboard HTTP** | `ThreadingHTTPServer` | Phục vụ web local (mỗi request 1 thread) |
| **Daily summary** | `daily_status_summary_loop` | Gửi tóm tắt trạng thái theo giờ đã đặt |
| **Cloudflared** | `CloudflaredTunnel._run` | Đọc stderr lấy URL tunnel công khai |

**Đồng bộ hóa:** `MotionMonitor` và `settings_store` dùng `threading.Lock` để bảo vệ trạng
thái dùng chung (radar bật/tắt, frame mới nhất, số người xem live, snapshot setting). Frame
camera mới nhất được chia sẻ cho luồng live-stream của dashboard qua `get_latest_frame()`.

---

## 4. Luồng dữ liệu chính

### 4.1. Phát hiện chuyển động → cảnh báo (luồng cốt lõi)

```
Vòng lặp camera (MotionMonitor._motion_detection_loop)
  │  đọc frame qua camera_tools.read_camera_frame
  ▼
So sánh 2 frame (camera_tools.has_large_motion, ngưỡng = motion_area_threshold)
  │  nếu có chuyển động lớn & qua cooldown & không trong giờ yên lặng
  ▼
(tùy chọn) Lọc người: ask_ai(Gemini) → parse_person_filter_result
  │  nếu person_filter_enabled mà không thấy người → bỏ qua
  ▼
Chụp ảnh cảnh báo → lưu logs/alert_*.jpg
  │
  ├─ (tùy chọn) Quay video ngắn → camera_tools.record_alert_video → logs/alert_*.mp4
  │     codec thử lần lượt: avc1 (H.264) → H264 → mp4v (fallback)
  │
  ├─ (tùy chọn) Phân tích Gemini nội dung ảnh
  ▼
add_alert_history(...)  → ghi vào logs/alert_history.json (kèm setting lúc cảnh báo)
  ▼
Gửi ảnh + video + phân tích qua Telegram cho ALLOWED_USER_ID
```

Các yếu tố điều khiển: `motion_area_threshold` (độ nhạy), `alert_cooldown_seconds` (chống
spam), `quiet_hours_*` (giờ yên lặng — vẫn quét nhưng không báo), `send_video`,
`use_gemini_analysis`, `person_filter_enabled`.

### 4.2. Phát hiện đụng phím/chuột

`pynput` lắng nghe phím/chuột. Khi có sự kiện và radar đang bật, `_handle_input_intrusion`
chạy trong thread riêng: chống dội bằng cửa sổ 15 giây, lấy frame camera mới nhất, (tùy chọn)
lọc người, rồi gửi ảnh camera + (tùy chọn) video quay màn hình. Điều khiển bởi
`input_monitoring_enabled`, `send_screen_record`, `send_input_camera_photo`.

### 4.3. Chụp ảnh theo yêu cầu

Khi người dùng nhắn text bất kỳ hoặc bấm "📸 Chụp ngay": bot tạm dừng radar (để nhả camera),
chụp 1 frame, gửi cho Gemini kèm câu hỏi của người dùng, trả ảnh + câu trả lời, rồi bật lại
radar nếu trước đó đang bật (`run_camera_action_with_radar_paused`).

### 4.4. Tóm tắt hằng ngày

`daily_status_summary_loop` kiểm tra mỗi 30 giây; đúng giờ:phút đã đặt
(`daily_summary_hour/minute`) thì gửi `build_status_message()` một lần trong ngày.

---

## 5. Các module lõi (`vision_bot_core/`)

| Module | Vai trò |
| --- | --- |
| `motion_monitor.py` | Trái tim giám sát: vòng lặp camera, listener phím/chuột, pipeline cảnh báo, xử lý lỗi camera, cung cấp frame cho live-stream |
| `camera_tools.py` | Đọc/quét/cấu hình camera (OpenCV), lưu frame, ghi video cảnh báo với fallback codec |
| `gemini_analyzer.py` | Bọc Google Gemini: `ask_ai(image, question)`, cấu hình API key |
| `settings_store.py` | Kho setting thread-safe, chuẩn hóa & kẹp giá trị (clamp), lưu `settings.json` |
| `alert_history_store.py` | Quản lý lịch sử cảnh báo + media, kiểm tra đường dẫn an toàn, cắt/khôi phục lịch sử |
| `backup_store.py` | Tạo/đọc backup JSON của setting & lịch sử trước mỗi thay đổi |
| `dashboard_server.py` | HTTP server local: xác thực, các tab, phục vụ media, live-stream, quản lý setting/backup |
| `status_report.py` | Tổng hợp & định dạng thông điệp trạng thái, lịch tóm tắt/giờ yên lặng |
| `telegram_handlers.py` | Đăng ký toàn bộ handler lệnh/nút Telegram |
| `telegram_ui.py` | Định dạng nội dung tin nhắn (lịch sử, snapshot setting) |
| `cloudflared_tunnel.py` | (Tùy chọn) tạo tunnel công khai để xem dashboard từ xa |

---

## 6. Lưu trữ & dữ liệu

- **`settings.json`** — setting lâu dài. `settings_store` luôn chuẩn hóa (clamp số, ép kiểu
  bool, snap về các lựa chọn hợp lệ) khi đọc/ghi, ghi bằng file tạm rồi `os.replace` (atomic).
- **`logs/alert_history.json`** — danh sách cảnh báo, mỗi mục gồm thời gian, đường dẫn ảnh/video,
  phân tích Gemini, và snapshot setting lúc đó. Khi vượt `alert_history_limit`, record cũ và
  media tương ứng bị xóa.
- **`logs/alert_*.jpg`, `alert_*.mp4`** — ảnh/video cảnh báo.
- **`logs/backups/`** — backup JSON nhẹ của setting và lịch sử, tạo tự động **trước** mỗi thao
  tác thay đổi (đổi setting, cắt/dọn lịch sử, khôi phục). Không copy lại media.
- **`logs/bot_errors.log`** — log lỗi nội bộ qua `RotatingFileHandler` (xoay vòng 1MB × 3).

Đường dẫn media trong lịch sử được lưu **tương đối** so với thư mục dự án và luôn kiểm tra
an toàn (`is_safe_alert_media_path`) trước khi phục vụ qua dashboard, tránh path traversal.

---

## 7. Dashboard & bảo mật

`dashboard_server.py` chạy `ThreadingHTTPServer` bind `127.0.0.1`. Các tab: Trạng thái, Lịch
sử, Setting, Backup, Log lỗi; cộng các endpoint `/media`, `/live-stream`,
`/download-backup`, `/download-history-zip`, `/scan-cameras`, `/test-camera`.

**Mô hình xác thực:**
- Nếu `dashboard_password` rỗng → không yêu cầu đăng nhập (chỉ an toàn khi không bật tunnel).
- Nếu có mật khẩu → mọi request phải qua `check_auth`:
  - Trang `/login` luôn truy cập được.
  - Đăng nhập đúng mật khẩu (`POST /login`) → set cookie `session=<token>` với cờ
    `HttpOnly; SameSite=Lax`.
  - **`token` là chuỗi ngẫu nhiên sinh mới mỗi tiến trình** (`secrets.token_urlsafe`), so sánh
    bằng `hmac.compare_digest` (chống timing attack). Đây là lý do restart bot sẽ buộc đăng
    nhập lại, và là lý do **không thể** bypass bằng cookie đoán được như trước đây.
  - Các endpoint tải file/stream trả `401` nếu chưa xác thực; trang khác bị chuyển về `/login`.
- Mật khẩu được seed từ biến môi trường `DASHBOARD_PASSWORD` (trong `.env`) khi setting còn
  rỗng; mật khẩu đặt qua dashboard/Telegram (lưu `settings.json`) được ưu tiên.

**Cloudflared tunnel:** nếu có `bin/cloudflared.exe`, bot tạo URL công khai
`https://...trycloudflare.com` để xem dashboard từ xa. Vì điều này phơi dashboard ra Internet,
**đặt mật khẩu mạnh là bắt buộc** khi dùng tunnel.

---

## 8. Vòng đời khởi động / tắt

1. **Single instance** — tạo mutex Windows; nếu đã có bot chạy thì thoát ngay.
2. Nạp `.env`, cấu hình `settings_store`, seed `dashboard_password`, cấu hình Gemini & logger.
3. Khởi tạo `MotionMonitor`, đăng ký lệnh Telegram, khởi động luồng tóm tắt hằng ngày.
4. Trong `__main__`: kiểm tra token, bật cloudflared, khởi động dashboard, gửi thông báo online,
   rồi vào `bot.infinity_polling()`.
5. **Restart** (`schedule_bot_restart`) — chạy `Chay_Bot_Ngam.vbs` qua PowerShell rồi thoát
   tiến trình cũ để VBScript nhận diện và bật lại.

---

## 9. Kiểm thử & chất lượng

- **Unit test** trong `tests/` (chạy: `python -m unittest discover -s tests`). Bao gồm test
  store (settings/history/backup), camera tools, motion monitor, status report, telegram
  handlers/UI, dashboard (render + **xác thực ở mức HTTP thật**), và cloudflared tunnel.
- **Lint:** `ruff check .` (cấu hình ở `ruff.toml`, bỏ qua E701 cho guard-clause một dòng).
- **CI:** GitHub Actions tự chạy lint + test + compile sau mỗi push.

---

## 10. Mở rộng dự án

**Thêm một setting mới:**
1. Khai báo mặc định trong `DEFAULT_SETTINGS` (và `SETTING_LIMITS`/`SETTING_CHOICES`/
   `SETTING_LABELS`/`SETTING_UNITS` nếu cần) ở `settings_store.py`.
2. Dùng `get_setting("ten_setting")` ở nơi cần.
3. Thêm điều khiển vào form dashboard (`render_dashboard_settings_form`) và/hoặc lệnh Telegram.

**Thêm một lệnh Telegram mới:** đăng ký trong `register_telegram_handlers`, dùng các callback
có sẵn trong `TelegramHandlerContext`; nếu cần khả năng mới, thêm trường vào Context và "tiêm"
từ `bot_giam_sat.py`.

**Thêm cảm biến/đầu vào mới:** mô phỏng theo cách `MotionMonitor` quản lý vòng lặp + lock, và
tái dùng pipeline `make_alert_id → lưu media → add_alert_history → gửi Telegram`.
