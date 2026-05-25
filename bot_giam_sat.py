import telebot
import cv2
import html
import sys
import os
import json
import logging
import mimetypes
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from PIL import Image
from urllib.parse import parse_qs, quote, urlencode, urlparse
from google import genai
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
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = env_int("DASHBOARD_PORT", 8765)
DASHBOARD_URL = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"
HISTORY_PREVIEW_LIMIT = 3
HISTORY_LIMIT_CHOICES = (10, 50, 100)
DEFAULT_SETTINGS = {
    "motion_area_threshold": 8000,
    "alert_cooldown_seconds": 10,
    "alert_video_seconds": 7,
    "alert_video_fps": 10,
    "send_video": True,
    "use_gemini_analysis": True,
    "alert_history_limit": 50
}

SETTING_LIMITS = {
    "motion_area_threshold": (500, 50000),
    "alert_cooldown_seconds": (3, 3600),
    "alert_video_seconds": (5, 10),
    "alert_video_fps": (5, 30),
    "alert_history_limit": (10, 100)
}

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
client = genai.Client(api_key=GEMINI_API_KEY)

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
settings_lock = threading.Lock()
pending_setting_inputs = {}
pending_setting_lock = threading.Lock()
history_lock = threading.Lock()

SETTING_LABELS = {
    "motion_area_threshold": "độ nhạy chuyển động",
    "alert_cooldown_seconds": "cooldown cảnh báo",
    "alert_video_seconds": "độ dài video",
    "alert_video_fps": "FPS video",
    "alert_history_limit": "số cảnh báo giữ trong lịch sử"
}

SETTING_UNITS = {
    "motion_area_threshold": "",
    "alert_cooldown_seconds": " giây",
    "alert_video_seconds": " giây",
    "alert_video_fps": "",
    "alert_history_limit": " cảnh báo"
}

SETTING_EXAMPLES = {
    "motion_area_threshold": "8000",
    "alert_cooldown_seconds": "20",
    "alert_video_seconds": "7",
    "alert_video_fps": "10",
    "alert_history_limit": "50"
}

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

    if normalized["alert_history_limit"] not in HISTORY_LIMIT_CHOICES:
        normalized["alert_history_limit"] = min(
            HISTORY_LIMIT_CHOICES,
            key=lambda choice: abs(choice - normalized["alert_history_limit"])
        )

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

def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)

def make_alert_id(timestamp):
    time_part = time.strftime("%Y%m%d_%H%M%S", time.localtime(timestamp))
    millis = int((timestamp - int(timestamp)) * 1000)
    return f"{time_part}_{millis:03d}"

def relative_to_base(path):
    return os.path.relpath(path, BASE_DIR)

def absolute_from_base(path):
    if not path:
        return None
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)

def load_alert_history_unlocked():
    try:
        with open(ALERT_HISTORY_FILE, "r", encoding="utf-8") as file:
            history = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]

def save_alert_history_unlocked(history):
    ensure_log_dir()
    temp_file = f"{ALERT_HISTORY_FILE}.tmp"
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(history, file, ensure_ascii=False, indent=2)
    os.replace(temp_file, ALERT_HISTORY_FILE)

def is_safe_alert_media_path(path):
    if not path:
        return False
    log_dir = os.path.abspath(LOG_DIR)
    absolute_path = os.path.abspath(absolute_from_base(path))
    if os.path.commonpath([log_dir, absolute_path]) != log_dir:
        return False
    return os.path.basename(absolute_path).startswith("alert_")

def delete_alert_media_file(path):
    if not is_safe_alert_media_path(path):
        return
    absolute_path = os.path.abspath(absolute_from_base(path))
    try:
        if os.path.isfile(absolute_path):
            os.remove(absolute_path)
    except OSError as e:
        log_error(f"Khong xoa duoc file canh bao cu: {absolute_path}", e)

def delete_alert_media_for_entries(entries):
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        delete_alert_media_file(entry.get("image_path"))
        delete_alert_media_file(entry.get("video_path"))

