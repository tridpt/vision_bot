import os
import subprocess
import threading
import urllib.request
import re

CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

TRYCLOUDFLARE_URL_PATTERN = re.compile(r'https://[-0-9a-z]+\.trycloudflare\.com')


def extract_trycloudflare_url(text):
    if not text:
        return None
    match = TRYCLOUDFLARE_URL_PATTERN.search(text)
    if match:
        return match.group(0)
    return None


class CloudflaredTunnel:
    def __init__(self, port, logger=None):
        self.port = port
        self.logger = logger
        self.process = None
        self.public_url = None
        self.thread = None
        self.bin_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bin")
        self.exe_path = os.path.join(self.bin_dir, "cloudflared.exe")

    def _log(self, msg, error=None):
        if self.logger:
            self.logger(msg, error)
        else:
            print(f"[Cloudflared] {msg}")

    def download_if_needed(self):
        if not os.path.exists(self.exe_path):
            os.makedirs(self.bin_dir, exist_ok=True)
            self._log("Dang tai cloudflared.exe tu GitHub...")
            try:
                urllib.request.urlretrieve(CLOUDFLARED_URL, self.exe_path)
                self._log("Tai cloudflared.exe thanh cong.")
            except Exception as e:
                self._log("Khong the tai cloudflared.exe", e)
                return False
        return True

    def start(self):
        if not self.download_if_needed():
            return
        
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        command = [self.exe_path, "tunnel", "--url", f"http://127.0.0.1:{self.port}"]
        try:
            creationflags = 0
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NO_WINDOW
                
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creationflags
            )
            
            for line in self.process.stderr:
                public_url = extract_trycloudflare_url(line)
                if public_url:
                    self.public_url = public_url
                    self._log(f"Public URL: {self.public_url}")
                    break
        except Exception as e:
            self._log("Loi khi chay cloudflared", e)

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def get_url(self):
        return self.public_url
