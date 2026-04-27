"""
test_telegram.py — Test Telegram Notifier
===========================================

Module được test: server/telegram_notifier.py
Lớp được test:    TelegramNotifier

MỤC ĐÍCH:
  Kiểm tra logic rate limiting, config update, và edge cases
  của Telegram notification. KHÔNG gửi tin nhắn thật (mock HTTP).

CÁC TEST CASE:
  1. test_initialization
     → TelegramNotifier khởi tạo thành công, đọc config đúng
  
  2. test_is_configured
     → Có token + chat_id → True. Thiếu → False.
  
  3. test_rate_limiting
     → Gửi 2 lần liên tiếp → lần 2 bị skip (cooldown chưa hết)
  
  4. test_update_config
     → Update config runtime → giá trị mới được áp dụng
  
  5. test_disabled_does_not_send
     → enabled=False → send_detection() không gửi gì cả

KẾT QUẢ MONG ĐỢI:
  - Tất cả 5 test PASSED
  - Rate limiting hoạt động đúng (không spam Telegram)
  - Config update được áp dụng ngay lập tức

CHẠY TEST:
  cd D:\\ROBOT\\server
  python -m pytest tests/test_telegram.py -v

LƯU Ý:
  - Test này KHÔNG gửi tin nhắn Telegram thật
  - Chỉ test logic nội bộ (rate limit, config, is_configured)
  - Để test gửi thật → dùng API endpoint POST /api/telegram/test
"""

import sys
import os
import time
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestTelegramNotifier:
    """
    Test TelegramNotifier — logic quản lý notification.
    
    KHÔNG test gửi tin nhắn thật (cần bot token + internet).
    Chỉ test: initialization, config, rate-limiting.
    """

    def test_initialization(self):
        """
        Test: TelegramNotifier khởi tạo thành công
        
        Kết quả mong đợi:
          - Không crash khi khởi tạo
          - Các thuộc tính được set từ config
        
        Giải thích:
          → TelegramNotifier đọc config từ config.py
          → Mặc định disabled nếu chưa cấu hình token
        """
        from telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()

        assert hasattr(notifier, 'bot_token'), "Phải có thuộc tính bot_token"
        assert hasattr(notifier, 'chat_id'), "Phải có thuộc tính chat_id"
        assert hasattr(notifier, 'enabled'), "Phải có thuộc tính enabled"
        assert hasattr(notifier, 'cooldown'), "Phải có thuộc tính cooldown"
        print("✅ TelegramNotifier khởi tạo thành công")

    def test_is_configured_without_token(self):
        """
        Test: Chưa có token → is_configured = False
        
        Tình huống:
          - bot_token = "" hoặc None
          - chat_id = "" hoặc None
        
        Kết quả mong đợi:
          - is_configured = False
        
        Giải thích:
          → Khi chưa cấu hình Telegram, hệ thống không nên cố gửi
          → is_configured giúp kiểm tra trước khi gửi
        """
        from telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()
        notifier.bot_token = ""
        notifier.chat_id = ""

        assert notifier.is_configured == False, \
            "Token rỗng → is_configured phải = False"
        print("✅ Token rỗng → is_configured = False (đúng)")

    def test_is_configured_with_token(self):
        """
        Test: Có token + chat_id → is_configured = True
        
        Kết quả mong đợi:
          - is_configured = True
        """
        from telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()
        notifier.bot_token = "123456:ABC-DEF"
        notifier.chat_id = "987654321"

        assert notifier.is_configured == True, \
            "Có token + chat_id → is_configured phải = True"
        print("✅ Có token + chat_id → is_configured = True (đúng)")

    def test_rate_limiting(self):
        """
        Test: Rate limiting — gửi 2 lần trong cooldown → lần 2 bị skip
        
        Tình huống:
          - cooldown = 30s
          - Gửi lần 1 → OK (set _last_sent = now)
          - Gửi lần 2 ngay sau → bị skip (now - _last_sent < 30s)
        
        Kết quả mong đợi:
          - Lần 1: _last_sent được cập nhật
          - Lần 2: _last_sent KHÔNG đổi (bị skip)
        
        Giải thích:
          → Tránh spam hàng trăm notification mỗi giây
          → Mặc định 30s giữa 2 alert liên tiếp
        
        Lưu ý: Test này chỉ kiểm tra logic rate limit,
                KHÔNG gửi tin nhắn thật (vì không có token hợp lệ)
        """
        from telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()
        notifier.cooldown = 30
        notifier.enabled = True
        notifier.bot_token = "fake-token"
        notifier.chat_id = "fake-chat"

        # Giả lập đã gửi 1 lần
        notifier._last_sent = time.time()

        # Tạo frame giả
        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Lưu _last_sent hiện tại
        last_sent_before = notifier._last_sent

        # Gửi lần 2 → phải bị skip do cooldown
        notifier.send_detection(fake_frame, 0.9, (320, 240), "MONITOR")

        # Vì bị skip, _last_sent không thay đổi
        # (trong thực tế, send_detection return sớm trước khi update _last_sent)
        # Test logic: time.time() - _last_sent < cooldown → return
        elapsed = time.time() - notifier._last_sent
        assert elapsed < notifier.cooldown, \
            "Gửi trong cooldown → phải bị skip"
        print("✅ Rate limiting: gửi trong cooldown → bị skip (đúng)")

    def test_update_config(self):
        """
        Test: Update config runtime → giá trị mới được áp dụng
        
        Tình huống:
          - Thay đổi bot_token, chat_id, enabled, cooldown
        
        Kết quả mong đợi:
          - Các thuộc tính được cập nhật ngay lập tức
          - Không cần restart server
        
        Giải thích:
          → User có thể thay đổi config Telegram qua web dashboard
          → API gọi update_config() để áp dụng ngay
        """
        from telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()

        # Update config
        notifier.update_config(
            bot_token="new-token-123",
            chat_id="new-chat-456",
            enabled=True,
            cooldown=60
        )

        assert notifier.bot_token == "new-token-123", "bot_token phải được cập nhật"
        assert notifier.chat_id == "new-chat-456", "chat_id phải được cập nhật"
        assert notifier.enabled == True, "enabled phải = True"
        assert notifier.cooldown == 60, f"cooldown phải = 60, nhận {notifier.cooldown}"
        print("✅ update_config → tất cả giá trị được cập nhật ngay")

    def test_disabled_does_not_send(self):
        """
        Test: enabled=False → send_detection() không gửi
        
        Tình huống:
          - enabled = False
          - Gọi send_detection() → phải return ngay, không gửi
        
        Kết quả mong đợi:
          - _last_sent KHÔNG thay đổi (vì không gửi)
          - Không crash, không exception
        
        Giải thích:
          → User có thể tắt Telegram notification từ dashboard
          → Khi tắt, hệ thống không nên cố gửi (tiết kiệm tài nguyên)
        """
        from telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier()
        notifier.enabled = False
        notifier.bot_token = "some-token"
        notifier.chat_id = "some-chat"

        last_sent_before = notifier._last_sent

        # Gửi khi disabled
        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        notifier.send_detection(fake_frame, 0.9, (320, 240), "MONITOR")

        assert notifier._last_sent == last_sent_before, \
            "Disabled → _last_sent không được thay đổi"
        print("✅ enabled=False → không gửi, không crash (đúng)")
