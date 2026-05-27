import html
import json
import mimetypes
import os
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlencode, urlparse


@dataclass
class DashboardContext:
    host: str
    port: int
    url: str
    log_dir: str
    settings_limits: dict
    setting_labels: dict
    setting_units: dict
    history_limit_choices: tuple
    bot_start_time: float
    get_settings_snapshot: object
    get_alert_history_snapshot: object
    get_camera_status: object
    is_radar_active: object
    format_size: object
    get_directory_size: object
    format_duration: object
    tail_error_log: object
    format_timestamp: object
    last_alert_timestamp: object
    text_preview: object
    is_safe_alert_media_path: object
    absolute_from_base: object
    delete_alert_history_entry: object
    update_setting: object
    trim_alert_history: object
    list_backups: object
    restore_settings_backup: object
    restore_alert_history_backup: object
    restore_latest_settings_backup: object
    restore_latest_alert_history_backup: object
    delete_backup: object
    clamp_int: object
    log_error: object


DASHBOARD_TABS = (
    ("status", "Trạng thái"),
    ("history", "Lịch sử"),
    ("settings", "Setting"),
    ("backups", "Backup"),
    ("errors", "Log lỗi")
)
DASHBOARD_TAB_KEYS = {key for key, _ in DASHBOARD_TABS}

DASHBOARD_HISTORY_FILTERS = (
    ("all", "Tất cả"),
    ("today", "Hôm nay"),
    ("with_video", "Có video"),
    ("without_video", "Không có video"),
    ("newest", "Mới nhất")
)
DASHBOARD_HISTORY_FILTER_KEYS = {key for key, _ in DASHBOARD_HISTORY_FILTERS}

DASHBOARD_BACKUP_FILTERS = (
    ("all", "Tất cả"),
    ("settings", "Setting"),
    ("history", "Lịch sử"),
    ("newest", "Mới nhất")
)
DASHBOARD_BACKUP_FILTER_KEYS = {key for key, _ in DASHBOARD_BACKUP_FILTERS}

HISTORY_EXPORT_FILENAMES = {"alert_history.json", "bot_errors.log"}
HISTORY_EXPORT_MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".mp4", ".avi", ".mov", ".webm"}


def escape_html(value):
    return html.escape(str(value), quote=True)


def dashboard_media_url(path):
    if not path:
        return ""
    return f"/media?path={quote(path)}"


def normalize_dashboard_tab(tab):
    if tab in DASHBOARD_TAB_KEYS:
        return tab
    return "status"


def normalize_dashboard_history_filter(history_filter):
    if history_filter in DASHBOARD_HISTORY_FILTER_KEYS:
        return history_filter
    return "all"


def normalize_dashboard_backup_filter(backup_filter):
    if backup_filter in DASHBOARD_BACKUP_FILTER_KEYS:
        return backup_filter
    return "all"


def dashboard_tab_url(tab, history_filter="all", backup_filter="all"):
    params = {"tab": normalize_dashboard_tab(tab)}
    if params["tab"] == "history":
        params["filter"] = normalize_dashboard_history_filter(history_filter)
    if params["tab"] == "backups":
        params["backup_filter"] = normalize_dashboard_backup_filter(backup_filter)
    return "/?" + urlencode(params)


def render_dashboard_tabs(active_tab, history_filter="all", backup_filter="all"):
    links = []
    active_tab = normalize_dashboard_tab(active_tab)
    for tab_key, label in DASHBOARD_TABS:
        active_class = " active" if tab_key == active_tab else ""
        links.append(
            f'<a class="tab-link{active_class}" href="{dashboard_tab_url(tab_key, history_filter, backup_filter)}">'
            f"{escape_html(label)}</a>"
        )
    return f'<nav class="tabs">{"".join(links)}</nav>'


def alert_timestamp_value(entry):
    try:
        return float(entry.get("timestamp") or 0)
    except (TypeError, ValueError):
        return 0


def alert_has_dashboard_video(ctx, entry):
    video_path = entry.get("video_path")
    return ctx.is_safe_alert_media_path(video_path) and os.path.exists(ctx.absolute_from_base(video_path))


def alert_is_today(entry):
    timestamp = alert_timestamp_value(entry)
    if not timestamp:
        return False
    today = time.strftime("%Y-%m-%d", time.localtime())
    alert_day = time.strftime("%Y-%m-%d", time.localtime(timestamp))
    return alert_day == today


def filter_dashboard_history(ctx, entries, history_filter):
    history_filter = normalize_dashboard_history_filter(history_filter)
    sorted_entries = sorted(entries, key=alert_timestamp_value, reverse=True)

    if history_filter == "today":
        return [entry for entry in sorted_entries if alert_is_today(entry)]
    if history_filter == "with_video":
        return [entry for entry in sorted_entries if alert_has_dashboard_video(ctx, entry)]
    if history_filter == "without_video":
        return [entry for entry in sorted_entries if not alert_has_dashboard_video(ctx, entry)]
    if history_filter == "newest":
        return sorted_entries[:10]
    return sorted_entries