def delete_alert_history_entry(alert_id):
    if not alert_id:
        return False

    with history_lock:
        history = load_alert_history_unlocked()
        kept_history = []
        removed_history = []
        for entry in history:
            if str(entry.get("id", "")) == str(alert_id):
                removed_history.append(entry)
            else:
                kept_history.append(entry)

        if not removed_history:
            return False

        save_alert_history_unlocked(kept_history)
        delete_alert_media_for_entries(removed_history)
        return True

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

def format_error_log_message():
    log_text = tail_error_log().replace("```", "` ` `")
    return f"🧯 LOG LỖI GẦN NHẤT\n\n```text\n{log_text}\n```"

def escape_html(value):
    return html.escape(str(value), quote=True)

def dashboard_media_url(path):
    if not path:
        return ""
    return f"/media?path={quote(path)}"

DASHBOARD_TABS = (
    ("status", "Trạng thái"),
    ("history", "Lịch sử"),
    ("settings", "Setting"),
    ("errors", "Log lỗi")
)
DASHBOARD_TAB_KEYS = {key for key, _ in DASHBOARD_TABS}

def normalize_dashboard_tab(tab):
    if tab in DASHBOARD_TAB_KEYS:
        return tab
    return "status"

def dashboard_tab_url(tab, history_filter="all"):
    params = {"tab": normalize_dashboard_tab(tab)}
    if params["tab"] == "history":
        params["filter"] = normalize_dashboard_history_filter(history_filter)
    return "/?" + urlencode(params)

def render_dashboard_tabs(active_tab, history_filter="all"):
    links = []
    active_tab = normalize_dashboard_tab(active_tab)
    for tab_key, label in DASHBOARD_TABS:
        active_class = " active" if tab_key == active_tab else ""
        links.append(
            f'<a class="tab-link{active_class}" href="{dashboard_tab_url(tab_key, history_filter)}">'
            f"{escape_html(label)}</a>"
        )
    return f'<nav class="tabs">{"".join(links)}</nav>'

DASHBOARD_HISTORY_FILTERS = (
    ("all", "Tất cả"),
    ("today", "Hôm nay"),
    ("with_video", "Có video"),
    ("without_video", "Không có video"),
    ("newest", "Mới nhất")
)
DASHBOARD_HISTORY_FILTER_KEYS = {key for key, _ in DASHBOARD_HISTORY_FILTERS}

def normalize_dashboard_history_filter(history_filter):
    if history_filter in DASHBOARD_HISTORY_FILTER_KEYS:
        return history_filter
    return "all"

def alert_timestamp_value(entry):
    try:
        return float(entry.get("timestamp") or 0)
    except (TypeError, ValueError):
        return 0

def alert_has_dashboard_video(entry):
    video_path = entry.get("video_path")
    return is_safe_alert_media_path(video_path) and os.path.exists(absolute_from_base(video_path))

def alert_is_today(entry):
    timestamp = alert_timestamp_value(entry)
    if not timestamp:
        return False
    today = time.strftime("%Y-%m-%d", time.localtime())
    alert_day = time.strftime("%Y-%m-%d", time.localtime(timestamp))
    return alert_day == today

def filter_dashboard_history(entries, history_filter):
    history_filter = normalize_dashboard_history_filter(history_filter)
    sorted_entries = sorted(entries, key=alert_timestamp_value, reverse=True)

    if history_filter == "today":
        return [entry for entry in sorted_entries if alert_is_today(entry)]
    if history_filter == "with_video":
        return [entry for entry in sorted_entries if alert_has_dashboard_video(entry)]
    if history_filter == "without_video":
        return [entry for entry in sorted_entries if not alert_has_dashboard_video(entry)]
    if history_filter == "newest":
        return sorted_entries[:10]
    return sorted_entries

def dashboard_filter_url(history_filter):
    return "/?" + urlencode({"tab": "history", "filter": history_filter})

