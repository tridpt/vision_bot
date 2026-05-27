import json
import os
import shutil
import threading
import time


_base_dir = None
_log_dir = None
_alert_history_file = None
_get_history_limit = None
_log_error = None
_history_lock = threading.Lock()


def configure_alert_history_store(
    base_dir,
    log_dir,
    alert_history_file,
    get_history_limit,
    log_error
):
    global _base_dir, _log_dir, _alert_history_file, _get_history_limit, _log_error
    _base_dir = base_dir
    _log_dir = log_dir
    _alert_history_file = alert_history_file
    _get_history_limit = get_history_limit
    _log_error = log_error


def ensure_log_dir():
    os.makedirs(_log_dir, exist_ok=True)


def make_alert_id(timestamp):
    time_part = time.strftime("%Y%m%d_%H%M%S", time.localtime(timestamp))
    millis = int((timestamp - int(timestamp)) * 1000)
    return f"{time_part}_{millis:03d}"


def relative_to_base(path):
    return os.path.relpath(path, _base_dir)


def absolute_from_base(path):
    if not path:
        return None
    if os.path.isabs(path):
        return path
    return os.path.join(_base_dir, path)


def load_alert_history_unlocked():
    try:
        with open(_alert_history_file, "r", encoding="utf-8") as file:
            history = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]


def load_alert_history_from_file(history_file, limit=None):
    with open(history_file, "r", encoding="utf-8") as file:
        history = json.load(file)

    if not isinstance(history, list):
        history = []

    restored_history = [entry for entry in history if isinstance(entry, dict)]
    if limit is not None:
        restored_history = restored_history[:limit]
    return restored_history


def save_alert_history_unlocked(history):
    ensure_log_dir()
    temp_file = f"{_alert_history_file}.tmp"
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(history, file, ensure_ascii=False, indent=2)
    os.replace(temp_file, _alert_history_file)


def is_safe_alert_media_path(path):
    if not path:
        return False
    log_dir = os.path.abspath(_log_dir)
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
        _log_error(f"Khong xoa duoc file canh bao cu: {absolute_path}", e)


def delete_alert_media_for_entries(entries):
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        delete_alert_media_file(entry.get("image_path"))
        delete_alert_media_file(entry.get("video_path"))


def delete_alert_history_entry(alert_id):
    if not alert_id:
        return False

    with _history_lock:
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


def add_alert_history(entry):
    with _history_lock:
        history = load_alert_history_unlocked()
        history.insert(0, entry)
        limit = _get_history_limit()
        kept_history = history[:limit]
        removed_history = history[limit:]
        save_alert_history_unlocked(kept_history)
        delete_alert_media_for_entries(removed_history)


def get_recent_alert_history(limit):
    with _history_lock:
        return load_alert_history_unlocked()[:limit]


def get_alert_history_snapshot(limit=None):
    with _history_lock:
        history = load_alert_history_unlocked()
    if limit is None:
        return history
    return history[:limit]


def get_alert_history_count():
    with _history_lock:
        return len(load_alert_history_unlocked())


def trim_alert_history(limit):
    with _history_lock:
        history = load_alert_history_unlocked()
        kept_history = history[:limit]
        removed_history = history[limit:]
        save_alert_history_unlocked(kept_history)
        delete_alert_media_for_entries(removed_history)


def restore_alert_history(history):
    with _history_lock:
        save_alert_history_unlocked(history)
        return list(history)


def restore_alert_history_from_file(history_file, limit=None):
    history = load_alert_history_from_file(history_file, limit=limit)
    return restore_alert_history(history)


def clear_alert_history_files():
    log_dir = os.path.abspath(_log_dir)
    base_dir = os.path.abspath(_base_dir)
    if os.path.basename(log_dir).lower() != "logs" or os.path.commonpath([base_dir, log_dir]) != base_dir:
        raise RuntimeError("Duong dan logs khong hop le, da huy thao tac xoa.")

    with _history_lock:
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
