import os
import time

import cv2


DEFAULT_CAMERA_SCAN_INDICES = range(6)


def normalize_camera_config(camera_config=None, camera_index=0):
    config = camera_config or {}
    return {
        "camera_index": int(config.get("camera_index", camera_index) or 0),
        "camera_width": int(config.get("camera_width", 0) or 0),
        "camera_height": int(config.get("camera_height", 0) or 0),
        "camera_fps": int(config.get("camera_fps", 0) or 0),
        "camera_rotation": int(config.get("camera_rotation", 0) or 0),
    }


def camera_config_with_index(camera_config, camera_index):
    config = normalize_camera_config(camera_config)
    config["camera_index"] = int(camera_index)
    return config


def apply_camera_config(camera, config):
    if config["camera_width"] > 0:
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, config["camera_width"])
    if config["camera_height"] > 0:
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, config["camera_height"])
    if config["camera_fps"] > 0:
        camera.set(cv2.CAP_PROP_FPS, config["camera_fps"])


def open_camera(camera_index=0, camera_config=None):
    config = normalize_camera_config(camera_config, camera_index=camera_index)
    camera = cv2.VideoCapture(config["camera_index"])
    apply_camera_config(camera, config)
    return camera


def transform_camera_frame(frame, camera_config=None):
    rotation = normalize_camera_config(camera_config)["camera_rotation"]
    if rotation == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if rotation == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if rotation == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


def format_camera_config(camera_config=None):
    config = normalize_camera_config(camera_config)
    resolution = "mặc định"
    if config["camera_width"] > 0 and config["camera_height"] > 0:
        resolution = f'{config["camera_width"]}x{config["camera_height"]}'
    fps = "mặc định" if config["camera_fps"] <= 0 else f'{config["camera_fps"]}fps'
    return (
        f'camera {config["camera_index"]}, '
        f'{resolution}, {fps}, xoay {config["camera_rotation"]}°'
    )


def read_camera_frame(camera_index=0, warmup_seconds=0, camera_config=None):
    camera = None
    config = normalize_camera_config(camera_config, camera_index=camera_index)
    try:
        camera = open_camera(camera_config=config)
        if warmup_seconds > 0:
            time.sleep(warmup_seconds)
        success, frame = camera.read()
        if not success:
            return False, None
        return True, transform_camera_frame(frame, config)
    finally:
        if camera is not None:
            camera.release()


def check_camera_once(camera_index=0, camera_config=None):
    config = normalize_camera_config(camera_config, camera_index=camera_index)
    camera = open_camera(camera_config=config)
    try:
        time.sleep(0.5)
        if not camera.isOpened():
            return False, f"Không mở được {format_camera_config(config)}"
        success, frame = camera.read()
        if success:
            transformed = transform_camera_frame(frame, config)
            height, width = transformed.shape[:2]
            return True, f"Mở và đọc được ảnh thử ({format_camera_config(config)}, thực tế {width}x{height})"
        return False, f"Mở được {format_camera_config(config)} nhưng không đọc được ảnh"
    finally:
        camera.release()


def probe_camera(camera_index=0, camera_config=None, warmup_seconds=0.25):
    config = camera_config_with_index(camera_config, camera_index)
    camera = None
    try:
        camera = open_camera(camera_config=config)
        if warmup_seconds > 0:
            time.sleep(warmup_seconds)

        opened = camera.isOpened()
        if not opened:
            return {
                "index": camera_index,
                "opened": False,
                "frame_ok": False,
                "width": 0,
                "height": 0,
                "status": "Không mở được camera",
            }

        success, frame = camera.read()
        if not success:
            return {
                "index": camera_index,
                "opened": True,
                "frame_ok": False,
                "width": 0,
                "height": 0,
                "status": "Mở được nhưng không đọc được ảnh",
            }

        transformed = transform_camera_frame(frame, config)
        height, width = transformed.shape[:2]
        return {
            "index": camera_index,
            "opened": True,
            "frame_ok": True,
            "width": width,
            "height": height,
            "status": f"Đọc được ảnh {width}x{height}",
        }
    except Exception as e:
        return {
            "index": camera_index,
            "opened": False,
            "frame_ok": False,
            "width": 0,
            "height": 0,
            "status": f"Lỗi: {e}",
        }
    finally:
        if camera is not None:
            camera.release()


