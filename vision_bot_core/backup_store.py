import os
import shutil
import time


DEFAULT_MAX_BACKUPS = 30


def safe_name_part(value):
    text = str(value).strip().lower()
    chars = []
    for char in text:
        if char.isalnum() or char in ("-", "_"):
            chars.append(char)
        else:
            chars.append("_")
    safe_text = "".join(chars).strip("_")
    return safe_text or "backup"


def backup_json_file(source_path, backup_dir, label, reason="", log_error=None):
    if not source_path or not os.path.exists(source_path):
        return None

    try:
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        unique = time.time_ns() % 1_000_000_000
        filename = (
            f"{safe_name_part(label)}_"
            f"{safe_name_part(reason)}_"
            f"{timestamp}_{unique:09d}.json"
        )
        backup_path = os.path.join(backup_dir, filename)
        shutil.copy2(source_path, backup_path)
        return backup_path
    except OSError as e:
        if log_error is not None:
            log_error(f"Khong tao duoc backup cho {source_path}", e)
        return None


def prune_backups(backup_dir, max_backups=DEFAULT_MAX_BACKUPS, log_error=None):
    if max_backups is None or max_backups <= 0 or not os.path.isdir(backup_dir):
        return

    try:
        backup_files = [
            os.path.join(backup_dir, name)
            for name in os.listdir(backup_dir)
            if name.endswith(".json") and os.path.isfile(os.path.join(backup_dir, name))
        ]
        backup_files.sort(key=lambda path: (os.path.getmtime(path), path), reverse=True)
        for path in backup_files[max_backups:]:
            os.remove(path)
    except OSError as e:
        if log_error is not None:
            log_error(f"Khong don duoc thu muc backup: {backup_dir}", e)


def backup_json_files(file_specs, backup_dir, reason, max_backups=DEFAULT_MAX_BACKUPS, log_error=None):
    backup_paths = []
    for label, source_path in file_specs:
        backup_path = backup_json_file(source_path, backup_dir, label, reason, log_error=log_error)
        if backup_path is not None:
            backup_paths.append(backup_path)

    prune_backups(backup_dir, max_backups=max_backups, log_error=log_error)
    return backup_paths
