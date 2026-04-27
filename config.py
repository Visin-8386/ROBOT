# ==========================================
# CẤU HÌNH HỆ THỐNG PHÁT HIỆN NGƯỜI VÀ SERVO
# ==========================================

# ----- Camera Configuration -----
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30

# ----- YOLO Model Configuration -----
# Sử dụng YOLOv8x cho độ chính xác cao nhất
# Các tùy chọn: yolov8n, yolov8s, yolov8m, yolov8l, yolov8x
YOLO_MODEL = "yolov8n.pt"
CONFIDENCE_THRESHOLD = 0.5  # Ngưỡng tin cậy để chấp nhận detection
PERSON_CLASS_ID = 0  # Class ID của người trong COCO dataset

# ----- Servo Configuration -----
# Góc servo (độ)
SERVO_PAN_MIN = -90   # Góc quay trái tối đa
SERVO_PAN_MAX = 90    # Góc quay phải tối đa
SERVO_TILT_MIN = -45  # Góc ngẩng xuống tối đa
SERVO_TILT_MAX = 45   # Góc ngẩng lên tối đa

# Điều khiển PID (chỉ dùng P trong demo này)
SERVO_KP = 0.1  # Hệ số tỉ lệ cho bộ điều khiển P

# Dead zone - không điều chỉnh nếu sai số nhỏ hơn giá trị này (pixels)
DEAD_ZONE_X = 30
DEAD_ZONE_Y = 20

# Tốc độ di chuyển servo tối đa (độ/frame)
MAX_SERVO_SPEED = 5

# ----- Tracking Flow (servo -> xe -> servo reset) -----
# Số frame liên tiếp phải ở giữa trước khi ra lệnh xe quay
CENTER_STABLE_FRAMES = 3
# Chỉ quay xe khi góc pan đủ lớn (độ)
CAR_ROTATE_MIN_ANGLE = 8
# Tốc độ trả servo về góc 0 (độ/frame)
SERVO_RETURN_SPEED = 4
# Sai số cho phép xem như servo đã về gốc (độ)
SERVO_RETURN_EPSILON = 1.0

# ----- Visualization -----
BOX_COLOR = (0, 255, 0)      # Màu bounding box (BGR)
CENTER_COLOR = (0, 0, 255)   # Màu crosshair tâm frame
ARROW_COLOR = (255, 0, 255)  # Màu mũi tên chỉ hướng
TEXT_COLOR = (255, 255, 255) # Màu chữ
