import json
import os
import threading


HISTORY_LIMIT_CHOICES = (10, 50, 100)
CAMERA_INDEX_CHOICES = (0, 1, 2)
CAMERA_ROTATION_CHOICES = (0, 90, 180, 270)

DEFAULT_SETTINGS = {
    "motion_area_threshold": 8000,
    "alert_cooldown_seconds": 10,
    "alert_video_seconds": 7,
    "alert_video_fps": 10,
    "send_video": True,
    "use_gemini_analysis": True,
    "person_filter_enabled": False,
    "daily_summary_enabled": False,
    "daily_summary_hour": 8,
    "daily_summary_minute": 0,
    "quiet_hours_enabled": False,
    "quiet_hours_start_hour": 22,
    "quiet_hours_end_hour": 7,
    "alert_history_limit": 50,
    "camera_index": 0,
    "camera_width": 0,
    "camera_height": 0,
    "camera_fps": 0,
    "camera_rotation": 0,
    "motion_detection_enabled": True,
    "input_monitoring_enabled": True,
    "send_screen_record": True,
    "send_input_camera_photo": True
}

SETTING_LIMITS = {
    "motion_area_threshold": (500, 50000),
    "alert_cooldown_seconds": (3, 3600),
    "alert_video_seconds": (5, 10),
    "alert_video_fps": (5, 30),
    "alert_history_limit": (10, 100),
    "daily_summary_hour": (0, 23),
    "daily_summary_minute": (0, 59),
    "quiet_hours_start_hour": (0, 23),
    "quiet_hours_end_hour": (0, 23),
    "camera_index": (0, 2),
    "camera_width": (0, 3840),
    "camera_height": (0, 2160),
    "camera_fps": (0, 60),
    "camera_rotation": (0, 270)
}

SETTING_CHOICES = {
    "alert_history_limit": HISTORY_LIMIT_CHOICES,
    "camera_index": CAMERA_INDEX_CHOICES,
    "camera_rotation": CAMERA_ROTATION_CHOICES
}

SETTING_LABELS = {
    "motion_area_threshold": "độ nhạy chuyển động",
    "alert_cooldown_seconds": "cooldown cảnh báo",
    "alert_video_seconds": "độ dài video",
    "alert_video_fps": "FPS video",
    "person_filter_enabled": "chỉ cảnh báo khi thấy người",
    "daily_summary_enabled": "gửi tóm tắt hằng ngày",
    "daily_summary_hour": "giờ tóm tắt hằng ngày",
    "daily_summary_minute": "phút tóm tắt hằng ngày",
    "quiet_hours_enabled": "giờ yên lặng",
    "quiet_hours_start_hour": "giờ bắt đầu yên lặng",
    "quiet_hours_end_hour": "giờ kết thúc yên lặng",
    "alert_history_limit": "số cảnh báo giữ trong lịch sử",
    "camera_index": "camera index",
    "camera_width": "chiều rộng camera",
    "camera_height": "chiều cao camera",
    "camera_fps": "FPS camera",
    "camera_rotation": "góc xoay camera",
    "motion_detection_enabled": "quan sát chuyển động camera",
    "input_monitoring_enabled": "giám sát bàn phím/chuột",
    "send_screen_record": "gửi video quay màn hình khi đụng phím/chuột",
    "send_input_camera_photo": "gửi ảnh camera khi đụng phím/chuột"
}

SETTING_UNITS = {
    "motion_area_threshold": "",
    "alert_cooldown_seconds": " giây",
    "alert_video_seconds": " giây",
    "alert_video_fps": "",
    "person_filter_enabled": "",
    "daily_summary_enabled": "",
    "daily_summary_hour": "",
    "daily_summary_minute": "",
    "quiet_hours_enabled": "",
    "quiet_hours_start_hour": " giờ",
    "quiet_hours_end_hour": " giờ",
    "alert_history_limit": " cảnh báo",
    "camera_index": "",
    "camera_width": " px",
    "camera_height": " px",
    "camera_fps": " fps",
    "camera_rotation": " độ",
    "motion_detection_enabled": "",
    "input_monitoring_enabled": "",
    "send_screen_record": "",
    "send_input_camera_photo": ""
}

