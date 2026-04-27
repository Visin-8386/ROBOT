"""
Simulated Servo Controller Module
Mô phỏng điều khiển servo Pan-Tilt để đưa người vào giữa frame
"""

import config


class SimulatedServoController:
    """
    Lớp mô phỏng điều khiển servo Pan-Tilt
    
    Pan: Quay trái/phải (trục X)
    Tilt: Ngẩng lên/xuống (trục Y)
    """
    
    def __init__(self, frame_width: int = None, frame_height: int = None):
        """
        Khởi tạo servo controller
        
        Args:
            frame_width: Chiều rộng frame (pixels)
            frame_height: Chiều cao frame (pixels)
        """
        self.frame_width = frame_width or config.CAMERA_WIDTH
        self.frame_height = frame_height or config.CAMERA_HEIGHT
        
        # Tâm frame
        self.frame_center_x = self.frame_width // 2
        self.frame_center_y = self.frame_height // 2
        
        # Góc servo hiện tại (bắt đầu ở vị trí giữa)
        self.pan_angle = 0.0   # Độ, âm = trái, dương = phải
        self.tilt_angle = 0.0  # Độ, âm = xuống, dương = lên
        
        # Cấu hình từ config
        self.kp = config.SERVO_KP
        self.dead_zone_x = config.DEAD_ZONE_X
        self.dead_zone_y = config.DEAD_ZONE_Y
        self.max_speed = config.MAX_SERVO_SPEED
        
        # Giới hạn góc
        self.pan_min = config.SERVO_PAN_MIN
        self.pan_max = config.SERVO_PAN_MAX
        self.tilt_min = config.SERVO_TILT_MIN
        self.tilt_max = config.SERVO_TILT_MAX
        
        # Lưu error để visualization
        self.last_error_x = 0
        self.last_error_y = 0
        
        print(f"[Servo] Khởi tạo với frame {self.frame_width}x{self.frame_height}")
        print(f"[Servo] Tâm frame: ({self.frame_center_x}, {self.frame_center_y})")
    
    def calculate_error(self, person_center: tuple) -> tuple:
        """
        Tính sai số giữa vị trí người và tâm frame
        
        Args:
            person_center: Tuple (x, y) tọa độ tâm người
            
        Returns:
            Tuple (error_x, error_y) - sai số theo pixels
            Dương = người ở bên phải/trên tâm frame
            Âm = người ở bên trái/dưới tâm frame
        """
        if person_center is None:
            return (0, 0)
            
        error_x = person_center[0] - self.frame_center_x
        error_y = self.frame_center_y - person_center[1]  # Đảo ngược vì Y tăng xuống
        
        self.last_error_x = error_x
        self.last_error_y = error_y
        
        return (error_x, error_y)
    
    def update(self, person_center: tuple) -> tuple:
        """
        Cập nhật góc servo dựa trên vị trí người
        
        Args:
            person_center: Tuple (x, y) tọa độ tâm người
            
        Returns:
            Tuple (pan_adjustment, tilt_adjustment) - điều chỉnh góc
        """
        if person_center is None:
            return (0, 0)
        
        error_x, error_y = self.calculate_error(person_center)
        
        # Áp dụng dead zone
        pan_adjustment = 0
        tilt_adjustment = 0
        
        if abs(error_x) > self.dead_zone_x:
            # Tính điều chỉnh Pan (người bên phải -> quay phải = góc dương)
            pan_adjustment = self.kp * error_x
            # Giới hạn tốc độ
            pan_adjustment = max(-self.max_speed, min(self.max_speed, pan_adjustment))
            
        if abs(error_y) > self.dead_zone_y:
            # Tính điều chỉnh Tilt (người ở trên -> ngẩng lên = góc dương)
            tilt_adjustment = self.kp * error_y
            tilt_adjustment = max(-self.max_speed, min(self.max_speed, tilt_adjustment))
        
        # Cập nhật góc servo
        self.pan_angle += pan_adjustment
        self.tilt_angle += tilt_adjustment
        
        # Giới hạn góc trong phạm vi cho phép
        self.pan_angle = max(self.pan_min, min(self.pan_max, self.pan_angle))
        self.tilt_angle = max(self.tilt_min, min(self.tilt_max, self.tilt_angle))
        
        return (pan_adjustment, tilt_adjustment)
    
    def get_servo_angles(self) -> tuple:
        """
        Lấy góc servo hiện tại
        
        Returns:
            Tuple (pan_angle, tilt_angle) theo độ
        """
        return (self.pan_angle, self.tilt_angle)

    def return_to_center_step(self, max_step: float = None) -> tuple:
        """
        Kéo servo về vị trí giữa (0, 0) theo từng bước.

        Args:
            max_step: Bước tối đa mỗi lần cập nhật (độ)

        Returns:
            Tuple (pan_delta, tilt_delta) đã áp dụng trong lần này
        """
        step = max_step if max_step is not None else self.max_speed
        step = max(0.1, float(step))

        pan_delta = 0.0
        tilt_delta = 0.0

        if self.pan_angle > 0:
            pan_delta = -min(step, self.pan_angle)
        elif self.pan_angle < 0:
            pan_delta = min(step, -self.pan_angle)

        if self.tilt_angle > 0:
            tilt_delta = -min(step, self.tilt_angle)
        elif self.tilt_angle < 0:
            tilt_delta = min(step, -self.tilt_angle)

        self.pan_angle += pan_delta
        self.tilt_angle += tilt_delta

        return (pan_delta, tilt_delta)

    def is_servo_near_origin(self, epsilon: float = 1.0) -> bool:
        """
        Kiểm tra servo đã gần vị trí giữa chưa.

        Args:
            epsilon: Ngưỡng sai số góc cho phép (độ)
        """
        eps = max(0.1, float(epsilon))
        return abs(self.pan_angle) <= eps and abs(self.tilt_angle) <= eps
    
    def get_direction_text(self) -> str:
        """
        Lấy mô tả hướng cần di chuyển
        
        Returns:
            String mô tả hướng
        """
        directions = []
        
        if abs(self.last_error_x) > self.dead_zone_x:
            if self.last_error_x > 0:
                directions.append("QUAY PHAI")
            else:
                directions.append("QUAY TRAI")
                
        if abs(self.last_error_y) > self.dead_zone_y:
            if self.last_error_y > 0:
                directions.append("NGẨNG LEN")
            else:
                directions.append("CUI XUONG")
        
        if not directions:
            return "DA CAN GIUA"
            
        return " + ".join(directions)
    
    def is_centered(self) -> bool:
        """
        Kiểm tra xem người đã ở giữa frame chưa
        
        Returns:
            True nếu người ở trong dead zone (đã căn giữa)
        """
        return (abs(self.last_error_x) <= self.dead_zone_x and 
                abs(self.last_error_y) <= self.dead_zone_y)
    
    def reset(self):
        """Reset servo về vị trí giữa"""
        self.pan_angle = 0.0
        self.tilt_angle = 0.0
        self.last_error_x = 0
        self.last_error_y = 0
        print("[Servo] Reset về vị trí giữa")
    
    def send_to_hardware(self):
        """
        Gửi góc servo đến hardware thật (placeholder)
        Trong demo này chỉ in ra console
        """
        # TODO: Thêm code điều khiển servo thật ở đây
        # Ví dụ: serial.write(f"PAN:{self.pan_angle},TILT:{self.tilt_angle}\n")
        pass


# Test module nếu chạy trực tiếp
if __name__ == "__main__":
    controller = SimulatedServoController(640, 480)
    
    # Test với các vị trí người khác nhau
    test_positions = [
        (320, 240),  # Giữa frame
        (500, 240),  # Bên phải
        (100, 240),  # Bên trái
        (320, 100),  # Phía trên
        (320, 400),  # Phía dưới
        (500, 100),  # Góc phải trên
    ]
    
    for pos in test_positions:
        adjustment = controller.update(pos)
        angles = controller.get_servo_angles()
        direction = controller.get_direction_text()
        print(f"Vị trí: {pos} -> Điều chỉnh: {adjustment} -> Góc: {angles} -> {direction}")
