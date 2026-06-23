# Tham chiếu module nội bộ

Tài liệu này liệt kê các hàm/lớp **công khai** của từng module trong `vision_bot_core/`,
kèm mô tả ngắn gọn. Dùng để tra cứu nhanh khi đọc hoặc mở rộng code. Để hiểu bức tranh tổng
thể và luồng dữ liệu, xem [`ARCHITECTURE.md`](ARCHITECTURE.md).

> Quy ước: nhiều module dùng mẫu **"configure trước, dùng sau"** — gọi `configure_*` một lần
> ở `bot_giam_sat.py` để nạp tài nguyên (đường dẫn, API key, logger), sau đó các hàm khác mới
> hoạt động. Các store dùng `threading.Lock` nên an toàn khi gọi từ nhiều luồng.

---

## settings_store.py

Kho setting thread-safe, lưu `settings.json`. Mọi giá trị đều được **chuẩn hóa** (clamp số,
ép bool, snap về lựa chọn hợp lệ) khi đọc/ghi.

| Hàm / Hằng | Mô tả |
| --- | --- |
| `configure_settings_store(settings_path)` | Trỏ tới file và nạp setting lần đầu |
| `get_setting(name)` | Lấy một giá trị setting |
| `get_settings_snapshot()` | Lấy bản sao toàn bộ setting (an toàn để đọc rời) |
| `update_setting(name, value)` | Đặt + chuẩn hóa + lưu xuống đĩa |
| `restore_settings_from_file(path)` | Khôi phục setting từ file backup |
| `clamp_int(value, default, min, max)` | Ép số nguyên về khoảng hợp lệ |
| `normalize_bool / snap_to_choice / normalize_settings` | Tiện ích chuẩn hóa |
| `DEFAULT_SETTINGS`, `SETTING_LIMITS`, `SETTING_CHOICES`, `SETTING_LABELS`, `SETTING_UNITS`, `HISTORY_LIMIT_CHOICES` | Bảng định nghĩa setting |

**Lưu ý logic:** không được tắt đồng thời `motion_detection_enabled` và
`input_monitoring_enabled` — nếu cả hai tắt, hệ thống tự bật lại giám sát camera.

---

## alert_history_store.py

Quản lý lịch sử cảnh báo và media kèm theo. Có kiểm tra đường dẫn an toàn để tránh path
traversal khi phục vụ/xóa file.

| Hàm | Mô tả |
| --- | --- |
| `configure_alert_history_store(base_dir, log_dir, alert_history_file, get_history_limit, log_error)` | Cấu hình ban đầu |
| `make_alert_id(timestamp)` | Sinh ID cảnh báo dạng `YYYYMMDD_HHMMSS_mmm` |
| `add_alert_history(entry)` | Thêm cảnh báo mới (chèn đầu), tự cắt theo giới hạn + xóa media cũ |
| `get_recent_alert_history(limit)` / `get_alert_history_snapshot(limit=None)` | Lấy danh sách cảnh báo |
| `get_alert_history_count()` | Đếm số cảnh báo |
| `delete_alert_history_entry(alert_id)` | Xóa một cảnh báo + media của nó |
| `trim_alert_history(limit)` | Cắt lịch sử về `limit`, xóa media dư |
| `clear_alert_history_files()` | Xóa toàn bộ cảnh báo + media (có kiểm tra đường dẫn `logs`) |
| `restore_alert_history(history)` / `restore_alert_history_from_file(path, limit)` | Khôi phục lịch sử |
| `load_alert_history_from_file(path, limit=None)` | Đọc lịch sử từ file bất kỳ |
| `is_safe_alert_media_path(path)` | Kiểm tra path nằm trong `logs/` và tên bắt đầu `alert_` |
| `relative_to_base(path)` / `absolute_from_base(path)` | Chuyển đổi đường dẫn tương đối ⇄ tuyệt đối |
| `ensure_log_dir()` | Tạo thư mục log nếu chưa có |
| `text_preview(text, max_length=140)` | Rút gọn văn bản phân tích |

---

## backup_store.py

Tạo và liệt kê backup JSON nhẹ của setting & lịch sử. Tên file mã hóa nhãn + lý do + thời gian.

| Hàm | Mô tả |
| --- | --- |
| `backup_json_files(file_specs, backup_dir, reason, max_backups=30, log_error=None)` | Backup nhiều file + tự dọn bớt |
| `backup_json_file(source_path, backup_dir, label, reason, log_error)` | Backup một file |
| `prune_backups(backup_dir, max_backups, log_error)` | Xóa backup cũ vượt giới hạn |
| `list_backups(backup_dir, limit=5, log_error, label=None)` | Liệt kê backup (mới nhất trước) |
| `get_latest_backup(backup_dir, label=None, log_error)` | Lấy backup gần nhất |
| `parse_backup_filename(filename)` | Tách nhãn/lý do/thời gian từ tên file |

---

## camera_tools.py

Tiện ích camera (OpenCV) thuần, không giữ trạng thái.

| Hàm | Mô tả |
| --- | --- |
| `read_camera_frame(warmup_seconds, camera_config)` | Đọc một frame (có warmup) |
| `scan_camera_indices(indices, camera_config)` | Quét các index camera khả dụng |
| `save_frame(path, img)` | Lưu frame ra ảnh |
| `has_large_motion(prev_gray, cur_gray, area_threshold)` | So sánh 2 frame, phát hiện chuyển động lớn |
| `create_alert_video_writer(video_path, fps, frame_size)` | Tạo `VideoWriter`, thử codec `avc1→H264→mp4v` |
| `record_alert_video(stream, first_frame, path, duration, fps, camera_config)` | Quay video cảnh báo ngắn |
| `normalize_camera_config / camera_config_with_index` | Chuẩn hóa cấu hình camera |
| `format_camera_config / format_camera_scan_results` | Định dạng thông tin camera cho hiển thị |