SETTING_EXAMPLES = {
    "motion_area_threshold": "8000",
    "alert_cooldown_seconds": "20",
    "alert_video_seconds": "7",
    "alert_video_fps": "10",
    "person_filter_enabled": "bat",
    "daily_summary_enabled": "bat",
    "daily_summary_hour": "8",
    "daily_summary_minute": "0",
    "quiet_hours_enabled": "bat",
    "quiet_hours_start_hour": "22",
    "quiet_hours_end_hour": "7",
    "alert_history_limit": "50",
    "camera_index": "0",
    "camera_width": "1280",
    "camera_height": "720",
    "camera_fps": "30",
    "camera_rotation": "180",
    "motion_detection_enabled": "bat",
    "input_monitoring_enabled": "bat",
    "send_screen_record": "bat",
    "send_input_camera_photo": "bat"
}

_settings_file = None
_settings_lock = threading.Lock()
_settings = DEFAULT_SETTINGS.copy()


def configure_settings_store(settings_path):
    global _settings_file, _settings
    _settings_file = settings_path
    with _settings_lock:
        _settings = load_settings()


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


def snap_to_choice(value, choices):
    return min(choices, key=lambda choice: abs(choice - value))


def normalize_settings(raw_settings):
    normalized = DEFAULT_SETTINGS.copy()
    if isinstance(raw_settings, dict):
        normalized.update({key: raw_settings[key] for key in DEFAULT_SETTINGS if key in raw_settings})

    for key, (min_value, max_value) in SETTING_LIMITS.items():
        normalized[key] = clamp_int(normalized[key], DEFAULT_SETTINGS[key], min_value, max_value)

    for key, choices in SETTING_CHOICES.items():
        if normalized[key] not in choices:
            normalized[key] = snap_to_choice(normalized[key], choices)

    normalized["send_video"] = normalize_bool(
        normalized["send_video"],
        DEFAULT_SETTINGS["send_video"]
    )
    normalized["use_gemini_analysis"] = normalize_bool(
        normalized["use_gemini_analysis"],
        DEFAULT_SETTINGS["use_gemini_analysis"]
    )
    normalized["person_filter_enabled"] = normalize_bool(
        normalized["person_filter_enabled"],
        DEFAULT_SETTINGS["person_filter_enabled"]
    )
    normalized["daily_summary_enabled"] = normalize_bool(
        normalized["daily_summary_enabled"],
        DEFAULT_SETTINGS["daily_summary_enabled"]
    )
    normalized["quiet_hours_enabled"] = normalize_bool(
        normalized["quiet_hours_enabled"],
        DEFAULT_SETTINGS["quiet_hours_enabled"]
    )
    normalized["motion_detection_enabled"] = normalize_bool(
        normalized["motion_detection_enabled"],
        DEFAULT_SETTINGS["motion_detection_enabled"]
    )
    normalized["input_monitoring_enabled"] = normalize_bool(
        normalized["input_monitoring_enabled"],
        DEFAULT_SETTINGS["input_monitoring_enabled"]
    )
    normalized["send_screen_record"] = normalize_bool(
        normalized["send_screen_record"],
        DEFAULT_SETTINGS["send_screen_record"]
    )
    normalized["send_input_camera_photo"] = normalize_bool(
        normalized["send_input_camera_photo"],
        DEFAULT_SETTINGS["send_input_camera_photo"]
    )
    if not normalized["motion_detection_enabled"] and not normalized["input_monitoring_enabled"]:
        normalized["motion_detection_enabled"] = True
    return normalized


def load_settings():
    if _settings_file is None:
        return DEFAULT_SETTINGS.copy()

    try:
        with open(_settings_file, "r", encoding="utf-8") as file:
            return normalize_settings(json.load(file))
    except FileNotFoundError:
        return DEFAULT_SETTINGS.copy()
    except (json.JSONDecodeError, OSError):
        return DEFAULT_SETTINGS.copy()


def save_settings(settings_to_save):
    if _settings_file is None:
        raise RuntimeError("Settings store has not been configured.")

    settings_dir = os.path.dirname(_settings_file)
    if settings_dir:
        os.makedirs(settings_dir, exist_ok=True)

    temp_file = f"{_settings_file}.tmp"
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(settings_to_save, file, ensure_ascii=False, indent=2)
    os.replace(temp_file, _settings_file)


def get_setting(name):
    with _settings_lock:
        return _settings[name]


def get_settings_snapshot():
    with _settings_lock:
        return _settings.copy()


def update_setting(name, value):
    with _settings_lock:
        _settings[name] = value
        normalized = normalize_settings(_settings)
        _settings.clear()
        _settings.update(normalized)
        save_settings(_settings.copy())


def restore_settings_from_file(settings_path):
    with open(settings_path, "r", encoding="utf-8") as file:
        restored_settings = normalize_settings(json.load(file))

    global _settings
    with _settings_lock:
        _settings = restored_settings
        save_settings(_settings.copy())
        return _settings.copy()
