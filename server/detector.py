"""
Person Detector Module using YOLOv8
Phát hiện người trong frame với tiền xử lý ảnh nâng cao

Pipeline xử lý:
  1. Giảm nhiễu (FastNlMeans) — ảnh ESP32-CAM thường nhiều noise
  2. Cân bằng sáng (CLAHE) — cải thiện phát hiện trong điều kiện thiếu sáng
  3. YOLO inference — phát hiện người
  4. Lọc false positive (tracking) — chỉ xác nhận khi phát hiện ≥3 frame liên tiếp
"""

from ultralytics import YOLO
import numpy as np
import cv2
import config
from tracker import SORT


class ImagePreprocessor:
    """Tiền xử lý ảnh trước khi đưa vào YOLO."""

    def __init__(self, denoise_strength=5, clahe_clip=2.0, clahe_grid=(8, 8)):
        """
        Args:
            denoise_strength: Cường độ giảm nhiễu (0 = tắt, 5-10 = bình thường)
            clahe_clip: Giới hạn contrast cho CLAHE (2.0 = mặc định)
            clahe_grid: Kích thước grid cho CLAHE
        """
        self.denoise_strength = denoise_strength
        self.clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=clahe_grid)

    def process(self, frame: np.ndarray) -> np.ndarray:
        """
        Tiền xử lý frame: giảm nhiễu + cân bằng sáng.

        Args:
            frame: Ảnh BGR từ ESP32-CAM

        Returns:
            Frame đã được xử lý
        """
        processed = frame

        # 1. Giảm nhiễu — GaussianBlur nhanh (~1ms) thay vì fastNlMeans (~100ms)
        if self.denoise_strength > 0:
            ksize = self.denoise_strength * 2 + 1  # Phải là số lẻ
            processed = cv2.GaussianBlur(processed, (ksize, ksize), 0)

        # 2. CLAHE — cân bằng sáng cục bộ (tăng contrast trong vùng tối)
        lab = cv2.cvtColor(processed, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        l_channel = self.clahe.apply(l_channel)
        processed = cv2.merge([l_channel, a_channel, b_channel])
        processed = cv2.cvtColor(processed, cv2.COLOR_LAB2BGR)

        # 3. Unsharp Mask — khôi phục edge bị mất do blur, giúp YOLO thấy biên người rõ hơn
        if self.denoise_strength > 0:
            blurred = cv2.GaussianBlur(processed, (0, 0), 3)
            processed = cv2.addWeighted(processed, 1.5, blurred, -0.5, 0)

        return processed


class DetectionTracker:
    """
    Lọc false positive bằng cách đếm frame liên tiếp.
    Chỉ xác nhận "có người" khi phát hiện >= min_consecutive_frames liên tiếp.
    """

    def __init__(self, min_consecutive_frames=3):
        self.min_frames = min_consecutive_frames
        self.consecutive_count = 0   # Số frame liên tiếp phát hiện người
        self.no_detect_count = 0     # Số frame liên tiếp KHÔNG phát hiện
        self.confirmed = False       # Trạng thái xác nhận

    def update(self, detected: bool) -> bool:
        """
        Cập nhật trạng thái tracking.

        Args:
            detected: True nếu YOLO phát hiện người trong frame này

        Returns:
            True nếu đã xác nhận có người (đủ số frame liên tiếp)
        """
        if detected:
            self.consecutive_count += 1
            self.no_detect_count = 0

            if self.consecutive_count >= self.min_frames:
                self.confirmed = True
        else:
            self.no_detect_count += 1
            self.consecutive_count = 0

            # Mất tín hiệu 5 frame liên tiếp → reset confirmed
            if self.no_detect_count >= 5:
                self.confirmed = False

        return self.confirmed


class PersonDetector:
    """
    Lớp phát hiện người sử dụng YOLOv8 với tiền xử lý ảnh.
    """

    def __init__(self, model_name: str = None, enable_preprocess: bool = True):
        """
        Khởi tạo detector với model YOLOv8

        Args:
            model_name: Tên model YOLO (mặc định từ config)
            enable_preprocess: Bật/tắt tiền xử lý ảnh
        """
        if model_name is None:
            model_name = config.YOLO_MODEL

        print(f"[Detector] Đang tải model {model_name}...")
        self.model = YOLO(model_name)
        print(f"[Detector] Model đã sẵn sàng!")

        self.confidence_threshold = config.CONFIDENCE_THRESHOLD
        self.person_class_id = config.PERSON_CLASS_ID

        # Tiền xử lý ảnh
        self.enable_preprocess = enable_preprocess
        if enable_preprocess:
            self.preprocessor = ImagePreprocessor(
                denoise_strength=5,  # Vừa phải, không làm chậm quá nhiều
                clahe_clip=2.0,
                clahe_grid=(8, 8),
            )
            print("[Detector] Tiền xử lý ảnh: BẬT (Denoise + CLAHE)")
        else:
            self.preprocessor = None
            print("[Detector] Tiền xử lý ảnh: TẮT")

        # Tracking để lọc false positive và lock-on mục tiêu
        self.tracker = SORT(max_age=5, min_hits=1, iou_threshold=0.3)

    def detect_confirmed(self, frame: np.ndarray, target_type: str = "person") -> tuple:
        """
        Phát hiện người hoặc thú cưng + lọc false positive bằng tracking.

        Args:
            frame: Frame ảnh numpy array
            target_type: "person" hoặc "pet"

        Returns:
            (detections, confirmed): detections là list kết quả YOLO,
            confirmed là True nếu đã phát hiện ≥3 frame liên tiếp
        """
        # Tiền xử lý ảnh
        if self.preprocessor:
            processed = self.preprocessor.process(frame)
        else:
            processed = frame

        # Chạy inference
        results = self.model(processed, verbose=False)[0]

        detections = []

        # Lọc theo target_type
        for box in results.boxes:
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])

            is_target = False
            if target_type == "person" and class_id == self.person_class_id:
                is_target = True
            elif target_type == "pet" and class_id in config.PET_CLASS_IDS:
                is_target = True

            # Chỉ lấy mục tiêu và đủ ngưỡng confidence
            if is_target and confidence >= self.confidence_threshold:
                x1, y1, x2, y2 = map(float, box.xyxy[0].tolist())
                # Bắt buộc append vào detections 5 giá trị [x1, y1, x2, y2, score]
                detections.append([x1, y1, x2, y2, confidence])

        raw_dets = np.array(detections) if len(detections) > 0 else np.empty((0, 5))
        
        # In logs để debug nếu cần
        # print(f"YOLO raw_dets shape: {raw_dets.shape}")
        
        tracked_objects = self.tracker.update(raw_dets)
        
        final_detections = []
        if len(tracked_objects) > 0:
            for trk in tracked_objects:
                x1, y1, x2, y2, obj_id = trk
                cx = int((x1 + x2) / 2)
                cy = int((y1 + y2) / 2)
                area = int((x2 - x1) * (y2 - y1))
                
                final_detections.append({
                    'bbox': (int(x1), int(y1), int(x2), int(y2)),
                    'confidence': 1.0,
                    'center': (cx, cy),
                    'area': area,
                    'class_id': self.person_class_id if target_type == "person" else config.PET_CLASS_IDS[0],
                    'id': int(obj_id)
                })

        confirmed = len(final_detections) > 0
        return final_detections, confirmed

    def get_largest_person(self, detections: list, target_id: int = None) -> dict:
        """
        Lấy người có bounding box lớn nhất (gần camera nhất) hoặc theo target_id để Lock-on

        Args:
            detections: List các detection từ hàm detect()
            target_id: ID mục tiêu cần theo dõi (nếu có)

        Returns:
            Detection của mục tiêu lớn nhất, hoặc theo ID nếu có target_id
        """
        if not detections:
            return None

        # Lock-on: N\u1ebfu c\u00f3 target_id, c\u1ed1 g\u1eafng t\u00ecm n\u00f3 tr\u01b0\u1edbc
        if target_id is not None:
            for det in detections:
                if det.get('id') == target_id:
                    return det

        # Fallback: S\u1eafp x\u1ebfp theo di\u1ec7n t\u00edch gi\u1ea3m d\u1ea7n
        sorted_detections = sorted(detections, key=lambda x: x.get('area', 0), reverse=True)
        return sorted_detections[0]

    def get_person_center(self, detection: dict) -> tuple:
        """
        Lấy tọa độ tâm của người

        Args:
            detection: Detection dict

        Returns:
            Tuple (cx, cy) hoặc None
        """
        if detection is None:
            return None
        return detection['center']


# Test module nếu chạy trực tiếp
if __name__ == "__main__":
    detector = PersonDetector()

    # Test với webcam
    cap = cv2.VideoCapture(0)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        detections, confirmed = detector.detect_confirmed(frame)

        # Vẽ kết quả
        for det in detections:
            x1, y1, x2, y2 = det['bbox']
            obj_id = det.get('id', '?')
            color = (0, 255, 0) if confirmed else (0, 165, 255)  # Xanh = confirmed, cam = chưa
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.circle(frame, det['center'], 5, (0, 0, 255), -1)
            label = f"ID: {obj_id} {'OK' if confirmed else '...'}"
            cv2.putText(frame, label, (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        status = "CONFIRMED Tracker" if confirmed else "Scanning..."
        cv2.putText(frame, status, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

        cv2.imshow("Person Detection Test", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
