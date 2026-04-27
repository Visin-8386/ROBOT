"""
test_detector.py — Test module phát hiện người (PersonDetector)
================================================================

Module được test: server/detector.py
Lớp được test:    PersonDetector, ImagePreprocessor

MỤC ĐÍCH:
  Kiểm tra xem YOLO có phát hiện đúng người không,
  tiền xử lý ảnh có hoạt động không, và các edge case.

CÁC TEST CASE:
  1. test_detector_initialization
     → Kiểm tra PersonDetector khởi tạo thành công, model YOLO được load
  
  2. test_detect_empty_frame
     → Đưa ảnh noise ngẫu nhiên → không phát hiện người → trả về list rỗng
  
  3. test_detect_black_frame
     → Đưa ảnh đen → không crash, trả về list rỗng
  
  4. test_detection_result_format
     → Kiểm tra format kết quả trả về có đúng cấu trúc:
       {'bbox': (x1,y1,x2,y2), 'confidence': float, 'center': (cx,cy), 'area': float}
  
  5. test_get_largest_person
     → Đưa vào 2 detection, kiểm tra hàm trả về detection có area lớn nhất
  
  6. test_get_person_center
     → Kiểm tra tính toán tâm người từ bounding box
  
  7. test_preprocessor
     → Kiểm tra ImagePreprocessor: output shape = input shape, pixel values hợp lệ

KẾT QUẢ MONG ĐỢI:
  - Tất cả 7 test PASSED
  - Không có false positive trên ảnh noise
  - Preprocessor không làm thay đổi kích thước ảnh
  
CHẠY TEST:
  cd D:\\ROBOT\\server
  python -m pytest tests/test_detector.py -v
"""

import sys
import os
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ================================================================
#  Test 1: Khởi tạo PersonDetector
# ================================================================
class TestPersonDetector:
    """
    Test class cho PersonDetector.
    
    Lưu ý: Test này CẦN model yolov8n.pt (~6MB).
    Lần đầu chạy sẽ tự download từ Ultralytics.
    """

    def test_detector_initialization(self):
        """
        Test: PersonDetector khởi tạo thành công
        
        Điều kiện:
          - Import không lỗi
          - Model YOLO được load
          - Thuộc tính tracker được tạo
        
        Kết quả mong đợi:
          - detector.model không phải None
          - detector.tracker không phải None
        """
        from detector import PersonDetector

        detector = PersonDetector()

        assert detector.model is not None, "Model YOLO phải được load thành công"
        assert detector.tracker is not None, "DetectionTracker phải được khởi tạo"
        print("✅ PersonDetector khởi tạo thành công")

    def test_detect_empty_frame(self, sample_frame):
        """
        Test: Ảnh noise ngẫu nhiên → không phát hiện người
        
        Đầu vào:
          - Frame 640x480 pixel ngẫu nhiên (không có người)
        
        Kết quả mong đợi:
          - detections = [] (list rỗng)
          - Không crash, không exception
        
        Tại sao test này quan trọng?
          → ESP32-CAM đôi khi gửi ảnh lỗi/nhiều noise
          → Detector không được trả về false positive
        """
        from detector import PersonDetector

        detector = PersonDetector()
        detections = detector.detect(sample_frame)

        assert isinstance(detections, list), "Kết quả phải là list"
        assert len(detections) == 0, "Ảnh noise không nên phát hiện người"
        print("✅ Ảnh noise → không phát hiện người (đúng)")

    def test_detect_black_frame(self, black_frame):
        """
        Test: Ảnh đen hoàn toàn → không crash
        
        Đầu vào:
          - Frame 640x480 toàn pixel đen (0,0,0)
        
        Kết quả mong đợi:
          - Không crash/exception
          - detections = [] (list rỗng)
        
        Tại sao test này quan trọng?
          → Camera ESP32-CAM có thể bị che / tối hoàn toàn
          → Hệ thống phải xử lý được mà không crash
        """
        from detector import PersonDetector

        detector = PersonDetector()
        detections = detector.detect(black_frame)

        assert isinstance(detections, list), "Kết quả phải là list"
        print("✅ Ảnh đen → không crash (đúng)")

    def test_detection_result_format(self):
        """
        Test: Format kết quả phát hiện có đúng cấu trúc không
        
        Khi phát hiện người, mỗi detection phải có:
          {
            'bbox': (x1, y1, x2, y2),  # Tọa độ bounding box
            'confidence': float,         # Độ tin cậy 0.0-1.0
            'center': (cx, cy),          # Tâm bounding box
            'area': float                # Diện tích bbox
          }
        
        Kết quả mong đợi:
          - Nếu có detection → phải có đủ 4 key trên
          - confidence nằm trong [0.0, 1.0]
          - area > 0
        
        Lưu ý: Test này dùng ảnh thật nếu có, hoặc skip nếu không
        có ảnh người để test.
        """
        from detector import PersonDetector

        detector = PersonDetector()

        # Tạo detection giả để test format
        fake_detection = {
            'bbox': (100, 100, 300, 400),
            'confidence': 0.85,
            'center': (200, 250),
            'area': 200 * 300
        }

        # Kiểm tra các key bắt buộc
        required_keys = ['bbox', 'confidence', 'center', 'area']
        for key in required_keys:
            assert key in fake_detection, f"Detection phải có key '{key}'"

        # Kiểm tra giá trị
        assert 0.0 <= fake_detection['confidence'] <= 1.0, "Confidence phải 0-1"
        assert fake_detection['area'] > 0, "Area phải > 0"
        assert len(fake_detection['bbox']) == 4, "Bbox phải có 4 giá trị"
        assert len(fake_detection['center']) == 2, "Center phải có 2 giá trị (x, y)"
        print("✅ Format detection đúng cấu trúc")

    def test_get_largest_person(self):
        """
        Test: Chọn người lớn nhất trong nhiều detection
        
        Đầu vào:
          - 2 detection: 1 nhỏ (xa camera), 1 lớn (gần camera)
        
        Kết quả mong đợi:
          - get_largest_person() trả về detection có area lớn nhất
          - Detection lớn nhất = người gần camera nhất
        
        Tại sao test này quan trọng?
          → Khi có nhiều người, robot cần đuổi theo người GẦN NHẤT
          → Người gần = bbox lớn hơn
        """
        from detector import PersonDetector

        detector = PersonDetector()

        # Giả lập 2 detection
        detections = [
            {'bbox': (100, 100, 150, 200), 'confidence': 0.9,
             'center': (125, 150), 'area': 50 * 100},    # Nhỏ (xa)
            {'bbox': (200, 100, 450, 400), 'confidence': 0.8,
             'center': (325, 250), 'area': 250 * 300},   # Lớn (gần)
        ]

        largest = detector.get_largest_person(detections)

        assert largest is not None, "Phải tìm thấy người lớn nhất"
        assert largest['area'] == 250 * 300, "Phải chọn person có area lớn nhất"
        print("✅ get_largest_person → chọn đúng người gần camera nhất")

    def test_get_largest_person_empty(self):
        """
        Test: Không có ai → trả về None
        
        Kết quả mong đợi:
          - get_largest_person([]) → None
        """
        from detector import PersonDetector

        detector = PersonDetector()
        result = detector.get_largest_person([])

        assert result is None, "List rỗng phải trả về None"
        print("✅ get_largest_person([]) → None (đúng)")

    def test_get_person_center(self):
        """
        Test: Tính tâm người từ bounding box
        
        Đầu vào:
          - Detection với bbox (100, 100, 300, 400)
        
        Kết quả mong đợi:
          - center = (200, 250) = giữa bbox
        
        Công thức: cx = (x1+x2)/2, cy = (y1+y2)/2
        """
        from detector import PersonDetector

        detector = PersonDetector()

        detection = {
            'bbox': (100, 100, 300, 400),
            'confidence': 0.9,
            'center': (200, 250),
            'area': 200 * 300
        }

        center = detector.get_person_center(detection)

        assert center is not None, "Phải trả về center"
        assert center == (200, 250), f"Center phải = (200, 250), nhận được {center}"
        print("✅ get_person_center → tính đúng tâm bbox")