def render_dashboard_filter_controls(active_filter, shown_count, total_count):
    links = []
    for filter_key, label in DASHBOARD_HISTORY_FILTERS:
        active_class = " active" if filter_key == active_filter else ""
        links.append(
            f'<a class="filter-link{active_class}" href="{dashboard_filter_url(filter_key)}">'
            f"{escape_html(label)}</a>"
        )

    return (
        '<div class="filter-bar">'
        '<div class="filter-links">'
        f"{''.join(links)}"
        "</div>"
        f'<span class="filter-count">Đang hiển thị {shown_count}/{total_count}</span>'
        "</div>"
    )

def render_dashboard_history(entries, active_filter="all"):
    if not entries:
        return '<section class="empty">Chưa có cảnh báo nào.</section>'

    cards = []
    for entry in entries:
        timestamp = format_timestamp(entry.get("timestamp"))
        analysis = text_preview(entry.get("analysis"), max_length=320)
        video_status = entry.get("video_status") or "Không có video"
        image_path = entry.get("image_path")
        video_path = entry.get("video_path")
        alert_id = str(entry.get("id") or "")

        delete_html = ""
        if alert_id:
            delete_html = (
                '<form class="delete-form" method="post" action="/delete-alert" '
                'onsubmit="return confirm(\'Xóa cảnh báo này?\')">'
                f'<input type="hidden" name="id" value="{escape_html(alert_id)}">'
                f'<input type="hidden" name="filter" value="{escape_html(active_filter)}">'
                '<button class="delete-button" type="submit">Xóa</button>'
                '</form>'
            )

        image_html = ""
        if is_safe_alert_media_path(image_path) and os.path.exists(absolute_from_base(image_path)):
            image_html = (
                f'<a href="{dashboard_media_url(image_path)}" target="_blank">'
                f'<img src="{dashboard_media_url(image_path)}" alt="Ảnh cảnh báo"></a>'
            )

        video_html = ""
        if is_safe_alert_media_path(video_path) and os.path.exists(absolute_from_base(video_path)):
            video_url = dashboard_media_url(video_path)
            video_html = (
                f'<video controls preload="metadata">'
                f'<source src="{video_url}" type="video/mp4">'
                "Trình duyệt không phát được video này."
                "</video>"
                f'<a class="media-link" href="{video_url}" target="_blank">Mở/tải video</a>'
            )

        cards.append(
            "<article class=\"history-card\">"
            "<div class=\"history-meta\">"
            "<div>"
            f"<strong>{escape_html(timestamp)}</strong>"
            f"<span>{escape_html(video_status)}</span>"
            "</div>"
            f"{delete_html}"
            "</div>"
            f"<p>{escape_html(analysis)}</p>"
            f"{image_html}{video_html}"
            "</article>"
        )
    return "\n".join(cards)

