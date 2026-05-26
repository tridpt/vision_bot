import os
import time

import cv2


def open_camera(camera_index=0):
    return cv2.VideoCapture(camera_index)


def read_camera_frame(camera_index=0, warmup_seconds=0):
    camera = None
    try:
        camera = open_camera(camera_index)
        if warmup_seconds > 0:
            time.sleep(warmup_seconds)
        success, frame = camera.read()
        if not success:
            return False, None
        return True, frame
    finally:
        if camera is not None:
            camera.release()


def check_camera_once(camera_index=0):
    camera = open_camera(camera_index)
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
