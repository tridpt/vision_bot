import tempfile
import unittest
from pathlib import Path

import numpy as np

from vision_bot_core import camera_tools


class CameraToolsTests(unittest.TestCase):
    def test_has_large_motion_detects_changed_area(self):
        base = np.zeros((120, 120, 3), dtype=np.uint8)
        changed = base.copy()
        changed[30:90, 30:90] = 255

        base_gray = camera_tools.build_motion_gray(base)
        changed_gray = camera_tools.build_motion_gray(changed)

        self.assertFalse(camera_tools.has_large_motion(base_gray, base_gray, 500))
        self.assertTrue(camera_tools.has_large_motion(base_gray, changed_gray, 500))

    def test_save_frame_writes_image_file(self):
        frame = np.zeros((24, 24, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "frame.jpg"

            self.assertTrue(camera_tools.save_frame(str(image_path), frame))
            self.assertTrue(image_path.exists())
            self.assertGreater(image_path.stat().st_size, 0)

    def test_transform_camera_frame_rotates_when_configured(self):
        frame = np.array(
            [
                [[1, 0, 0], [2, 0, 0]],
                [[3, 0, 0], [4, 0, 0]],
            ],
            dtype=np.uint8,
        )

        rotated = camera_tools.transform_camera_frame(frame, {"camera_rotation": 180})

        self.assertEqual(rotated.shape, frame.shape)
        self.assertEqual(rotated[0, 0, 0], 4)
        self.assertEqual(rotated[1, 1, 0], 1)

    def test_format_camera_config_uses_defaults(self):
        text = camera_tools.format_camera_config({"camera_index": 2, "camera_rotation": 90})

        self.assertIn("camera 2", text)
        self.assertIn("xoay 90", text)


if __name__ == "__main__":
    unittest.main()
