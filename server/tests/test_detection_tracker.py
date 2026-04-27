"""
test_detection_tracker.py — Test bộ lọc false positive (DetectionTracker)
==========================================================================

Module được test: server/detector.py
Lớp được test:    DetectionTracker

MỤC ĐÍCH:
  DetectionTracker lọc false positive bằng cách yêu cầu phát hiện
  người liên tiếp >= N frame trước khi xác nhận "có người thật".
  File này test logic đếm frame đó.

CÁC TEST CASE:
  1. test_single_detection_not_confirmed
     → 1 frame phát hiện → chưa confirmed (có thể là noise)
  
  2. test_three_consecutive_confirmed
     → 3 frame liên tiếp phát hiện → confirmed = True ✓
  
  3. test_interrupted_detection_resets
     → 2 frame detect + 1 frame miss → reset, chưa confirmed
  
  4. test_lost_after_confirmed
     → Đã confirmed → mất nhiều frame → confirmed reset về False
  
  5. test_custom_threshold
     → Thay đổi min_consecutive_frames = 5 → cần 5 frame mới confirmed

KẾT QUẢ MONG ĐỢI:
  - Tất cả 5 test PASSED
  - Tracker chỉ confirmed khi đủ frame liên tiếp (không false positive)

CHẠY TEST:
  cd D:\\ROBOT\\server
  python -m pytest tests/test_detection_tracker.py -v
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestDetectionTracker:
    """
    Test DetectionTracker — bộ lọc false positive.
    
    Nguyên lý hoạt động:
      - Đếm số frame liên tiếp phát hiện người
      - Chỉ confirmed khi đếm >= min_consecutive_frames (mặc định = 3)
      - Nếu mất detection → reset counter
      - Nếu mất quá nhiều frame → reset confirmed
    """

    def test_single_detection_not_confirmed(self):
        """
        Test: 1 frame phát hiện → chưa confirmed
        
        Tình huống:
          - YOLO phát hiện người trong 1 frame duy nhất
          - Có thể chỉ là noise / false positive
        
        Kết quả mong đợi:
          - confirmed = False (cần thêm frame để xác nhận)
        
        Giải thích:
          → 1 frame không đủ tin cậy
          → Tránh robot đuổi theo "ma" (false positive)
        """
        from detector import DetectionTracker

        tracker = DetectionTracker(min_consecutive_frames=3)

        # Chỉ 1 frame phát hiện
        result = tracker.update(detected=True)

        assert result == False, "1 frame phát hiện → chưa đủ để confirmed"
        print("✅ 1 frame detect → confirmed=False (đúng)")

    def test_three_consecutive_confirmed(self):
        """
        Test: 3 frame liên tiếp phát hiện → confirmed
        
        Tình huống:
          - YOLO phát hiện người 3 frame liên tiếp
          - Đủ tin cậy để xác nhận "có người thật"
        
        Kết quả mong đợi:
          - Frame 1: confirmed = False
          - Frame 2: confirmed = False
          - Frame 3: confirmed = True ✓
        """
        from detector import DetectionTracker

        tracker = DetectionTracker(min_consecutive_frames=3)

        # 3 frame liên tiếp phát hiện người
        r1 = tracker.update(detected=True)   # Frame 1
        r2 = tracker.update(detected=True)   # Frame 2
        r3 = tracker.update(detected=True)   # Frame 3

        assert r1 == False, "Frame 1: chưa đủ"
        assert r2 == False, "Frame 2: chưa đủ"
        assert r3 == True, "Frame 3: đủ 3 frame → confirmed!"
        print("✅ 3 frame liên tiếp → confirmed=True (đúng)")

    def test_interrupted_detection_resets(self):
        """
        Test: Bị ngắt giữa chừng → reset counter
        
        Tình huống:
          - Frame 1: detect ✓
          - Frame 2: detect ✓
          - Frame 3: MISS ✗ (mất detection)
          - Frame 4: detect ✓
          - Frame 5: detect ✓
        
        Kết quả mong đợi:
          - Sau frame 3 (miss) → counter reset về 0
          - Frame 4, 5 chỉ đếm được 2 → chưa confirmed
        
        Giải thích:
          → Detection phải LIÊN TIẾP, không được đứt quãng
          → Nếu bị đứt = có thể là 2 sự kiện khác nhau
        """
        from detector import DetectionTracker

        tracker = DetectionTracker(min_consecutive_frames=3)

        tracker.update(detected=True)   # +1 → count=1
        tracker.update(detected=True)   # +1 → count=2
        tracker.update(detected=False)  # MISS → reset!
        tracker.update(detected=True)   # +1 → count=1 (bắt đầu lại)
        r = tracker.update(detected=True)  # +1 → count=2

        assert r == False, "Bị ngắt giữa chừng → reset, chưa đủ 3 frame liên tiếp"
        print("✅ Detection bị ngắt → reset counter (đúng)")

    def test_lost_after_confirmed(self):
        """
        Test: Đã confirmed → sau đó mất người → reset
        
        Tình huống:
          - 3 frame detect → confirmed = True
          - Sau đó 6 frame mất detect liên tiếp
        
        Kết quả mong đợi:
          - Confirmed trở về False sau khi mất nhiều frame
        
        Giải thích:
          → Người đã rời khỏi camera
          → Robot cần biết để chuyển trạng thái (CHASE → PATROL)
        """
        from detector import DetectionTracker

        tracker = DetectionTracker(min_consecutive_frames=3)

        # Confirmed trước
        tracker.update(detected=True)
        tracker.update(detected=True)
        tracker.update(detected=True)  # → confirmed

        # Mất người nhiều frame
        for _ in range(6):
            result = tracker.update(detected=False)

        assert result == False, "Mất người nhiều frame → confirmed phải reset"
        print("✅ Mất người sau confirmed → reset (đúng)")

    def test_custom_threshold(self):
        """
        Test: Thay đổi ngưỡng min_consecutive_frames
        
        Tình huống:
          - Đặt threshold = 5 (cần 5 frame liên tiếp)
          - Gửi 4 frame detect → chưa confirmed
          - Gửi frame thứ 5 → confirmed
        
        Kết quả mong đợi:
          - 4 frame → False
          - 5 frame → True
        """
        from detector import DetectionTracker

        tracker = DetectionTracker(min_consecutive_frames=5)

        # 4 frame → chưa đủ
        for _ in range(4):
            result = tracker.update(detected=True)
        assert result == False, "4/5 frame → chưa đủ"

        # Frame thứ 5 → confirmed
        result = tracker.update(detected=True)
        assert result == True, "5/5 frame → confirmed!"
        print("✅ Custom threshold=5 hoạt động đúng")