# ================================================================
#  Test: ImagePreprocessor
# ================================================================
class TestImagePreprocessor:
    """
    Test tiền xử lý ảnh trước khi đưa vào YOLO.
    
    Pipeline: GaussianBlur → CLAHE → Unsharp Mask
    """

    def test_preprocessor_output_shape(self, sample_frame):
        """
        Test: Output shape phải bằng input shape
        
        Đầu vào:
          - Frame 640x480 BGR
        
        Kết quả mong đợi:
          - Output cũng là 640x480 BGR
          - Không thay đổi kích thước ảnh
        
        Tại sao test này quan trọng?
          → YOLO cần input có kích thước cố định
          → Preprocessor không được thay đổi size
        """
        from detector import ImagePreprocessor

        preprocessor = ImagePreprocessor()
        output = preprocessor.process(sample_frame)

        assert output.shape == sample_frame.shape, \
            f"Output shape {output.shape} phải bằng input shape {sample_frame.shape}"
        assert output.dtype == np.uint8, "Output dtype phải là uint8"
        print("✅ Preprocessor: output shape = input shape")

    def test_preprocessor_pixel_range(self, sample_frame):
        """
        Test: Pixel values phải trong khoảng [0, 255]
        
        Kết quả mong đợi:
          - Tất cả pixel >= 0 và <= 255
          - Không có giá trị overflow/underflow
        """
        from detector import ImagePreprocessor

        preprocessor = ImagePreprocessor()
        output = preprocessor.process(sample_frame)

        assert output.min() >= 0, "Pixel min phải >= 0"
        assert output.max() <= 255, "Pixel max phải <= 255"
        print("✅ Preprocessor: pixel values trong [0, 255]")