---

## gemini_analyzer.py

Bọc Google Gemini.

| Hàm | Mô tả |
| --- | --- |
| `configure_gemini_analyzer(api_key)` | Khởi tạo client Gemini |
| `ask_ai(image_path, user_question)` | Gửi ảnh + câu hỏi tới `gemini-2.5-flash`, trả văn bản |

---

## status_report.py

Tổng hợp & định dạng trạng thái; tính lịch tóm tắt và giờ yên lặng.

| Hàm | Mô tả |
| --- | --- |
| `StatusReportContext` | Dataclass gom các phụ thuộc để dựng báo cáo |
| `format_status_message(ctx)` | Dựng thông điệp trạng thái đầy đủ (Telegram/dashboard) |
| `get_daily_summary_schedule(snapshot)` / `format_daily_summary_schedule(snapshot)` | Lịch tóm tắt hằng ngày |
| `get_quiet_hours_schedule(snapshot)` / `format_quiet_hours_schedule(snapshot)` | Lịch giờ yên lặng |
| `is_within_quiet_hours(snapshot, now_hour=None)` | Có đang trong giờ yên lặng không (hỗ trợ vắt nửa đêm) |
| `format_duration(seconds)` / `format_size(num_bytes)` | Định dạng thời lượng / dung lượng |
| `get_directory_size(path, log_error=None)` | Tính tổng dung lượng thư mục |

---

## motion_monitor.py

Lớp giám sát trung tâm (camera + phím/chuột). Là module có trạng thái, dùng lock nội bộ.

| Thành phần | Mô tả |
| --- | --- |
| `MotionMonitorContext` | Dataclass phụ thuộc (`bot`, `log_dir`, `get_setting`, `add_alert_history`, `ask_ai`, ...) |
| `MotionMonitor.start()` | Khởi động vòng lặp phát hiện chuyển động |
| `set_radar_state(active, chat_id=None)` / `is_radar_active()` | Bật/tắt & đọc trạng thái radar |
| `get_camera_status_for_report()` / `get_camera_status_for_dashboard()` | Trạng thái camera cho báo cáo/dashboard |
| `get_last_alert_timestamp()` / `get_monitoring_chat_id()` | Thông tin cảnh báo gần nhất / chat đang giám sát |
| `add_live_viewer()` / `remove_live_viewer()` / `get_latest_frame()` | Hỗ trợ live-stream dashboard |
| `parse_person_filter_result(text)` | Phân tích kết quả lọc người từ Gemini (hàm module-level) |

Các phương thức `_`-prefix (vòng lặp, listener phím/chuột, xử lý lỗi camera) là nội bộ.

---

## dashboard_server.py

HTTP server local với xác thực. Phần lớn là hàm render HTML thuần (dễ test) + lớp handler.

| Thành phần | Mô tả |
| --- | --- |
| `DashboardContext` | Dataclass gom mọi phụ thuộc dashboard cần (gồm `get_dashboard_password`) |
| `start_dashboard_server(ctx)` | Khởi động `ThreadingHTTPServer` trên thread nền |
| `make_dashboard_handler(ctx)` | Tạo lớp handler; **sinh `session_token` ngẫu nhiên cho mỗi tiến trình** |
| `render_dashboard_html(...)` | Dựng HTML cho các tab (status/history/settings/backups/errors) |
| `render_login_page(error_message="")` | Trang đăng nhập |
| `update_dashboard_settings(ctx, form)` | Áp dụng setting từ form web |
| `build_dashboard_history_zip(ctx)` / `get_dashboard_history_export_files(ctx)` | Đóng gói lịch sử thành `.zip` |
| `restore_selected_dashboard_backup / delete_selected_dashboard_backup` | Khôi phục/xóa backup đã chọn |
| `normalize_dashboard_tab / *_filter / *_page` | Chuẩn hóa tham số truy vấn |

**Xác thực (trong handler):** `check_auth()` cho qua khi không đặt mật khẩu; ngược lại yêu
cầu cookie `session` khớp `session_token` (so sánh bằng `hmac.compare_digest`). Đăng nhập đúng
mật khẩu mới được cấp cookie. Chi tiết mô hình bảo mật ở [`ARCHITECTURE.md`](ARCHITECTURE.md#7-dashboard--bảo-mật).

---

## telegram_handlers.py & telegram_ui.py

| Thành phần | Mô tả |
| --- | --- |
| `TelegramHandlerContext` | Dataclass phụ thuộc cho handler (bot, `allowed_user_id`, các callback điều khiển) |
| `register_telegram_handlers(ctx)` | Đăng ký toàn bộ handler lệnh/nút Telegram |
| `telegram_ui.format_alert_history_message(entries, format_timestamp)` | Định dạng tóm tắt lịch sử |
| `telegram_ui.format_settings_snapshot(snapshot)` | Định dạng snapshot setting |

Mọi handler đều kiểm tra người gửi qua `allowed_user_id` trước khi xử lý (chặn người lạ).

---

## cloudflared_tunnel.py

| Thành phần | Mô tả |
| --- | --- |
| `CloudflaredTunnel(port, logger=None)` | Quản lý tiến trình `cloudflared` |
| `.start()` / `.stop()` / `.get_url()` | Bật/tắt tunnel & lấy URL công khai |
| `.download_if_needed()` | Tải `cloudflared.exe` nếu chưa có |
| `extract_trycloudflare_url(text)` | Trích URL `*.trycloudflare.com` từ log (hàm module-level, có test) |
