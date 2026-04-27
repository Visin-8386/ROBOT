"""
Main Application - Person Detection with Servo Control Simulation
Ứng dụng chính: Phát hiện người và mô phỏng điều khiển servo camera
"""

import cv2
import numpy as np
import time
import config
from detector import PersonDetector
from servo_controller import SimulatedServoController


def simulate_esp32cam(frame: np.ndarray, resolution=(320, 240), jpeg_quality=40, noise_level=10) -> np.ndarray:
    """
    Giả lập chất lượng camera ESP32-CAM
    
    Args:
        frame: Frame gốc từ webcam
        resolution: Độ phân giải ESP32-CAM (mặc định 320x240 - QVGA)
        jpeg_quality: Chất lượng JPEG (1-100, thấp = nhiều artifact hơn)
        noise_level: Mức nhiễu (0-50)
    
    Returns:
        Frame đã giảm chất lượng
    """
    original_size = (frame.shape[1], frame.shape[0])
    
    # 1. Giảm độ phân giải
    small = cv2.resize(frame, resolution, interpolation=cv2.INTER_LINEAR)
    
    # 2. Thêm JPEG compression artifacts
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
    _, encoded = cv2.imencode('.jpg', small, encode_param)
    small = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    
    # 3. Thêm nhiễu (noise) như camera giá rẻ
    if noise_level > 0:
        noise = np.random.normal(0, noise_level, small.shape).astype(np.int16)
        small = np.clip(small.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    
    # 4. Scale lên lại kích thước gốc để hiển thị
    result = cv2.resize(small, original_size, interpolation=cv2.INTER_NEAREST)
    
    return result


class PersonTrackingApp:
    """
    Ứng dụng tracking người với servo simulation
    """
    
    def __init__(self, camera_id: int = 0, video_path: str = None, esp32_mode: bool = False):
        """
        Khởi tạo ứng dụng
        
        Args:
            camera_id: ID của webcam (mặc định 0)
            video_path: Đường dẫn video file (nếu không dùng webcam)
            esp32_mode: Bật chế độ giả lập ESP32-CAM
        """
        print("=" * 50)
        print("PERSON TRACKING WITH SERVO CONTROL SIMULATION")
        print("=" * 50)
        
        self.esp32_mode = esp32_mode
        if esp32_mode:
            print("[Main] CHẾ ĐỘ GIẢ LẬP ESP32-CAM")
        
        # Khởi tạo camera/video
        if video_path:
            self.cap = cv2.VideoCapture(video_path)
            print(f"[Main] Sử dụng video: {video_path}")
        else:
            self.cap = cv2.VideoCapture(camera_id)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
            print(f"[Main] Sử dụng webcam ID: {camera_id}")
        
        # Lấy kích thước thực của frame
        self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[Main] Kích thước frame: {self.frame_width}x{self.frame_height}")
        
        # Khởi tạo detector và servo controller
        self.detector = PersonDetector()
        self.servo = SimulatedServoController(self.frame_width, self.frame_height)
        
        # Biến theo dõi FPS
        self.fps = 0
        self.frame_count = 0
        self.start_time = time.time()
        
        print("[Main] Sẵn sàng! Nhấn 'Q' để thoát, 'R' để reset servo, 'E' để bật/tắt ESP32")
        print("=" * 50)
    
    def draw_overlay(self, frame: np.ndarray, detection: dict) -> np.ndarray:
        """
        Vẽ các thông tin overlay lên frame
        
        Args:
            frame: Frame gốc
            detection: Detection của người (hoặc None)
            
        Returns:
            Frame với overlay
        """
        overlay = frame.copy()
        
        # Vẽ crosshair tâm frame
        cx, cy = self.frame_width // 2, self.frame_height // 2
        cv2.line(overlay, (cx - 30, cy), (cx + 30, cy), config.CENTER_COLOR, 2)
        cv2.line(overlay, (cx, cy - 30), (cx, cy + 30), config.CENTER_COLOR, 2)
        cv2.circle(overlay, (cx, cy), 5, config.CENTER_COLOR, -1)
        
        # Nếu có detection
        if detection:
            # Vẽ bounding box
            x1, y1, x2, y2 = detection['bbox']
            cv2.rectangle(overlay, (x1, y1), (x2, y2), config.BOX_COLOR, 3)
            
            # Vẽ tâm người
            person_cx, person_cy = detection['center']
            cv2.circle(overlay, (person_cx, person_cy), 8, config.BOX_COLOR, -1)
            
            # Vẽ đường nối từ tâm frame đến tâm người
            cv2.line(overlay, (cx, cy), (person_cx, person_cy), config.ARROW_COLOR, 2)
            
            # Vẽ mũi tên chỉ hướng cần di chuyển
            if not self.servo.is_centered():
                # Tính hướng mũi tên (từ người về tâm)
                arrow_length = 50
                dx = cx - person_cx
                dy = cy - person_cy
                dist = np.sqrt(dx**2 + dy**2)
                if dist > 0:
                    dx = int(dx / dist * arrow_length)
                    dy = int(dy / dist * arrow_length)
                    arrow_start = (person_cx, person_cy)
                    arrow_end = (person_cx + dx, person_cy + dy)
                    cv2.arrowedLine(overlay, arrow_start, arrow_end, 
                                   config.ARROW_COLOR, 3, tipLength=0.4)
            
            # Hiển thị confidence
            conf_text = f"Conf: {detection['confidence']:.2f}"
            cv2.putText(overlay, conf_text, (x1, y1 - 10), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, config.BOX_COLOR, 2)
        
        # Panel thông tin góc servo (nền bán trong suốt)
        panel_height = 120
        overlay_rect = overlay.copy()
        cv2.rectangle(overlay_rect, (0, 0), (280, panel_height), (0, 0, 0), -1)
        cv2.addWeighted(overlay_rect, 0.6, overlay, 0.4, 0, overlay)
        
        # Hiển thị góc servo
        pan, tilt = self.servo.get_servo_angles()
        cv2.putText(overlay, f"PAN:  {pan:+6.1f} deg", (10, 25), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, config.TEXT_COLOR, 2)
        cv2.putText(overlay, f"TILT: {tilt:+6.1f} deg", (10, 50), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, config.TEXT_COLOR, 2)
        
        # Hiển thị hướng di chuyển
        direction = self.servo.get_direction_text()
        color = (0, 255, 0) if self.servo.is_centered() else (0, 255, 255)
        cv2.putText(overlay, direction, (10, 80), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        
        # Hiển thị FPS
        cv2.putText(overlay, f"FPS: {self.fps:.1f}", (10, 110), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, config.TEXT_COLOR, 2)
        
        # Hiển thị trạng thái detection
        status = "PERSON DETECTED" if detection else "NO PERSON"
        status_color = (0, 255, 0) if detection else (0, 0, 255)
        cv2.putText(overlay, status, (self.frame_width - 200, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
        
        return overlay
    
    def update_fps(self):
        """Cập nhật FPS"""
        self.frame_count += 1
        elapsed = time.time() - self.start_time
        if elapsed >= 1.0:
            self.fps = self.frame_count / elapsed
            self.frame_count = 0
            self.start_time = time.time()
    
    def run(self):
        """Chạy vòng lặp chính"""
        
        while True:
            # Đọc frame
            ret, frame = self.cap.read()
            if not ret:
                print("[Main] Không thể đọc frame, thoát...")
                break
            
            # Áp dụng giả lập ESP32-CAM nếu bật
            if self.esp32_mode:
                frame = simulate_esp32cam(frame)
            
            # Phát hiện người
            detections = self.detector.detect(frame)
            
            # Lấy người lớn nhất (gần nhất)
            main_person = self.detector.get_largest_person(detections)
            
            # Cập nhật servo controller
            if main_person:
                person_center = main_person['center']
                self.servo.update(person_center)
            
            # Vẽ overlay
            display_frame = self.draw_overlay(frame, main_person)
            
            # Hiển thị
            cv2.imshow("Person Tracking - Press Q to Quit", display_frame)
            
            # Cập nhật FPS
            self.update_fps()
            
            # Xử lý phím
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == ord('Q'):
                print("[Main] Nhận lệnh thoát...")
                break
            elif key == ord('r') or key == ord('R'):
                self.servo.reset()
            elif key == ord('e') or key == ord('E'):
                self.esp32_mode = not self.esp32_mode
                status = "BẬT" if self.esp32_mode else "TẮT"
                print(f"[Main] Chế độ ESP32-CAM: {status}")
        
        # Cleanup
        self.cap.release()
        cv2.destroyAllWindows()
        print("[Main] Đã thoát!")
    
    def __del__(self):
        """Destructor"""
        if hasattr(self, 'cap') and self.cap.isOpened():
            self.cap.release()


def main():
    """Entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Person Tracking with Servo Control')
    parser.add_argument('--camera', type=int, default=0, help='Camera ID (default: 0)')
    parser.add_argument('--video', type=str, default=None, help='Path to video file')
    parser.add_argument('--esp32', action='store_true', help='Enable ESP32-CAM simulation mode')
    args = parser.parse_args()
    
    app = PersonTrackingApp(camera_id=args.camera, video_path=args.video, esp32_mode=args.esp32)
    app.run()


if __name__ == "__main__":
    main()
