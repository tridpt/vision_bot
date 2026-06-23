import os
import tempfile
import unittest

from vision_bot_core.cloudflared_tunnel import CloudflaredTunnel, extract_trycloudflare_url


class ExtractTryCloudflareUrlTests(unittest.TestCase):
    def test_extracts_url_from_log_line(self):
        line = "2024-01-01 INF |  https://random-words-1234.trycloudflare.com  |"
        self.assertEqual(
            extract_trycloudflare_url(line),
            "https://random-words-1234.trycloudflare.com",
        )

    def test_returns_none_when_no_url(self):
        self.assertIsNone(extract_trycloudflare_url("Starting tunnel..."))

    def test_returns_none_for_empty_input(self):
        self.assertIsNone(extract_trycloudflare_url(""))
        self.assertIsNone(extract_trycloudflare_url(None))

    def test_ignores_non_trycloudflare_https_urls(self):
        self.assertIsNone(extract_trycloudflare_url("https://example.com/path"))


class CloudflaredTunnelTests(unittest.TestCase):
    def test_get_url_is_none_before_start(self):
        tunnel = CloudflaredTunnel(8765)
        self.assertIsNone(tunnel.get_url())

    def test_download_if_needed_skips_when_exe_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tunnel = CloudflaredTunnel(8765)
            tunnel.bin_dir = temp_dir
            tunnel.exe_path = os.path.join(temp_dir, "cloudflared.exe")
            with open(tunnel.exe_path, "wb") as file:
                file.write(b"fake-binary")

            # Không có file thật để tải; nếu hàm cố tải sẽ thất bại. Vì exe đã tồn tại
            # nên nó phải trả True ngay mà không truy cập mạng.
            self.assertTrue(tunnel.download_if_needed())

    def test_logger_is_used_when_provided(self):
        messages = []
        tunnel = CloudflaredTunnel(8765, logger=lambda msg, error=None: messages.append(msg))
        tunnel._log("hello", None)
        self.assertEqual(messages, ["hello"])


if __name__ == "__main__":
    unittest.main()
