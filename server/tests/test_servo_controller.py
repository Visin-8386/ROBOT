"""
test_servo_controller.py — Test bộ điều khiển servo mô phỏng
==============================================================

Module được test: server/servo_controller.py
Lớp được test:    SimulatedServoController

MỤC ĐÍCH:
  Kiểm tra tính toán pan/tilt khi người ở các vị trí khác nhau.
  Servo controller tính sai số giữa vị trí người và tâm frame,
  rồi điều chỉnh góc pan (trái/phải) và tilt (lên/xuống).

CÁC TEST CASE:
  1. test_person_at_center
     → Người ở giữa frame → pan≈0, tilt≈0 (dead zone, không cần quay)
  
  2. test_person_on_right
     → Người bên phải frame → pan > 0 (quay phải)
  
  3. test_person_on_left
     → Người bên trái frame → pan < 0 (quay trái)
  
  4. test_person_on_top
     → Người phía trên frame → tilt > 0 (ngẩng lên)
  
  5. test_is_centered
     → Kiểm tra hàm is_centered() khi người ở giữa / không ở giữa
  
  6. test_reset
     → Reset servo → góc trở về (0, 0)
  
  7. test_angle_limits
     → Góc servo không được vượt quá giới hạn min/max

KẾT QUẢ MONG ĐỢI:
  - Tất cả 7 test PASSED
  - Servo quay đúng hướng theo vị trí người

CHẠY TEST:
  cd D:\\ROBOT\\server
  python -m pytest tests/test_servo_controller.py -v
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestServoController:
    """
    Test SimulatedServoController.
    
    Frame mặc định: 640x480
    Tâm frame: (320, 240)
    Dead zone: ±30px (X), ±20px (Y) theo config
    
    Quy ước:
      - Pan dương = quay phải (người ở bên phải)
      - Pan âm = quay trái (người ở bên trái)
      - Tilt dương = ngẩng lên (người ở trên)
      - Tilt âm = cúi xuống (người ở dưới)
    """

    def _create_controller(self):
        """Helper: Tạo controller 640x480"""
        from servo_controller import SimulatedServoController
        return SimulatedServoController(frame_width=640, frame_height=480)

    def test_person_at_center(self):
        """
        Test: Người ở giữa frame → không cần quay
        
        Đầu vào:
          - person_center = (320, 240) = tâm frame
        
        Kết quả mong đợi:
          - pan_adjustment ≈ 0 (trong dead zone)
          - tilt_adjustment ≈ 0
          - is_centered() = True
        
        Giải thích:
          → Người đã ở giữa camera
          → Servo không cần điều chỉnh
          → Robot chỉ cần chạy thẳng tới
        """
        controller = self._create_controller()

        pan_adj, tilt_adj = controller.update((320, 240))

        assert pan_adj == 0, f"Người ở giữa → pan_adjustment phải = 0, nhận {pan_adj}"
        assert tilt_adj == 0, f"Người ở giữa → tilt_adjustment phải = 0, nhận {tilt_adj}"
        assert controller.is_centered() == True, "Người ở giữa → is_centered = True"
        print("✅ Người ở giữa → servo không quay (đúng)")

    def test_person_on_right(self):
        """
        Test: Người bên phải frame → servo quay phải
        
        Đầu vào:
          - person_center = (550, 240) — bên phải, giữa theo chiều dọc
        
        Kết quả mong đợi:
          - pan_adjustment > 0 (quay phải)
          - Sau update, pan_angle > 0
        
        Giải thích:
          → Người ở bên phải camera
          → Robot cần quay phải để đưa người vào giữa
        """
        controller = self._create_controller()

        pan_adj, _ = controller.update((550, 240))

        assert pan_adj > 0, f"Người bên phải → pan_adjustment phải > 0, nhận {pan_adj}"
        
        pan, _ = controller.get_servo_angles()
        assert pan > 0, f"Pan angle phải > 0, nhận {pan}"
        print("✅ Người bên phải → servo quay phải (đúng)")

    def test_person_on_left(self):
        """
        Test: Người bên trái frame → servo quay trái
        
        Đầu vào:
          - person_center = (50, 240) — bên trái
        
        Kết quả mong đợi:
          - pan_adjustment < 0 (quay trái)
        """
        controller = self._create_controller()

        pan_adj, _ = controller.update((50, 240))

        assert pan_adj < 0, f"Người bên trái → pan_adjustment phải < 0, nhận {pan_adj}"
        print("✅ Người bên trái → servo quay trái (đúng)")

    def test_person_on_top(self):
        """
        Test: Người phía trên frame → servo ngẩng lên
        
        Đầu vào:
          - person_center = (320, 50) — phía trên, giữa theo chiều ngang
        
        Kết quả mong đợi:
          - tilt_adjustment > 0 (ngẩng lên)
        
        Lưu ý: Trục Y trong OpenCV ngược (y=0 ở trên, y=480 ở dưới)
        """
        controller = self._create_controller()

        _, tilt_adj = controller.update((320, 50))

        assert tilt_adj > 0, f"Người phía trên → tilt_adjustment phải > 0, nhận {tilt_adj}"
        print("✅ Người phía trên → servo ngẩng lên (đúng)")

    def test_is_centered(self):
        """
        Test: Kiểm tra hàm is_centered()
        
        Kết quả mong đợi:
          - Người ở giữa → True
          - Người ở góc → False
        """
        controller = self._create_controller()

        # Người ở giữa
        controller.update((320, 240))
        assert controller.is_centered() == True, "Người ở giữa → True"

        # Reset và thử người ở góc
        controller.reset()
        controller.update((600, 50))
        assert controller.is_centered() == False, "Người ở góc → False"
        print("✅ is_centered() hoạt động đúng")

    def test_reset(self):
        """
        Test: Reset servo về vị trí (0, 0)
        
        Tình huống:
          - Update vài lần → góc thay đổi
          - Gọi reset() → góc phải trở về (0, 0)
        """
        controller = self._create_controller()

        # Quay servo đi
        controller.update((600, 50))
        controller.update((600, 50))

        # Kiểm tra góc đã thay đổi
        pan, tilt = controller.get_servo_angles()
        assert pan != 0 or tilt != 0, "Sau update, góc phải khác 0"

        # Reset
        controller.reset()
        pan, tilt = controller.get_servo_angles()
        assert pan == 0 and tilt == 0, f"Sau reset, góc phải = (0,0), nhận ({pan},{tilt})"
        print("✅ Reset → góc về (0, 0) (đúng)")

    def test_none_input(self):
        """
        Test: Input None → không crash, trả về (0, 0)
        
        Tình huống:
          - Không phát hiện người → person_center = None
        
        Kết quả mong đợi:
          - update(None) → (0, 0)
          - Không exception
        """
        controller = self._create_controller()

        result = controller.update(None)

        assert result == (0, 0), f"Input None → phải trả về (0,0), nhận {result}"
        print("✅ Input None → (0, 0), không crash (đúng)")