def dashboard_filter_url(history_filter):
    return "/?" + urlencode({"tab": "history", "filter": history_filter})


def dashboard_backup_detail_url(filename, backup_filter="all"):
    return "/?" + urlencode({
        "tab": "backups",
        "backup_filter": normalize_dashboard_backup_filter(backup_filter),
        "backup": filename
    })


def dashboard_backup_download_url(filename):
    return "/download-backup?" + urlencode({"filename": filename})


def dashboard_history_zip_url():
    return "/download-history-zip"


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


def render_dashboard_history_actions():
    return (
        '<div class="history-actions">'
        f'<a class="download-button" href="{dashboard_history_zip_url()}">Tải lịch sử .zip</a>'
        "</div>"
    )


def filter_dashboard_backups(backups, backup_filter):
    backup_filter = normalize_dashboard_backup_filter(backup_filter)
    if backup_filter == "settings":
        return [backup for backup in backups if backup.get("label") == "settings"]
    if backup_filter == "history":
        return [backup for backup in backups if backup.get("label") == "alert_history"]
    if backup_filter == "newest":
        return backups[:10]
    return backups


def dashboard_backup_filter_url(backup_filter):
    return "/?" + urlencode({
        "tab": "backups",
        "backup_filter": normalize_dashboard_backup_filter(backup_filter)
    })