def render_dashboard_html(notice="", history_filter="all", active_tab="status"):
    active_tab = normalize_dashboard_tab(active_tab)
    history_filter = normalize_dashboard_history_filter(history_filter)
    settings_snapshot = get_settings_snapshot()
    all_history_entries = get_alert_history_snapshot(settings_snapshot["alert_history_limit"])
    history_entries = filter_dashboard_history(all_history_entries, history_filter)
    filter_controls = render_dashboard_filter_controls(
        history_filter,
        len(history_entries),
        len(all_history_entries)
    )
    camera_ok, camera_status = get_camera_status_for_dashboard()
    radar_status = "BẬT" if auto_mode_active else "TẮT"
    logs_size = format_size(get_directory_size(LOG_DIR))
    uptime = format_duration(time.time() - BOT_START_TIME)
    error_log = escape_html(tail_error_log())

    settings_rows = "".join(
        f"<tr><th>{escape_html(key)}</th><td>{escape_html(value)}</td></tr>"
        for key, value in settings_snapshot.items()
    )

    notice_html = ""
    if notice:
        notice_html = f'<section class="notice">{escape_html(notice)}</section>'

    camera_class = "ok" if camera_ok else "bad"
    tabs_html = render_dashboard_tabs(active_tab, history_filter)
    status_content = f"""
    <section class="grid">
      <div class="card"><span>Radar</span><strong>{escape_html(radar_status)}</strong></div>
      <div class="card"><span>Camera</span><strong class="{camera_class}">{escape_html(camera_status)}</strong></div>
      <div class="card"><span>Lịch sử</span><strong>{len(all_history_entries)}/{settings_snapshot["alert_history_limit"]}</strong></div>
      <div class="card"><span>Logs</span><strong>{escape_html(logs_size)}</strong></div>
    </section>

    <section class="panel tab-panel">
      <h2>Trạng thái</h2>
      <table>
        <tr><th>Uptime</th><td>{escape_html(uptime)}</td></tr>
        <tr><th>Cảnh báo gần nhất</th><td>{escape_html(format_timestamp(last_alert_timestamp))}</td></tr>
        <tr><th>Dashboard local</th><td>{escape_html(DASHBOARD_URL)}</td></tr>
      </table>
    </section>"""
    history_content = f"""
    <section class="tab-panel">
      <h2>Lịch sử cảnh báo</h2>
      {filter_controls}
      <section class="history">{render_dashboard_history(history_entries, history_filter)}</section>
    </section>"""
    settings_content = f"""
    <section class="panel tab-panel">
      <h2>Setting</h2>
      <table>{settings_rows}</table>
    </section>"""
    errors_content = f"""
    <section class="panel tab-panel">
      <h2>Log lỗi gần nhất</h2>
      <pre>{error_log}</pre>
    </section>"""
    tab_content = {
        "status": status_content,
        "history": history_content,
        "settings": settings_content,
        "errors": errors_content
    }[active_tab]

    return f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>Vision Bot Dashboard</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #172033;
      --muted: #647084;
      --line: #d9e0ea;
      --accent: #006d77;
      --ok: #117a44;
      --bad: #a32b2b;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #121620;
        --panel: #1b2230;
        --text: #eef3fb;
        --muted: #aab4c5;
        --line: #303a4c;
        --accent: #56b6c2;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font: 14px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      padding: 20px 24px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    h1 {{ margin: 0 0 4px; font-size: 22px; }}
    main {{ padding: 20px 24px 40px; max-width: 1220px; margin: 0 auto; }}
    .muted {{ color: var(--muted); }}
    .tabs {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }}
    .tab-link {{ border: 1px solid var(--line); border-radius: 8px; color: var(--text); padding: 8px 11px; text-decoration: none; }}
    .tab-link.active {{ background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 700; }}
    .tab-panel {{ margin-top: 16px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .card, .history-card, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .card span {{ display: block; color: var(--muted); font-size: 12px; }}
    .card strong {{ font-size: 18px; }}
    .ok {{ color: var(--ok); }}
    .bad {{ color: var(--bad); }}
    .layout {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }}
    h2 {{ font-size: 16px; margin: 0 0 10px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 8px 0; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ color: var(--muted); width: 45%; font-weight: 600; }}
    .history {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 16px; }}
    .history-meta {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; color: var(--muted); margin-bottom: 8px; }}
    .history-meta span {{ display: block; }}
    .filter-bar {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 0 0 12px; flex-wrap: wrap; }}
    .filter-links {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .filter-link {{ border: 1px solid var(--line); border-radius: 999px; color: var(--text); padding: 6px 10px; text-decoration: none; }}
    .filter-link.active {{ background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 700; }}
    .filter-count {{ color: var(--muted); }}
    .delete-form {{ margin: 0; }}
    .delete-button {{ border: 1px solid var(--line); border-radius: 6px; background: transparent; color: var(--bad); cursor: pointer; font: inherit; font-weight: 700; padding: 5px 9px; }}
    .delete-button:hover {{ border-color: var(--bad); }}
    .history-card img, .history-card video {{ width: 100%; max-height: 360px; object-fit: contain; border-radius: 6px; border: 1px solid var(--line); background: #000; margin-top: 8px; }}
    .media-link {{ display: inline-block; margin-top: 8px; color: var(--accent); font-weight: 700; text-decoration: none; }}
    .notice {{ margin-bottom: 14px; padding: 10px 12px; border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 8px; background: var(--panel); }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; color: var(--muted); }}
    .empty {{ padding: 20px; color: var(--muted); }}
    @media (max-width: 860px) {{
      .grid, .layout, .history {{ grid-template-columns: 1fr; }}
      header, main {{ padding-left: 14px; padding-right: 14px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Vision Bot Dashboard</h1>
    <div class="muted">Chỉ mở trên máy tính này: {escape_html(DASHBOARD_URL)} · Tự refresh mỗi 30 giây</div>
    {tabs_html}
  </header>
  <main>
    {notice_html}
    {tab_content}
  </main>
</body>
</html>"""

def parse_range_header(range_header, file_size):
    if not range_header or not range_header.startswith("bytes="):
        return None, False

    range_spec = range_header[len("bytes="):].split(",", 1)[0].strip()
    if "-" not in range_spec:
        return None, True

    start_text, end_text = range_spec.split("-", 1)
    try:
        if start_text == "":
            suffix_length = int(end_text)
            if suffix_length <= 0:
                return None, True
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
    except ValueError:
        return None, True

    end = min(end, file_size - 1)
    if start < 0 or start >= file_size or end < start:
        return None, True
    return (start, end), True

def send_dashboard_file(handler, absolute_path, content_type):
    file_size = os.path.getsize(absolute_path)
    byte_range, range_requested = parse_range_header(handler.headers.get("Range"), file_size)

    if range_requested and byte_range is None:
        handler.send_response(416)
        handler.send_header("Content-Range", f"bytes */{file_size}")
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return

    if byte_range is None:
        start = 0
        end = file_size - 1
        status_code = 200
    else:
        start, end = byte_range
        status_code = 206

    content_length = end - start + 1
    handler.send_response(status_code)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Content-Length", str(content_length))
    if status_code == 206:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()

    remaining = content_length
    with open(absolute_path, "rb") as file:
        file.seek(start)
        while remaining > 0:
            chunk = file.read(min(64 * 1024, remaining))
            if not chunk:
                break
            try:
                handler.wfile.write(chunk)
            except (ConnectionError, TimeoutError):
                return
            remaining -= len(chunk)

def serve_dashboard_media(handler, query):
    media_path = query.get("path", [""])[0]
    if not is_safe_alert_media_path(media_path):
        handler.send_error(403)
        return

    absolute_path = os.path.abspath(absolute_from_base(media_path))
    if not os.path.isfile(absolute_path):
        handler.send_error(404)
        return

    try:
        content_type = mimetypes.guess_type(absolute_path)[0] or "application/octet-stream"
        send_dashboard_file(handler, absolute_path, content_type)
    except OSError as e:
        log_error(f"Khong doc duoc media dashboard: {absolute_path}", e)
        handler.send_error(404)

def redirect_dashboard(handler, location):
    handler.send_response(303)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", "0")
    handler.end_headers()

class DashboardRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urlparse(self.path)
        if parsed_url.path in ("/", "/index.html"):
            query = parse_qs(parsed_url.query)
            active_tab = normalize_dashboard_tab(query.get("tab", ["status"])[0])
            history_filter = normalize_dashboard_history_filter(query.get("filter", ["all"])[0])
            notice = ""
            if query.get("deleted") == ["1"]:
                notice = "Đã xóa cảnh báo."
            elif query.get("deleted") == ["0"]:
                notice = "Không tìm thấy cảnh báo để xóa."

            body = render_dashboard_html(notice, history_filter, active_tab).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed_url.path == "/media":
            serve_dashboard_media(self, parse_qs(parsed_url.query))
            return

        self.send_error(404)

    def do_POST(self):
        parsed_url = urlparse(self.path)
        if parsed_url.path != "/delete-alert":
            self.send_error(404)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        body = self.rfile.read(min(content_length, 4096)).decode("utf-8", errors="replace")
        form = parse_qs(body)
        alert_id = form.get("id", [""])[0]
        history_filter = normalize_dashboard_history_filter(form.get("filter", ["all"])[0])
        deleted = delete_alert_history_entry(alert_id)
        redirect_dashboard(
            self,
            "/?" + urlencode({
                "tab": "history",
                "filter": history_filter,
                "deleted": "1" if deleted else "0"
            })
        )

    def log_message(self, format, *args):
        return

def start_dashboard_server():
    try:
        server = ThreadingHTTPServer((DASHBOARD_HOST, DASHBOARD_PORT), DashboardRequestHandler)
    except OSError as e:
        log_error(f"Khong khoi dong duoc dashboard local tai {DASHBOARD_URL}", e)
        return

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Dashboard local dang chay tai {DASHBOARD_URL}")

def add_alert_history(entry):
    with history_lock:
        history = load_alert_history_unlocked()
        history.insert(0, entry)
        limit = get_setting("alert_history_limit")
        kept_history = history[:limit]
        removed_history = history[limit:]
        save_alert_history_unlocked(kept_history)
        delete_alert_media_for_entries(removed_history)

def get_recent_alert_history(limit=HISTORY_PREVIEW_LIMIT):
    with history_lock:
        return load_alert_history_unlocked()[:limit]

def get_alert_history_snapshot(limit=None):
    with history_lock:
        history = load_alert_history_unlocked()
    if limit is None:
        return history
    return history[:limit]

def get_alert_history_count():
    with history_lock:
        return len(load_alert_history_unlocked())

def trim_alert_history(limit):
    with history_lock:
        history = load_alert_history_unlocked()
        kept_history = history[:limit]
        removed_history = history[limit:]
        save_alert_history_unlocked(kept_history)
        delete_alert_media_for_entries(removed_history)

def clear_alert_history_files():
    log_dir = os.path.abspath(LOG_DIR)
    base_dir = os.path.abspath(BASE_DIR)
    if os.path.basename(log_dir).lower() != "logs" or os.path.commonpath([base_dir, log_dir]) != base_dir:
        raise RuntimeError("Duong dan logs khong hop le, da huy thao tac xoa.")

    with history_lock:
        ensure_log_dir()
        for name in os.listdir(log_dir):
            path = os.path.join(log_dir, name)
            should_delete = (
                name.startswith("alert_")
                or name in ("alert_history.json", "alert_history.json.tmp")
            )
            if not should_delete:
                continue
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        save_alert_history_unlocked([])

def text_preview(text, max_length=140):
    if not text:
        return "Không có phân tích"
    compact = " ".join(str(text).split())
    if len(compact) <= max_length:
        return compact
    return f"{compact[:max_length - 3]}..."

def format_alert_history_message(entries):
    if not entries:
        return "🧾 LỊCH SỬ CẢNH BÁO\n\nChưa có cảnh báo nào được ghi lại."

    lines = ["🧾 LỊCH SỬ CẢNH BÁO GẦN NHẤT"]
    for index, entry in enumerate(entries, start=1):
        timestamp = entry.get("timestamp")
        video_status = entry.get("video_status") or "Không có video"
        analysis = text_preview(entry.get("analysis"))
        lines.append(
            f"\n{index}. {format_timestamp(timestamp)}\n"
            f"Video: {video_status}\n"
            f"Gemini: {analysis}"
        )
    return "\n".join(lines)

def send_alert_history(chat_id, limit=HISTORY_PREVIEW_LIMIT):
    entries = get_recent_alert_history(limit)
    try:
        bot.send_message(chat_id, format_alert_history_message(entries))
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
        f"🧾 Giữ lịch sử: {current['alert_history_limit']} cảnh báo\n\n"
        "Bấm nút bên dưới để chỉnh. Với các mục số, bot sẽ hỏi và bạn chỉ cần nhập số mới vào khung chat."
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

def build_setting_prompt(setting_name):
    label = SETTING_LABELS[setting_name]
    unit = SETTING_UNITS[setting_name]
    min_value, max_value = SETTING_LIMITS[setting_name]
    current_value = get_setting(setting_name)
    example = SETTING_EXAMPLES[setting_name]
    return (
        f"Nhập {label} mới.\n"
        f"Hiện tại: {current_value}{unit}\n"
        f"Khoảng hợp lệ: {min_value}-{max_value}{unit}\n"
        f"Ví dụ: {example}\n\n"
        "Gõ hủy để bỏ qua."
    )

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

def build_main_menu():
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(telebot.types.InlineKeyboardButton("📸 Chụp ngay", callback_data="menu:capture"))
    keyboard.add(
        telebot.types.InlineKeyboardButton("🟢 Bật Radar", callback_data="menu:auto_on"),
        telebot.types.InlineKeyboardButton("🔴 Tắt Radar", callback_data="menu:auto_off")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("📡 Trạng thái", callback_data="menu:status"),
        telebot.types.InlineKeyboardButton("🧾 Lịch sử", callback_data="menu:history")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("🧯 Xem log lỗi", callback_data="menu:error_log"),
        telebot.types.InlineKeyboardButton("⚙️ Cài đặt", callback_data="menu:settings")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("🔄 Restart bot", callback_data="menu:restart_confirm"),
        telebot.types.InlineKeyboardButton("🧹 Dọn lịch sử", callback_data="menu:clear_history_confirm")
    )
    return keyboard

def build_restart_confirm_menu():
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        telebot.types.InlineKeyboardButton("✅ Restart ngay", callback_data="menu:restart_execute"),
        telebot.types.InlineKeyboardButton("⬅️ Không restart", callback_data="menu:main")
    )
    return keyboard

def build_clear_history_confirm_menu():
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        telebot.types.InlineKeyboardButton("✅ Xóa hết lịch sử", callback_data="menu:clear_history_execute"),
        telebot.types.InlineKeyboardButton("⬅️ Không xóa", callback_data="menu:main")
    )
    return keyboard

def build_settings_menu():
    current = get_settings_snapshot()
    video_label = "📹 Tắt video" if current["send_video"] else "📹 Bật video"
    ai_label = "🧠 Tắt Gemini" if current["use_gemini_analysis"] else "🧠 Bật Gemini"
    history_buttons = [
        telebot.types.InlineKeyboardButton(
            f"{'✅ ' if current['alert_history_limit'] == choice else ''}{choice} cảnh báo",
            callback_data=f"setting:history_limit:{choice}"
        )
        for choice in HISTORY_LIMIT_CHOICES
    ]

    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        telebot.types.InlineKeyboardButton("🎯 Nhập độ nhạy", callback_data="setting:input:motion_area_threshold"),
        telebot.types.InlineKeyboardButton("⏱️ Nhập cooldown", callback_data="setting:input:alert_cooldown_seconds")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("🎥 Nhập giây video", callback_data="setting:input:alert_video_seconds"),
        telebot.types.InlineKeyboardButton("🎞️ Nhập FPS", callback_data="setting:input:alert_video_fps")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton(video_label, callback_data="setting:toggle_video"),
        telebot.types.InlineKeyboardButton(ai_label, callback_data="setting:toggle_ai")
    )
    keyboard.add(*history_buttons)
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
    except Exception as e:
        log_error("Khong edit duoc menu message, fallback sang send_message", e)
        bot.send_message(call.message.chat.id, text, reply_markup=reply_markup)

def ask_ai(image_path, user_question):
    img = Image.open(image_path)
    prompt = f"Bạn là bộ não an ninh. Chủ vừa yêu cầu: '{user_question}'. \n Hãy quan sát tỷ mỉ ảnh camera trực tiếp này và trả lời cực kỳ ngắn gọn, khách quan."
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[prompt, img]
    )
    return response.text

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

    camera = None
    success = False
    try:
        camera = cv2.VideoCapture(0)
        time.sleep(1)
        success, img = camera.read()
    finally:
        if camera is not None:
            camera.release()
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
    cv2.imwrite(image_path, img)

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

def get_camera_status_for_dashboard():
    if auto_mode_active:
        return camera_online, last_camera_status
    if last_camera_status and last_camera_status != "Chưa kiểm tra camera":
        return camera_online, last_camera_status
    return False, "Camera chưa kiểm tra trên dashboard"

def format_duration(seconds):
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days} ngày")
    if hours:
        parts.append(f"{hours} giờ")
    if minutes:
        parts.append(f"{minutes} phút")
    if seconds or not parts:
        parts.append(f"{seconds} giây")
    return " ".join(parts)

def get_directory_size(path):
    total_size = 0
    if not os.path.isdir(path):
        return 0

    for root, _, files in os.walk(path):
        for filename in files:
            file_path = os.path.join(root, filename)
            try:
                total_size += os.path.getsize(file_path)
            except OSError as e:
                log_error(f"Khong doc duoc dung luong file log: {file_path}", e)
    return total_size

def format_size(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024

def format_settings_snapshot(settings_snapshot):
    return (
        f"Độ nhạy {settings_snapshot['motion_area_threshold']} | "
        f"Cooldown {settings_snapshot['alert_cooldown_seconds']}s | "
        f"Video {settings_snapshot['alert_video_seconds']}s/{settings_snapshot['alert_video_fps']}fps | "
        f"Gửi video {on_off_label(settings_snapshot['send_video'])} | "
        f"Gemini {on_off_label(settings_snapshot['use_gemini_analysis'])} | "
        f"Giữ lịch sử {settings_snapshot['alert_history_limit']}"
    )

def format_status_message():
    camera_ok, camera_status = get_camera_status_for_report()
    radar_status = "BẬT" if auto_mode_active else "TẮT"
    camera_icon = "✅" if camera_ok else "❌"
    alert_time = format_timestamp(last_alert_timestamp)
    uptime = format_duration(time.time() - BOT_START_TIME)
    alert_count = get_alert_history_count()
    logs_size = format_size(get_directory_size(LOG_DIR))
    settings_snapshot = get_settings_snapshot()

    return (
        "📡 TRẠNG THÁI VISION BOT\n\n"
        "✅ Bot: Đang chạy và nhận lệnh Telegram\n"
        f"📍 Radar: {radar_status}\n"
        f"{camera_icon} Camera: {camera_status}\n"
        f"🚨 Lần cảnh báo gần nhất: {alert_time}\n"
        f"🧾 Cảnh báo trong lịch sử: {alert_count}/{settings_snapshot['alert_history_limit']}\n"
        f"💾 Dung lượng logs: {logs_size}\n"
        f"⏳ Uptime: {uptime}\n"
        f"🌐 Dashboard local: {DASHBOARD_URL}\n"
        f"⚙️ Setting: {format_settings_snapshot(settings_snapshot)}"
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

def create_alert_video_writer(video_path, fps, frame_size):
    codec_options = (
        ("avc1", "H.264"),
        ("H264", "H.264"),
        ("mp4v", "MP4V")
    )
    for fourcc_name, codec_label in codec_options:
        writer = cv2.VideoWriter(
            video_path,
            cv2.VideoWriter_fourcc(*fourcc_name),
            fps,
            frame_size
        )
        if writer.isOpened():
            return writer, codec_label
        writer.release()
    return None, ""

def record_alert_video(camera_stream, first_frame, video_path, duration_seconds, fps):
    height, width = first_frame.shape[:2]
    width -= width % 2
    height -= height % 2
    frame_size = (width, height)
    writer, codec_label = create_alert_video_writer(video_path, fps, frame_size)
    if writer is None:
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
        return True, f"Camera dừng sớm, đã gửi phần video ghi được ({codec_label})"
    return True, f"Đã ghi clip {duration_seconds} giây ({codec_label})"

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
                camera_stream = cv2.VideoCapture(0)
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
                for _ in range(5):
                    camera_stream.read()
                
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
                alert_id = make_alert_id(last_alert_time)
                ensure_log_dir()
                image_path = os.path.join(LOG_DIR, f"alert_{alert_id}.jpg")
                video_path = None
                video_status = "Không ghi video"
                analysis = "Gemini đang tắt"
                cv2.imwrite(image_path, img)
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
    bot.reply_to(message, format_status_message())

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
        edit_menu_message(call, format_status_message(), build_main_menu())
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
        bot.send_message(call.message.chat.id, format_error_log_message(), parse_mode="Markdown")
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
        start_dashboard_server()
        send_startup_notification()
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