def scan_camera_indices(indices=DEFAULT_CAMERA_SCAN_INDICES, camera_config=None):
    return [
        probe_camera(camera_index=index, camera_config=camera_config)
        for index in indices
    ]


def format_camera_probe_result(result):
    index = result.get("index")
    if result.get("frame_ok"):
        return f"Cam {index}: OK - {result.get('width')}x{result.get('height')}"
    if result.get("opened"):
        return f"Cam {index}: mở được nhưng không đọc được ảnh"
    return f"Cam {index}: không mở được"


def format_camera_scan_results(results, current_index=None):
    lines = ["🔎 KẾT QUẢ QUÉT CAMERA"]
    working_indices = []
    for result in results:
        if result.get("frame_ok"):
            working_indices.append(str(result.get("index")))
        marker = " ← đang dùng" if result.get("index") == current_index else ""
        lines.append(f"{format_camera_probe_result(result)}{marker}")

    if working_indices:
        lines.append("")
        lines.append(f"Camera dùng được: {', '.join(working_indices)}")
    else:
        lines.append("")
        lines.append("Không tìm thấy camera nào đọc được ảnh.")
    return "\n".join(lines)


def warm_up_camera(camera_stream, delay_seconds=1.5, buffer_reads=5):
    time.sleep(delay_seconds)
    for _ in range(buffer_reads):
        camera_stream.read()


def save_frame(image_path, frame):
    return cv2.imwrite(image_path, frame)


def build_motion_gray(frame):
    return cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (21, 21), 0)


def has_large_motion(previous_gray_frame, current_gray_frame, area_threshold):
    diff = cv2.absdiff(previous_gray_frame, current_gray_frame)
    thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1]
    thresh = cv2.dilate(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return any(cv2.contourArea(contour) > area_threshold for contour in contours)


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


def record_alert_video(camera_stream, first_frame, video_path, duration_seconds, fps, camera_config=None):
    config = normalize_camera_config(camera_config)
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
            frame = transform_camera_frame(frame, config)

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


def record_screen_video(video_path, duration_seconds, fps):
    from PIL import ImageGrab
    import numpy as np

    try:
        first_grab = ImageGrab.grab()
    except Exception as e:
        return False, f"Không chụp được màn hình: {e}"

    first_frame = np.array(first_grab)
    if len(first_frame.shape) == 3 and first_frame.shape[2] == 4:
        first_frame = cv2.cvtColor(first_frame, cv2.COLOR_RGBA2BGR)
    elif len(first_frame.shape) == 3 and first_frame.shape[2] == 3:
        first_frame = cv2.cvtColor(first_frame, cv2.COLOR_RGB2BGR)

    height, width = first_frame.shape[:2]
    width -= width % 2
    height -= height % 2
    frame_size = (width, height)

    writer, codec_label = create_alert_video_writer(video_path, fps, frame_size)
    if writer is None:
        return False, "Không tạo được file video màn hình"

    frames_written = 0
    end_time = time.time() + duration_seconds
    next_frame_time = time.time()

    try:
        while time.time() < end_time:
            img = ImageGrab.grab()
            frame = np.array(img)
            if len(frame.shape) == 3 and frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
            elif len(frame.shape) == 3 and frame.shape[2] == 3:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            writer.write(frame[:height, :width])
            frames_written += 1

            next_frame_time += 1.0 / fps
            delay = next_frame_time - time.time()
            if delay > 0:
                time.sleep(delay)
            else:
                time.sleep(0.01)
    except Exception as e:
        writer.release()
        return False, f"Lỗi khi quay màn hình: {e}"
    finally:
        writer.release()

    if frames_written == 0 or not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return False, "Video màn hình rỗng"

    return True, f"Đã ghi clip màn hình {duration_seconds} giây ({codec_label})"

