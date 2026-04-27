"""
Person Detector Module using YOLOv8
Phát hiện người trong frame với độ chính xác cao
"""

from ultralytics import YOLO
import numpy as np
import config


class PersonDetector:
    """
    Lớp phát hiện người sử dụng YOLOv8
    """
    
    def __init__(self, model_name: str = None):
        """
        Khởi tạo detector với model YOLOv8
        
        Args:
            model_name: Tên model YOLO (mặc định từ config)
        """
        if model_name is None:
            model_name = config.YOLO_MODEL
            
        print(f"[Detector] Đang tải model {model_name}...")
        self.model = YOLO(model_name)
        print(f"[Detector] Model đã sẵn sàng!")
        
        self.confidence_threshold = config.CONFIDENCE_THRESHOLD
        self.person_class_id = config.PERSON_CLASS_ID
    
    def detect(self, frame: np.ndarray) -> list:
        """
        Phát hiện tất cả người trong frame
        
        Args:
            frame: Frame ảnh dạng numpy array (BGR)
            
        Returns:
            List các detection, mỗi detection là dict:
            {
                'bbox': (x1, y1, x2, y2),
                'confidence': float,
                'center': (cx, cy),
                'area': float
            }
        """
        # Chạy inference
        results = self.model(frame, verbose=False)[0]
        
        detections = []
        
        # Lọc chỉ lấy class người
        for box in results.boxes:
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])
            
            # Chỉ lấy người và đủ ngưỡng confidence
            if class_id == self.person_class_id and confidence >= self.confidence_threshold:
                # Lấy tọa độ bounding box
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                
                # Tính tâm và diện tích
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                area = (x2 - x1) * (y2 - y1)
                
                detections.append({
                    'bbox': (x1, y1, x2, y2),
                    'confidence': confidence,
                    'center': (cx, cy),
                    'area': area
                })
        
        return detections
    
    def get_largest_person(self, detections: list) -> dict:
        """
        Lấy người có bounding box lớn nhất (gần camera nhất)
        
        Args:
            detections: List các detection từ hàm detect()
            
        Returns:
            Detection của người lớn nhất, hoặc None nếu không có người
        """
        if not detections:
            return None
            
        # Sắp xếp theo diện tích giảm dần
        sorted_detections = sorted(detections, key=lambda x: x['area'], reverse=True)
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
    import cv2
    
    detector = PersonDetector()
    
    # Test với webcam
    cap = cv2.VideoCapture(0)
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        detections = detector.detect(frame)
        
        for det in detections:
            x1, y1, x2, y2 = det['bbox']
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.circle(frame, det['center'], 5, (0, 0, 255), -1)
            
        cv2.imshow("Person Detection Test", frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()
