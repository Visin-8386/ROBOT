# ==========================================
# CẤU HÌNH HỆ THỐNG — sửa tại đây
# ==========================================
# Local: dùng giá trị mặc định
# Docker: tự đọc từ environment variables

import os

# ----- Server -----
SERVER_HOST = "0.0.0.0"
SERVER_PORT = int(os.getenv("SERVER_PORT", "8765"))
API_PORT = int(os.getenv("API_PORT", "8000"))
TCP_CLIENT_TIMEOUT = float(os.getenv("TCP_CLIENT_TIMEOUT", "60"))

# ----- MQTT Broker -----
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "robot")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "robot123")
MQTT_TOPIC = "robot/position"
MQTT_COMMAND_TOPIC = "robot/command"
MQTT_ALERT_TOPIC = "robot/alert"
MQTT_CLIENT_ID = "detection_server"

# ----- Database -----
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://robot:robot123@localhost:5432/robot")

# ----- Image Storage -----
IMAGE_STORAGE_PATH = os.getenv("IMAGE_STORAGE_PATH", "./images")
IMAGE_SAVE_INTERVAL = 5  # Lưu tối đa 1 ảnh mỗi 5 giây

# ----- Headless Mode -----
HEADLESS = os.getenv("HEADLESS", "1") == "1"

# ----- YOLO -----
YOLO_MODEL = "yolov8n.pt"
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.35"))
YOLO_PREPROCESS_ENABLED = os.getenv("YOLO_PREPROCESS_ENABLED", "1") == "1"

# ----- Face Recognition -----
FACE_RECOGNITION_ENABLED = os.getenv("FACE_RECOGNITION_ENABLED", "1") == "1"
FACE_DISABLE_ON_CPU = os.getenv("FACE_DISABLE_ON_CPU", "1") == "1"
FACE_EMBEDDINGS_PATH = os.getenv("FACE_EMBEDDINGS_PATH", "./known_faces/embeddings.npz")
FACE_SIMILARITY_THRESHOLD = float(os.getenv("FACE_SIMILARITY_THRESHOLD", "0.65"))
FACE_MATCH_INTERVAL = int(os.getenv("FACE_MATCH_INTERVAL", "3"))
FACE_MAX_MATCH_PERSONS = int(os.getenv("FACE_MAX_MATCH_PERSONS", "2"))
FACE_CACHE_TTL = float(os.getenv("FACE_CACHE_TTL", "2.0"))
FACE_DET_SIZE = int(os.getenv("FACE_DET_SIZE", "320"))
FACE_MAX_CROP_SIDE = int(os.getenv("FACE_MAX_CROP_SIDE", "320"))
FACE_UNKNOWN_RETRY_SEC = float(os.getenv("FACE_UNKNOWN_RETRY_SEC", "1.2"))

# Class IDs
PERSON_CLASS_ID = 0
PET_CLASS_IDS = [15, 16]  # 15: cat, 16: dog

# ----- Camera -----
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480

# ----- Servo (simulated) -----
SERVO_PAN_MIN = -90
SERVO_PAN_MAX = 90
SERVO_TILT_MIN = -45
SERVO_TILT_MAX = 45
SERVO_KP = 0.05
DEAD_ZONE_X = 30
DEAD_ZONE_Y = 20
MAX_SERVO_SPEED = 2

# ----- Telegram Notification -----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "0") == "1"
TELEGRAM_COOLDOWN = int(os.getenv("TELEGRAM_COOLDOWN", "30"))  # Giây giữa 2 lần gửi

# ----- Visualization -----
BOX_COLOR = (0, 255, 0)
CENTER_COLOR = (0, 0, 255)
ARROW_COLOR = (255, 0, 255)
TEXT_COLOR = (255, 255, 255)