def render_dashboard_backup_filter_controls(active_filter, shown_count, total_count):
    links = []
    active_filter = normalize_dashboard_backup_filter(active_filter)
    for filter_key, label in DASHBOARD_BACKUP_FILTERS:
        active_class = " active" if filter_key == active_filter else ""
        links.append(
            f'<a class="filter-link{active_class}" href="{dashboard_backup_filter_url(filter_key)}">'
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


def render_dashboard_history(ctx, entries, active_filter="all"):
    if not entries:
        return '<section class="empty">Chưa có cảnh báo nào.</section>'

    cards = []
    for entry in entries:
        timestamp = ctx.format_timestamp(entry.get("timestamp"))
        analysis = ctx.text_preview(entry.get("analysis"), max_length=320)
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
        if ctx.is_safe_alert_media_path(image_path) and os.path.exists(ctx.absolute_from_base(image_path)):
            image_html = (
                f'<a href="{dashboard_media_url(image_path)}" target="_blank">'
                f'<img src="{dashboard_media_url(image_path)}" alt="Ảnh cảnh báo"></a>'
            )

        video_html = ""
        if ctx.is_safe_alert_media_path(video_path) and os.path.exists(ctx.absolute_from_base(video_path)):
            video_url = dashboard_media_url(video_path)
            video_html = (
                '<video controls preload="metadata">'
                f'<source src="{video_url}" type="video/mp4">'
                "Trình duyệt không phát được video này."
                "</video>"
                f'<a class="media-link" href="{video_url}" target="_blank">Mở/tải video</a>'
            )

        cards.append(
            '<article class="history-card">'
            '<div class="history-meta">'
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


def selected_attr(current_value, option_value):
    return " selected" if current_value == option_value else ""


def render_dashboard_settings_form(ctx, settings_snapshot):
    numeric_fields = (
        "motion_area_threshold",
        "alert_cooldown_seconds",
        "alert_video_seconds",
        "alert_video_fps"
    )
    rows = []
    for field in numeric_fields:
        min_value, max_value = ctx.settings_limits[field]
        rows.append(
            "<tr>"
            f'<th><label for="setting_{field}">{escape_html(ctx.setting_labels[field])}</label></th>'
            "<td>"
            f'<input id="setting_{field}" name="{field}" type="number" '
            f'value="{settings_snapshot[field]}" min="{min_value}" max="{max_value}" step="1">'
            f'<span class="setting-hint">{min_value}-{max_value}{escape_html(ctx.setting_units[field])}</span>'
            "</td>"
            "</tr>"
        )

    history_options = "".join(
        f'<option value="{choice}"{selected_attr(settings_snapshot["alert_history_limit"], choice)}>{choice} cảnh báo</option>'
        for choice in ctx.history_limit_choices
    )
    rows.append(
        "<tr>"
        f'<th><label for="setting_alert_history_limit">{escape_html(ctx.setting_labels["alert_history_limit"])}</label></th>'
        "<td>"
        f'<select id="setting_alert_history_limit" name="alert_history_limit">{history_options}</select>'
        '<span class="setting-hint">Khi giảm số lượng, bot xóa record cũ và media tương ứng.</span>'
        "</td>"
        "</tr>"
    )

    for field, label in (
        ("send_video", "Gửi video cảnh báo"),
        ("use_gemini_analysis", "Phân tích Gemini")
    ):
        rows.append(
            "<tr>"
            f'<th><label for="setting_{field}">{escape_html(label)}</label></th>'
            "<td>"
            f'<select id="setting_{field}" name="{field}">'
            f'<option value="true"{selected_attr(settings_snapshot[field], True)}>BẬT</option>'
            f'<option value="false"{selected_attr(settings_snapshot[field], False)}>TẮT</option>'
            "</select>"
            "</td>"
            "</tr>"
        )

    return (
        '<form class="settings-form" method="post" action="/update-settings">'
        f"<table>{''.join(rows)}</table>"
        '<button class="save-button" type="submit">Lưu setting</button>'
        '<p class="setting-note">Setting được lưu vào settings.json và vẫn còn sau khi restart bot.</p>'
        "</form>"
    )


def backup_label_text(label):
    labels = {
        "settings": "Setting",
        "alert_history": "Lịch sử",
    }
    return labels.get(str(label), str(label).replace("_", " "))


def backup_detail_title(backup):
    return (
        f"{backup_label_text(backup.get('label', 'unknown'))} - "
        f"{backup.get('filename', '')}"
    )


def find_dashboard_backup(backups, filename):
    if not filename:
        return None
    for backup in backups:
        if backup.get("filename") == filename:
            return backup
    return None


def load_dashboard_backup_json(ctx, backup):
    backup_path = backup.get("path")
    if not backup_path or not os.path.isfile(backup_path):
        return None, "File backup không còn tồn tại."

    try:
        with open(backup_path, "r", encoding="utf-8") as file:
            return json.load(file), ""
    except (OSError, json.JSONDecodeError) as e:
        ctx.log_error(f"Dashboard khong doc duoc backup: {backup_path}", e)
        return None, "Không đọc được nội dung backup. Xem tab Log lỗi để biết chi tiết."


def get_dashboard_backup_file(ctx, filename):
    backup = find_dashboard_backup(ctx.list_backups(limit=20), filename)
    if backup is None:
        return None

    backup_path = backup.get("path")
    if not backup_path or not os.path.isfile(backup_path):
        return None
    if os.path.basename(os.path.abspath(backup_path)) != backup.get("filename"):
        return None
    if not str(backup.get("filename", "")).endswith(".json"):
        return None
    return backup


def render_settings_backup_detail(ctx, data):
    if not isinstance(data, dict):
        return '<p class="empty">Backup setting không đúng định dạng.</p>'

    labels = {
        **ctx.setting_labels,
        "send_video": "Gửi video cảnh báo",
        "use_gemini_analysis": "Phân tích Gemini",
    }
    ordered_keys = [
        "motion_area_threshold",
        "alert_cooldown_seconds",
        "alert_video_seconds",
        "alert_video_fps",
        "send_video",
        "use_gemini_analysis",
        "alert_history_limit",
    ]
    extra_keys = sorted(key for key in data if key not in ordered_keys)
    rows = []
    for key in ordered_keys + extra_keys:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, bool):
            value = "BẬT" if value else "TẮT"
        rows.append(
            "<tr>"
            f"<th>{escape_html(labels.get(key, key))}</th>"
            f"<td>{escape_html(value)}</td>"
            "</tr>"
        )

    if not rows:
        return '<p class="empty">Backup setting không có giá trị nào.</p>'
    return f"<table>{''.join(rows)}</table>"


def render_history_backup_detail(ctx, data):
    if not isinstance(data, list):
        return '<p class="empty">Backup lịch sử không đúng định dạng.</p>'

    entries = [entry for entry in data if isinstance(entry, dict)]
    if entries:
        latest_timestamp = max(alert_timestamp_value(entry) for entry in entries)
        latest_text = ctx.format_timestamp(latest_timestamp) if latest_timestamp else "Không có timestamp"
    else:
        latest_text = "Không có cảnh báo"

    rows = []
    for entry in entries[:5]:
        rows.append(
            "<tr>"
            f"<td>{escape_html(ctx.format_timestamp(entry.get('timestamp')))}</td>"
            f"<td>{escape_html(entry.get('video_status') or 'Không có video')}</td>"
            f"<td>{escape_html(ctx.text_preview(entry.get('analysis'), max_length=180))}</td>"
            "</tr>"
        )

    preview_table = '<p class="empty">Backup không có cảnh báo nào.</p>'
    if rows:
        preview_table = (
            "<table>"
            "<thead><tr><th>Thời gian</th><th>Video</th><th>Gemini</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )

    return (
        '<div class="backup-summary">'
        f"<p><strong>Số cảnh báo:</strong> {len(entries)}</p>"
        f"<p><strong>Cảnh báo gần nhất:</strong> {escape_html(latest_text)}</p>"
        "</div>"
        f"{preview_table}"
    )


def render_generic_backup_detail(data):
    compact = json.dumps(data, ensure_ascii=False, indent=2)
    if len(compact) > 4000:
        compact = f"{compact[:4000]}\n..."
    return f"<pre>{escape_html(compact)}</pre>"


def restore_selected_dashboard_backup(ctx, filename):
    backup = find_dashboard_backup(ctx.list_backups(limit=20), filename)
    if backup is None:
        return {
            "status": "0",
            "kind": "unknown",
            "count": "0",
        }

    label = backup.get("label")
    if label == "settings":
        ctx.restore_settings_backup(backup)
        return {
            "status": "1",
            "kind": "settings",
            "count": "0",
        }

    if label == "alert_history":
        restored = ctx.restore_alert_history_backup(backup)
        return {
            "status": "1",
            "kind": "history",
            "count": str(restored.get("restored_count", 0)),
        }

    return {
        "status": "unsupported",
        "kind": str(label or "unknown"),
        "count": "0",
    }


def delete_selected_dashboard_backup(ctx, filename):
    backup = find_dashboard_backup(ctx.list_backups(limit=20), filename)
    if backup is None:
        return False
    return ctx.delete_backup(backup)


def render_dashboard_backup_detail(ctx, backups, selected_filename):
    if not selected_filename:
        return ""

    backup = find_dashboard_backup(backups, selected_filename)
    if backup is None:
        return (
            '<section class="backup-detail">'
            "<h3>Nội dung backup</h3>"
            '<p class="empty">Không tìm thấy backup trong danh sách hiện tại.</p>'
            "</section>"
        )

    data, error = load_dashboard_backup_json(ctx, backup)
    if error:
        detail_html = f'<p class="empty">{escape_html(error)}</p>'
    elif backup.get("label") == "settings":
        detail_html = render_settings_backup_detail(ctx, data)
    elif backup.get("label") == "alert_history":
        detail_html = render_history_backup_detail(ctx, data)
    else:
        detail_html = render_generic_backup_detail(data)

    return (
        '<section class="backup-detail">'
        f"<h3>Nội dung backup: {escape_html(backup_detail_title(backup))}</h3>"
        f"{detail_html}"
        "</section>"
    )


def render_dashboard_backup_actions():
    return """
    <div class="backup-actions">
      <form method="post" action="/restore-settings-backup" onsubmit="return confirm('Khôi phục setting từ backup gần nhất? Setting hiện tại sẽ được backup trước khi ghi đè.')">
        <button class="save-button" type="submit">Khôi phục setting gần nhất</button>
      </form>
      <form method="post" action="/restore-history-backup" onsubmit="return confirm('Khôi phục lịch sử từ backup gần nhất? Lịch sử hiện tại sẽ được backup trước khi ghi đè.')">
        <button class="secondary-button" type="submit">Khôi phục lịch sử gần nhất</button>
      </form>
    </div>
    """


def render_selected_backup_restore_form(backup, active_filter="all"):
    filename = backup.get("filename", "")
    label = backup.get("label")
    if not filename or label not in ("settings", "alert_history"):
        return ""

    button_label = "Khôi phục file này"
    confirm_text = "Khôi phục backup này? Trạng thái hiện tại sẽ được backup trước khi ghi đè."
    active_filter = normalize_dashboard_backup_filter(active_filter)
    return (
        '<form class="inline-form" method="post" action="/restore-selected-backup" '
        f'onsubmit="return confirm(\'{escape_html(confirm_text)}\')">'
        f'<input type="hidden" name="filename" value="{escape_html(filename)}">'
        f'<input type="hidden" name="backup_filter" value="{escape_html(active_filter)}">'
        f'<button class="table-action-button" type="submit">{escape_html(button_label)}</button>'
        "</form>"
    )


def render_selected_backup_delete_form(backup, active_filter="all"):
    filename = backup.get("filename", "")
    if not filename:
        return ""

    confirm_text = "Xóa backup này? Thao tác này chỉ xóa file JSON backup đã chọn."
    active_filter = normalize_dashboard_backup_filter(active_filter)
    return (
        '<form class="inline-form" method="post" action="/delete-backup" '
        f'onsubmit="return confirm(\'{escape_html(confirm_text)}\')">'
        f'<input type="hidden" name="filename" value="{escape_html(filename)}">'
        f'<input type="hidden" name="backup_filter" value="{escape_html(active_filter)}">'
        '<button class="delete-button" type="submit">Xóa</button>'
        "</form>"
    )


def render_selected_backup_download_link(backup):
    filename = backup.get("filename", "")
    if not filename:
        return ""
    return (
        f'<a class="media-link" href="{dashboard_backup_download_url(filename)}">'
        "Tải xuống</a>"
    )


def render_dashboard_backups(ctx, backups, selected_filename="", active_filter="all"):
    actions = render_dashboard_backup_actions()
    filtered_backups = filter_dashboard_backups(backups, active_filter)
    filter_controls = render_dashboard_backup_filter_controls(
        active_filter,
        len(filtered_backups),
        len(backups)
    )

    if not filtered_backups:
        empty_text = (
            "Chưa có backup nào trong logs/backups."
            if not backups else
            "Không có backup nào theo bộ lọc này."
        )
        return (
            f"{actions}"
            f"{filter_controls}"
            f'<section class="empty">{empty_text}</section>'
        )

    detail_html = render_dashboard_backup_detail(ctx, filtered_backups, selected_filename)
    rows = []
    for backup in filtered_backups:
        filename = backup.get("filename", "")
        detail_link = (
            f'<a class="media-link" href="{dashboard_backup_detail_url(filename, active_filter)}">Xem nội dung</a>'
            if filename else ""
        )
        restore_form = render_selected_backup_restore_form(backup, active_filter)
        delete_form = render_selected_backup_delete_form(backup, active_filter)
        download_link = render_selected_backup_download_link(backup)
        rows.append(
            "<tr>"
            f"<td>{escape_html(backup_label_text(backup.get('label', 'unknown')))}</td>"
            f"<td>{escape_html(str(backup.get('reason', 'unknown')).replace('_', ' '))}</td>"
            f"<td>{escape_html(ctx.format_timestamp(backup.get('created_at')))}</td>"
            f"<td>{escape_html(ctx.format_size(backup.get('size', 0)))}</td>"
            f"<td><code>{escape_html(filename)}</code></td>"
            f"<td>{detail_link}</td>"
            f"<td>{download_link}</td>"
            f"<td>{restore_form}</td>"
            f"<td>{delete_form}</td>"
            "</tr>"
        )

    return (
        f"{actions}"
        f"{filter_controls}"
        f"{detail_html}"
        '<p class="setting-note">Backup chỉ lưu file JSON cấu hình/lịch sử. Ảnh và video cảnh báo không được copy vào backup.</p>'
        '<div class="table-scroll">'
        "<table>"
        "<thead><tr><th>Loại</th><th>Lý do</th><th>Thời gian</th><th>Dung lượng</th><th>File</th><th>Nội dung</th><th>Tải</th><th>Khôi phục</th><th>Xóa</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
    )


def bool_from_dashboard(value, default):
    if value is None:
        return default
    return str(value).strip().lower() in ("true", "1", "yes", "on", "bat", "bật")


def update_dashboard_settings(ctx, form):
    updates = {}
    current = ctx.get_settings_snapshot()

    for field, (min_value, max_value) in ctx.settings_limits.items():
        raw_value = form.get(field, [current[field]])[0]
        value = ctx.clamp_int(raw_value, current[field], min_value, max_value)
        if field == "alert_history_limit" and value not in ctx.history_limit_choices:
            value = min(ctx.history_limit_choices, key=lambda choice: abs(choice - value))
        updates[field] = value

    updates["send_video"] = bool_from_dashboard(
        form.get("send_video", [current["send_video"]])[0],
        current["send_video"]
    )
    updates["use_gemini_analysis"] = bool_from_dashboard(
        form.get("use_gemini_analysis", [current["use_gemini_analysis"]])[0],
        current["use_gemini_analysis"]
    )

    for field, value in updates.items():
        ctx.update_setting(field, value)

    if updates["alert_history_limit"] != current["alert_history_limit"]:
        ctx.trim_alert_history(updates["alert_history_limit"])


def render_dashboard_html(
    ctx,
    notice="",
    history_filter="all",
    active_tab="status",
    backup_filename="",
    backup_filter="all"
):
    active_tab = normalize_dashboard_tab(active_tab)
    history_filter = normalize_dashboard_history_filter(history_filter)
    backup_filter = normalize_dashboard_backup_filter(backup_filter)
    settings_snapshot = ctx.get_settings_snapshot()
    all_history_entries = ctx.get_alert_history_snapshot(settings_snapshot["alert_history_limit"])
    history_entries = filter_dashboard_history(ctx, all_history_entries, history_filter)
    filter_controls = render_dashboard_filter_controls(
        history_filter,
        len(history_entries),
        len(all_history_entries)
    )
    camera_ok, camera_status = ctx.get_camera_status()
    radar_status = "BẬT" if ctx.is_radar_active() else "TẮT"
    logs_size = ctx.format_size(ctx.get_directory_size(ctx.log_dir))
    uptime = ctx.format_duration(time.time() - ctx.bot_start_time)
    error_log = escape_html(ctx.tail_error_log())
    settings_form = render_dashboard_settings_form(ctx, settings_snapshot)
    backups = ctx.list_backups(limit=20)
    backups_content = render_dashboard_backups(ctx, backups, backup_filename, backup_filter)

    notice_html = ""
    if notice:
        notice_html = f'<section class="notice">{escape_html(notice)}</section>'

    camera_class = "ok" if camera_ok else "bad"
    tabs_html = render_dashboard_tabs(active_tab, history_filter, backup_filter)
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
        <tr><th>Cảnh báo gần nhất</th><td>{escape_html(ctx.format_timestamp(ctx.last_alert_timestamp()))}</td></tr>
        <tr><th>Dashboard local</th><td>{escape_html(ctx.url)}</td></tr>
      </table>
    </section>"""
    history_content = f"""
    <section class="tab-panel">
      <h2>Lịch sử cảnh báo</h2>
      {render_dashboard_history_actions()}
      {filter_controls}
      <section class="history">{render_dashboard_history(ctx, history_entries, history_filter)}</section>
    </section>"""
    settings_content = f"""
    <section class="panel tab-panel">
      <h2>Setting</h2>
      {settings_form}
    </section>"""
    backups_content = f"""
    <section class="panel tab-panel">
      <h2>Backup</h2>
      {backups_content}
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
        "backups": backups_content,
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
    .history-actions {{ display: flex; justify-content: flex-end; margin-bottom: 12px; }}
    .download-button {{ display: inline-block; border: 0; border-radius: 6px; background: var(--accent); color: #fff; font-weight: 700; padding: 9px 13px; text-decoration: none; }}
    .filter-bar {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 0 0 12px; flex-wrap: wrap; }}
    .filter-links {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .filter-link {{ border: 1px solid var(--line); border-radius: 999px; color: var(--text); padding: 6px 10px; text-decoration: none; }}
    .filter-link.active {{ background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 700; }}
    .filter-count {{ color: var(--muted); }}
    .settings-form input, .settings-form select {{ width: min(260px, 100%); padding: 8px 9px; border: 1px solid var(--line); border-radius: 6px; background: transparent; color: var(--text); font: inherit; }}
    .setting-hint {{ display: block; margin-top: 5px; color: var(--muted); font-size: 12px; }}
    .setting-note {{ color: var(--muted); margin: 12px 0 0; }}
    .save-button {{ margin-top: 12px; border: 0; border-radius: 6px; background: var(--accent); color: #fff; cursor: pointer; font: inherit; font-weight: 700; padding: 9px 13px; }}
    .secondary-button {{ margin-top: 12px; border: 1px solid var(--line); border-radius: 6px; background: transparent; color: var(--text); cursor: pointer; font: inherit; font-weight: 700; padding: 9px 13px; }}
    .backup-actions {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 12px; }}
    .backup-actions form {{ margin: 0; }}
    .backup-actions .save-button, .backup-actions .secondary-button {{ margin-top: 0; }}
    .backup-detail {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; margin: 12px 0; }}
    .backup-detail h3 {{ font-size: 15px; margin: 0 0 10px; }}
    .backup-summary {{ display: flex; flex-wrap: wrap; gap: 14px; color: var(--muted); }}
    .backup-summary p {{ margin: 0 0 8px; }}
    .table-scroll {{ overflow-x: auto; }}
    code {{ font: 12px/1.4 ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; overflow-wrap: anywhere; }}
    .inline-form {{ margin: 0; }}
    .table-action-button {{ border: 1px solid var(--line); border-radius: 6px; background: transparent; color: var(--accent); cursor: pointer; font: inherit; font-weight: 700; padding: 5px 9px; white-space: nowrap; }}
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
    <div class="muted">Chỉ mở trên máy tính này: {escape_html(ctx.url)} · Tự refresh mỗi 30 giây</div>
    {tabs_html}
  </header>
  <main>
    {notice_html}
    {tab_content}
  </main>
</body>
</html>"""


def is_dashboard_history_export_file(filename):
    lower_name = filename.lower()
    if lower_name in HISTORY_EXPORT_FILENAMES:
        return True
    extension = os.path.splitext(lower_name)[1]
    return lower_name.startswith("alert_") and extension in HISTORY_EXPORT_MEDIA_EXTENSIONS


def get_dashboard_history_export_files(ctx):
    log_dir = os.path.abspath(ctx.log_dir)
    if not os.path.isdir(log_dir):
        return []

    files = []
    try:
        filenames = os.listdir(log_dir)
    except OSError as e:
        ctx.log_error(f"Dashboard khong doc duoc thu muc logs: {log_dir}", e)
        return []

    for filename in filenames:
        absolute_path = os.path.abspath(os.path.join(log_dir, filename))
        try:
            if os.path.commonpath([log_dir, absolute_path]) != log_dir:
                continue
        except ValueError:
            continue
        if not os.path.isfile(absolute_path):
            continue
        if not is_dashboard_history_export_file(filename):
            continue
        files.append((absolute_path, f"logs/{filename}"))

    return sorted(files, key=lambda item: item[1].lower())


def build_dashboard_history_zip(ctx):
    export_files = get_dashboard_history_export_files(ctx)
    temp_file = tempfile.NamedTemporaryFile(prefix="vision_bot_history_", suffix=".zip", delete=False)
    temp_path = temp_file.name
    temp_file.close()

    written_count = 0
    with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for absolute_path, archive_name in export_files:
            try:
                zip_file.write(absolute_path, archive_name)
                written_count += 1
            except OSError as e:
                ctx.log_error(f"Dashboard khong them duoc file vao zip: {absolute_path}", e)
        if written_count == 0:
            zip_file.writestr("README.txt", "Khong co file lich su canh bao trong logs/.\n")

    return temp_path, written_count


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


def send_dashboard_file(handler, absolute_path, content_type, download_filename=""):
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
    if download_filename:
        handler.send_header("Content-Disposition", f'attachment; filename="{download_filename}"')
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


def serve_dashboard_media(ctx, handler, query):
    media_path = query.get("path", [""])[0]
    if not ctx.is_safe_alert_media_path(media_path):
        handler.send_error(403)
        return

    absolute_path = os.path.abspath(ctx.absolute_from_base(media_path))
    if not os.path.isfile(absolute_path):
        handler.send_error(404)
        return

    try:
        content_type = mimetypes.guess_type(absolute_path)[0] or "application/octet-stream"
        send_dashboard_file(handler, absolute_path, content_type)
    except OSError as e:
        ctx.log_error(f"Khong doc duoc media dashboard: {absolute_path}", e)
        handler.send_error(404)


def serve_dashboard_backup_download(ctx, handler, query):
    filename = query.get("filename", [""])[0]
    backup = get_dashboard_backup_file(ctx, filename)
    if backup is None:
        handler.send_error(404)
        return

    absolute_path = os.path.abspath(backup["path"])
    try:
        with open(absolute_path, "rb") as file:
            content = file.read()
    except OSError as e:
        ctx.log_error(f"Dashboard khong tai duoc backup: {absolute_path}", e)
        handler.send_error(404)
        return

    safe_filename = os.path.basename(backup["filename"])
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Disposition", f'attachment; filename="{safe_filename}"')
    handler.send_header("Content-Length", str(len(content)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(content)


def serve_dashboard_history_zip(ctx, handler):
    zip_path = ""
    try:
        zip_path, _ = build_dashboard_history_zip(ctx)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        download_filename = f"vision_bot_history_{timestamp}.zip"
        send_dashboard_file(handler, zip_path, "application/zip", download_filename)
    except (ConnectionError, TimeoutError):
        return
    except OSError as e:
        ctx.log_error("Dashboard khong tao duoc file zip lich su", e)
        handler.send_error(500)
    finally:
        if zip_path:
            try:
                os.remove(zip_path)
            except OSError:
                pass


def redirect_dashboard(handler, location):
    handler.send_response(303)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def make_dashboard_handler(ctx):
    class DashboardRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed_url = urlparse(self.path)
            if parsed_url.path in ("/", "/index.html"):
                query = parse_qs(parsed_url.query)
                active_tab = normalize_dashboard_tab(query.get("tab", ["status"])[0])
                history_filter = normalize_dashboard_history_filter(query.get("filter", ["all"])[0])
                backup_filter = normalize_dashboard_backup_filter(query.get("backup_filter", ["all"])[0])
                backup_filename = query.get("backup", [""])[0]
                notice = ""
                if query.get("deleted") == ["1"]:
                    notice = "Đã xóa cảnh báo."
                elif query.get("deleted") == ["0"]:
                    notice = "Không tìm thấy cảnh báo để xóa."
                elif query.get("saved") == ["1"]:
                    notice = "Đã lưu setting."
                elif query.get("restore_settings") == ["1"]:
                    notice = "Đã khôi phục setting từ backup gần nhất."
                elif query.get("restore_settings") == ["0"]:
                    notice = "Chưa có backup setting để khôi phục."
                elif query.get("restore_settings") == ["error"]:
                    notice = "Không thể khôi phục setting. Xem tab Log lỗi để biết chi tiết."
                elif query.get("restore_history") == ["1"]:
                    count = query.get("count", ["0"])[0]
                    notice = f"Đã khôi phục {count} cảnh báo từ backup lịch sử gần nhất."
                elif query.get("restore_history") == ["0"]:
                    notice = "Chưa có backup lịch sử để khôi phục."
                elif query.get("restore_history") == ["error"]:
                    notice = "Không thể khôi phục lịch sử. Xem tab Log lỗi để biết chi tiết."
                elif query.get("restore_selected") == ["1"]:
                    kind = query.get("kind", ["unknown"])[0]
                    if kind == "settings":
                        notice = "Đã khôi phục setting từ backup đã chọn."
                    elif kind == "history":
                        count = query.get("count", ["0"])[0]
                        notice = f"Đã khôi phục {count} cảnh báo từ backup lịch sử đã chọn."
                    else:
                        notice = "Đã khôi phục backup đã chọn."
                elif query.get("restore_selected") == ["0"]:
                    notice = "Không tìm thấy backup đã chọn trong danh sách hiện tại."
                elif query.get("restore_selected") == ["unsupported"]:
                    notice = "Loại backup này chưa hỗ trợ khôi phục từ dashboard."
                elif query.get("restore_selected") == ["error"]:
                    notice = "Không thể khôi phục backup đã chọn. Xem tab Log lỗi để biết chi tiết."
                elif query.get("deleted_backup") == ["1"]:
                    notice = "Đã xóa backup đã chọn."
                elif query.get("deleted_backup") == ["0"]:
                    notice = "Không tìm thấy backup đã chọn để xóa."
                elif query.get("deleted_backup") == ["error"]:
                    notice = "Không thể xóa backup đã chọn. Xem tab Log lỗi để biết chi tiết."

                body = render_dashboard_html(
                    ctx,
                    notice,
                    history_filter,
                    active_tab,
                    backup_filename,
                    backup_filter
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed_url.path == "/media":
                serve_dashboard_media(ctx, self, parse_qs(parsed_url.query))
                return

            if parsed_url.path == "/download-backup":
                serve_dashboard_backup_download(ctx, self, parse_qs(parsed_url.query))
                return

            if parsed_url.path == "/download-history-zip":
                serve_dashboard_history_zip(ctx, self)
                return

            self.send_error(404)

        def do_POST(self):
            parsed_url = urlparse(self.path)
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                content_length = 0

            body = self.rfile.read(min(content_length, 4096)).decode("utf-8", errors="replace")
            form = parse_qs(body)

            if parsed_url.path == "/update-settings":
                update_dashboard_settings(ctx, form)
                redirect_dashboard(self, "/?" + urlencode({"tab": "settings", "saved": "1"}))
                return

            if parsed_url.path == "/restore-settings-backup":
                try:
                    restored = ctx.restore_latest_settings_backup()
                    status = "1" if restored is not None else "0"
                except Exception as e:
                    ctx.log_error("Dashboard khoi phuc setting that bai", e)
                    status = "error"
                redirect_dashboard(self, "/?" + urlencode({"tab": "backups", "restore_settings": status}))
                return

            if parsed_url.path == "/restore-history-backup":
                count = "0"
                try:
                    restored = ctx.restore_latest_alert_history_backup()
                    status = "1" if restored is not None else "0"
                    if restored is not None:
                        count = str(restored.get("restored_count", 0))
                except Exception as e:
                    ctx.log_error("Dashboard khoi phuc lich su canh bao that bai", e)
                    status = "error"
                redirect_dashboard(
                    self,
                    "/?" + urlencode({"tab": "backups", "restore_history": status, "count": count})
                )
                return

            if parsed_url.path == "/restore-selected-backup":
                filename = form.get("filename", [""])[0]
                backup_filter = normalize_dashboard_backup_filter(form.get("backup_filter", ["all"])[0])
                try:
                    restored = restore_selected_dashboard_backup(ctx, filename)
                except Exception as e:
                    ctx.log_error("Dashboard khoi phuc backup da chon that bai", e)
                    restored = {
                        "status": "error",
                        "kind": "unknown",
                        "count": "0",
                    }
                redirect_dashboard(
                    self,
                    "/?" + urlencode({
                        "tab": "backups",
                        "backup_filter": backup_filter,
                        "backup": filename,
                        "restore_selected": restored["status"],
                        "kind": restored["kind"],
                        "count": restored["count"],
                    })
                )
                return

            if parsed_url.path == "/delete-backup":
                filename = form.get("filename", [""])[0]
                backup_filter = normalize_dashboard_backup_filter(form.get("backup_filter", ["all"])[0])
                try:
                    deleted = delete_selected_dashboard_backup(ctx, filename)
                    status = "1" if deleted else "0"
                except Exception as e:
                    ctx.log_error("Dashboard xoa backup that bai", e)
                    status = "error"
                redirect_dashboard(
                    self,
                    "/?" + urlencode({
                        "tab": "backups",
                        "backup_filter": backup_filter,
                        "deleted_backup": status
                    })
                )
                return

            if parsed_url.path != "/delete-alert":
                self.send_error(404)
                return

            alert_id = form.get("id", [""])[0]
            history_filter = normalize_dashboard_history_filter(form.get("filter", ["all"])[0])
            deleted = ctx.delete_alert_history_entry(alert_id)
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

    return DashboardRequestHandler


def start_dashboard_server(ctx):
    try:
        server = ThreadingHTTPServer((ctx.host, ctx.port), make_dashboard_handler(ctx))
    except OSError as e:
        ctx.log_error(f"Khong khoi dong duoc dashboard local tai {ctx.url}", e)
        return

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Dashboard local dang chay tai {ctx.url}")
