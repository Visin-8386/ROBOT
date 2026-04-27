"""
Telegram Notifier — Gửi cảnh báo + hình ảnh qua Telegram Bot
Sử dụng HTTP API trực tiếp (không cần thư viện bên ngoài).
"""

import io
import time
import threading
import requests
import cv2
import numpy as np

import config


class TelegramNotifier:
    """
    Gửi thông báo phát hiện người qua Telegram Bot API.
    Rate-limited theo config.TELEGRAM_COOLDOWN.
    """

    def __init__(self):
        self.bot_token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.enabled = config.TELEGRAM_ENABLED
        self.cooldown = config.TELEGRAM_COOLDOWN
        self._last_sent = 0
        self._lock = threading.Lock()

        if self.enabled and self.bot_token and self.chat_id:
            print(f"[Telegram] Enabled — cooldown {self.cooldown}s")
        else:
            print("[Telegram] Disabled (chưa cấu hình token/chat_id)")

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def update_config(self, bot_token: str = None, chat_id: str = None,
                      enabled: bool = None, cooldown: int = None):
        """Cập nhật cấu hình runtime (từ API/web dashboard)."""
        with self._lock:
            if bot_token is not None:
                self.bot_token = bot_token
                config.TELEGRAM_BOT_TOKEN = bot_token
            if chat_id is not None:
                self.chat_id = chat_id
                config.TELEGRAM_CHAT_ID = chat_id
            if enabled is not None:
                self.enabled = enabled
                config.TELEGRAM_ENABLED = enabled
            if cooldown is not None:
                self.cooldown = cooldown
                config.TELEGRAM_COOLDOWN = cooldown

        status = "ON" if self.enabled else "OFF"
        print(f"[Telegram] Config updated — {status}, cooldown={self.cooldown}s")

    def send_detection(self, frame: np.ndarray, confidence: float,
                       center: tuple, robot_state: str = "UNKNOWN"):
        """
        Gửi cảnh báo phát hiện người kèm hình ảnh.
        Chạy trong thread riêng để không block detection loop.

        Args:
            frame: Frame ảnh BGR (numpy array)
            confidence: Độ tin cậy phát hiện (0-1)
            center: Tọa độ tâm người (x, y)
            robot_state: Trạng thái robot hiện tại (MONITOR/PATROL/CHASE)
        """
        if not self.enabled or not self.is_configured:
            return

        now = time.time()
        with self._lock:
            if (now - self._last_sent) < self.cooldown:
                return  # Rate limit
            self._last_sent = now

        # Gửi trong thread riêng để không block
        t = threading.Thread(
            target=self._send_photo,
            args=(frame.copy(), confidence, center, robot_state),
            daemon=True
        )
        t.start()

    def _send_photo(self, frame: np.ndarray, confidence: float,
                    center: tuple, robot_state: str):
        """Gửi ảnh qua Telegram Bot API (chạy trong thread)."""
        try:
            # Encode frame thành JPEG
            _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            photo_bytes = io.BytesIO(jpeg.tobytes())
            photo_bytes.name = "detection.jpg"

            # Tạo caption
            state_emoji = {
                "MONITOR": "👁️ GIÁM SÁT",
                "PATROL": "🚶 TUẦN TRA",
                "CHASE": "🏃 ĐUỔI THEO",
                "MANUAL": "🎮 THỦ CÔNG",
            }
            state_text = state_emoji.get(robot_state, f"❓ {robot_state}")
            timestamp = time.strftime("%H:%M:%S %d/%m/%Y")

            caption = (
                f"🚨 *PHÁT HIỆN NGƯỜI\\!*\n\n"
                f"📍 Vị trí: `({center[0]}, {center[1]})`\n"
                f"🎯 Độ tin cậy: `{confidence:.1%}`\n"
                f"🤖 Chế độ: {state_text}\n"
                f"🕐 Thời gian: `{timestamp}`"
            )

            url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
            resp = requests.post(
                url,
                data={
                    "chat_id": self.chat_id,
                    "caption": caption,
                    "parse_mode": "MarkdownV2",
                },
                files={"photo": photo_bytes},
                timeout=10,
            )

            if resp.status_code == 200:
                print(f"[Telegram] ✓ Đã gửi cảnh báo ({robot_state})")
            else:
                print(f"[Telegram] ✗ Lỗi: {resp.status_code} — {resp.text[:200]}")

        except Exception as e:
            print(f"[Telegram] ✗ Gửi thất bại: {e}")

    def send_text(self, message: str):
        """Gửi tin nhắn text đơn giản."""
        if not self.enabled or not self.is_configured:
            return

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            resp = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                print(f"[Telegram] ✓ Tin nhắn đã gửi")
            else:
                print(f"[Telegram] ✗ Lỗi: {resp.status_code}")
        except Exception as e:
            print(f"[Telegram] ✗ Gửi thất bại: {e}")

    def test_connection(self) -> dict:
        """Kiểm tra kết nối bot — trả về thông tin bot."""
        if not self.is_configured:
            return {"ok": False, "error": "Token hoặc Chat ID chưa được cấu hình"}

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            resp = requests.get(url, timeout=5)
            data = resp.json()

            if data.get("ok"):
                bot_info = data["result"]
                # Gửi tin nhắn test
                self.send_text(
                    "🤖 <b>Robot Security System</b>\n"
                    "✅ Kết nối Telegram thành công!\n"
                    "Bạn sẽ nhận được thông báo khi phát hiện người."
                )
                return {
                    "ok": True,
                    "bot_name": bot_info.get("first_name"),
                    "bot_username": bot_info.get("username"),
                }
            else:
                return {"ok": False, "error": data.get("description", "Unknown error")}

        except Exception as e:
            return {"ok": False, "error": str(e)}
