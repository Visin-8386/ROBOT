# 🤖 ROBOT TỰ ĐỘNG THEO DÕI NGƯỜI LẠ - FILE NGỮ CẢNH VẼ SƠ ĐỒ

---

## **PHẦN 1: CẤU TRÚC CỤM HỆ THỐNG**

### **CLUSTER 1: THIẾT BỊ PHẦN CỨNG (xe theo dõi)**

#### **Thành phần 1.1 - Đầu ghi hình**
- **Tên**: ESP32-CAM (Camera Module)
- **Vị trí code**: `station/` (ESP-IDF C)
- **Chức năng**: Ghi hình, mã hóa JPEG, truyền stream
- **Thông số**:
  - Camera: OV3660 (640×480 pixels)
  - Tốc độ: 10-15 fps
  - Định dạng: JPEG
  - Kết nối: **TCP socket → Server (port 8765)**
  - Giao thức: `[4-byte big-endian length][JPEG data]`
- **Người nhận dữ liệu**: TCP Server (server.py port 8765)

#### **Thành phần 1.2 - Bộ điều khiển động cơ & cảm biến**
- **Tên**: ESP32 Motor Controller (SIN)
- **Vị trí code**: `SIN/` (ESP-IDF C)
- **Chức năng chính**: Điều khiển chuyển động, phát hiện chướng ngại, phát hiện chuyển động

**Chi tiết con:**

**1.2.1 - Driver động cơ**
- Driver: TB6612 (H-Bridge 2-channel)
- Loại: 2-wheel tank drive
- Motor A (Trái):
  - PWM Pin: 25 (tốc độ)
  - Pin điều khiển: 26, 27
- Motor B (Phải):
  - PWM Pin: 14 (tốc độ)
  - Pin điều khiển: 12, 13
- Tốc độ PWM: 20kHz, 8-bit (0-255)
- Mức tốc độ:
  - PATROL: 140
  - CHASE: 220
  - TURN: 240

**1.2.2 - Servo Pan (quay ngang)**
- Pin: 46
- Độ phân giải: 1000-2000 μs
  - 1500μs = center (0°)
  - 2000μs = left (~135°)
  - 1000μs = right (~45°)

**1.2.3 - Cảm biến VL53L0X ToF (khoảng cách)**
- Loại: Laser distance (Time-of-Flight)
- Giao tiếp: I2C (SDA=21, SCL=22, Address=0x29)
- Phạm vi: 260-500mm
- Chức năng:
  - 260mm: Hard stop (phanh)
  - 500mm: Soft avoidance (tránh khiến)

**1.2.4 - Cảm biến PIR (chuyển động)**
- Pin: 32
- Chức năng: Phát hiện chuyển động (alarm)
- Cooldown: 5000ms

**Kết nối từ 1.2**:
- **MQTT Client → MQTT Broker (mosquitto:1883)**
  - Subscribe: `robot/command`, `robot/alert`
  - Publish: `robot/position`, `robot/alert`

---

#### **Thành phần 1.3 - Cấu hình chung phần cứng**
- **File**: `shared_config.h`
- **WiFi**:
  - SSID: "Sin"
  - Password: "33333333"
- **Kết nối Server**:
  - Server IP: 172.20.10.2
  - Server Port TCP: 8765
- **MQTT Broker**:
  - URI: mqtt://172.20.10.2:1883
  - Username: robot
  - Password: robot123

---

### **CLUSTER 2: SERVER XỬ LÝ CHÍNH**

#### **Thành phần 2.1 - TCP Receiver**
- **File**: `server/server.py` (hàm TCP receiver)
- **Chức năng**: Nhận JPEG stream từ ESP32-CAM
- **Port**: 8765 (TCP)
- **Xử lý**:
  - Parse 4-byte length prefix
  - Đọc JPEG data
  - Đưa frame vào `frame_queue` (maxsize=2)
- **Người nhận tiếp**: YOLO Inference Thread

#### **Thành phần 2.2 - YOLO Inference Engine**
- **File**: `server/detector.py`
- **Class**: `PersonDetector`
- **Chức năng**: Phát hiện người & vật nuôi theo thời gian thực
- **Thông số**:
  - Model: YOLOv8n (nano)
  - Model file: `server/yolov8n.pt`
  - Confidence threshold: 0.35 (configurable)
  - Classes:
    - PERSON: 0
    - PET: 15 (cat), 16 (dog)

**2.2.1 - Preprocessing Pipeline** (`ImagePreprocessor`)
1. **GaussianBlur** (kernel=11): Giảm nhiễu ESP32-CAM
2. **CLAHE** (8×8 tile, clip_limit=2.0): Cân bằng ánh sáng (môi trường tối)
3. **Unsharp Mask**: Làm sắc nét cạnh biên

**2.2.2 - Detection Tracker** (`DetectionTracker`)
- **Chức năng**: Lọc dương tính giả
- **Logic**:
  - Cần ≥3 frame liên tiếp → xác nhận phát hiện
  - Cần 5 frame không phát hiện → reset trạng thái
  - Ngưỡng: confidence ≥ 0.35

#### **Thành phần 2.3 - Object Tracking (SORT)**
- **File**: `server/tracker.py`
- **Class**: `SORT`
- **Thuật toán**: Simple Online and Realtime Tracking
- **Thành phần con**:
  - **Kalman Filter**: Dự đoán chuyển động bounding box
  - **Hungarian Algorithm**: Gán detection → track ID
- **Tham số**:
  - `max_age`: 5 frame
  - `min_hits`: 1
  - `iou_threshold`: 0.3
- **Đầu ra**: Track ID ổn định

#### **Thành phần 2.4 - Servo Controller**
- **File**: `servo_controller.py`
- **Class**: `SimulatedServoController`
- **Input**: Trung tâm người (x, y) từ YOLO
- **Output**: pan_angle, tilt_angle → MQTT publish
- **Thuật toán**:
  - Proportional control
  - Dead zone: 30px (ngang), 20px (dọc)
  - Max speed: 2°/frame
  - Error: `error_x = person_x - frame_center_x`

#### **Thành phần 2.5 - MQTT Client**
- **Chức năng**: 2-way communication với robot
- **Broker**: mosquitto:1883 (creds: robot/robot123)
- **Topics**:
  - **Publish** (Server → Robot):
    - `robot/position`: {detected, x, y, pan, tilt, confidence, track_id}
    - Tần suất: ~10-15 Hz (match camera FPS)
  - **Subscribe** (Robot → Server):
    - `robot/command`: {action, pan, tilt}
    - `robot/alert`: {alert_type, distance_mm, pir, detail}

#### **Thành phần 2.6 - FastAPI Server**
- **File**: `server/api.py`
- **Port**: 8000
- **Endpoints**:
  - `GET /api/events` - Lịch sử phát hiện (pagination, filters)
  - `GET /api/events/{event_id}/image` - Ảnh phát hiện
  - `GET /api/status` - Trạng thái robot real-time
  - `POST /api/control` - Gửi lệnh (forward/backward/left/right/patrol/chase/monitor)
  - `GET /api/faces` - Danh sách khuôn mặt đã nhận dạng
  - `POST /api/faces` - Upload khuôn mặt mới
  - `POST /api/config/telegram` - Cấu hình Telegram
  - `GET /api/stream` - MJPEG live stream
  - `GET /api/health` - Health check

#### **Thành phần 2.7 - PostgreSQL Database**
- **Container**: postgres:16-alpine
- **Port**: 5432
- **URL**: `postgresql://robot:robot123@localhost:5432/robot`
- **File định nghĩa**: `server/database.py`

**Bảng:**
1. **detection_events**
   - timestamp, detected (bool), confidence, track_id
   - x, y (tọa độ trung tâm), pan, tilt (angle)
   - image_path (ảnh gốc)

2. **robot_status**
   - state (MONITOR/PATROL/CHASE/MANUAL/OFFLINE)
   - mqtt_connected, camera_connected (bool)
   - last_seen (timestamp)

3. **sensor_alerts**
   - alert_type: "pir", "distance", "camera", "status"
   - distance_mm (int), pir (bool)
   - acknowledged (bool), detail (text)

4. **settings**
   - key-value store (JSON)

---

#### **Thành phần 2.8 - MQTT Broker (Mosquitto)**
- **Container**: eclipse-mosquitto:2
- **Port**: 1883
- **Config file**: `mosquitto/mosquitto.conf`
- **Credentials**: robot / robot123
- **Topics manager**: Centre của communication system

#### **Thành phần 2.9 - Telegram Notifier**
- **File**: `server/telegram_notifier.py`
- **Class**: `TelegramNotifier`
- **Chức năng**: Gửi alert qua Telegram Bot
- **Thông số**:
  - Rate limit: cooldown 30s (configurable)
  - Gửi: ảnh + metadata (confidence, x, y, robot state)
- **Env vars**:
  - TELEGRAM_BOT_TOKEN
  - TELEGRAM_CHAT_ID
  - TELEGRAM_ENABLED
  - TELEGRAM_COOLDOWN

---

### **CLUSTER 3: MÔ HÌNH ML (DỮ LIỆU - HUẤN LUYỆN - SỬ DỤNG)**

#### **Thành phần 3.1 - Input Data (Dữ liệu)**

**3.1.1 - Nguồn dữ liệu**
- **Source**: ESP32-CAM JPEG stream
- **Tốc độ**: 10-15 fps (ideal: 25-60 fps)
- **Định dạng**: JPEG, 640×480 pixels
- **Lưu trữ gốc**: Frame queue (maxsize=2, real-time)

**3.1.2 - Lưu trữ lâu dài**
- **Interval**: Mỗi 5 giây lưu 1 frame
- **Location**: `./images/` (annotated JPEG) + PostgreSQL (metadata)
- **Metadata**: timestamp, detection info, path

#### **Thành phần 3.2 - Data Preprocessing**

**3.2.1 - Denoising**
- **Method**: GaussianBlur
- **Kernel**: 11×11
- **Mục đích**: Giảm noise từ ESP32-CAM low-quality sensor

**3.2.2 - Contrast Enhancement**
- **Method**: CLAHE (Contrast Limited Adaptive Histogram Equalization)
- **Tile grid**: 8×8 blocks
- **Clip limit**: 2.0
- **Mục đích**: Cải thiện khả năng phát hiện trong ánh sáng yếu

**3.2.3 - Sharpening**
- **Method**: Unsharp Mask
- **Mục đích**: Khôi phục cạnh biên, tăng độ sắc nét người

#### **Thành phần 3.3 - Data Split (Phân chia dữ liệu)**

**Tỷ lệ phân chia**:
- **Training**: 70% (2800 ảnh)
  - Mục đích: Huấn luyện mô hình
- **Validation**: 15% (600 ảnh)
  - Mục đích: Kiểm chứng hiệu suất trong quá trình training
- **Test**: 15% (600 ảnh)
  - Mục đích: Đánh giá cuối cùng, độ tin cậy

**Cân bằng lớp**:
- PERSON (class 0): Ưu tiên (80%)
- PET cat (class 15): Bổ sung (10%)
- PET dog (class 16): Bổ sung (10%)
- Background: Tối thiểu (<10%)

#### **Thành phần 3.4 - Mô hình Detection (YOLOv8n)**

**3.4.1 - Model Info**
- **Architecture**: YOLOv8 (Ultralytics nano variant)
- **Pre-trained**: Yes (`server/yolov8n.pt`)
- **Tính năng**: Nhẹ, phù hợp real-time ở edge device
- **Input**: 640×480 JPEG từ preprocessing
- **Output**: Bounding boxes + confidence scores

**3.4.2 - Inference Parameters**
- **Confidence threshold**: 0.35 (default, configurable via API)
- **Classes đang sử dụng**:
  - PERSON_CLASS_ID = 0
  - PET_CAT = 15
  - PET_DOG = 16

**3.4.3 - Post-processing**
- **Detection Filter** (`DetectionTracker`):
  - Yêu cầu ≥3 frame liên tiếp → xác nhận (filter noise)
  - Yêu cầu 5 frame blank → reset
  - Giữ lại: confidence ≥ 0.35

#### **Thành phần 3.5 - Object Tracking (SORT)**

**3.5.1 - Thuật toán**
- **Name**: Simple Online and Realtime Tracking
- **Purpose**: Gán stable track ID cho mỗi person

**3.5.2 - Thành phần con**
- **Kalman Filter**: `SimpleKalman` class
  - Dự đoán motion của bounding box
  - Update khi có new detection
- **Hungarian Algorithm**: Gán detection → track ID
  - Minimize cost (IOU distance)

**3.5.3 - Tham số**
- `max_age`: 5 (frame)
- `min_hits`: 1 (yêu cầu 1 hit → confirmed)
- `iou_threshold`: 0.3

**3.5.4 - Output**
- **Track ID**: Stable identifier per person
- **Bbox**: Bounding box update per frame
- **Age**: Số frame mà track đã tồn tại

#### **Thành phần 3.6 - Face Recognition Engine (Optional)**

**3.6.1 - Architecture** (`server/face_recognition_engine.py`)
- **Engine**: InsightFace (ONNX Runtime)
- **Device preference**: CUDA/GPU > CPU
- **Disable on CPU**: Yes (via FACE_DISABLE_ON_CPU)

**3.6.2 - Thành phần con**

**Face Detection** (SCRFD):
- **Purpose**: Tìm khuôn mặt trong crop người
- **Output**: BBox khuôn mặt + confidence

**Face Embedding** (ArcFace):
- **Purpose**: Tạo vector đặc trưng (512-dim)
- **Output**: 512-dimensional embedding vector
- **Training data**: Được tính từ known_faces dataset

**Face Matching**:
- **Method**: Cosine similarity
- **Match threshold**: 0.65 (configurable)
- **Cache**: 2 giây TTL (không re-process khuôn mặt giống)

**3.6.3 - Training Data** (`server/known_faces/embeddings.npz`)

**Format**: NumPy `.npz` file
- **Cấu trúc**: {person_name → np.array([512-dim float array])}
- **Tạo lập**: Script `server/build_face_embeddings.py`
  - Scan thư mục `known_faces/`
  - Extract ArcFace embeddings
  - Save `.npz`

**3.6.4 - Inference Pipeline**
1. Crop person từ YOLO detection
2. Phát hiện khuôn mặt (SCRFD)
3. Generate embedding per face (ArcFace)
4. Compare với known_faces embeddings
5. Match nếu similarity ≥ 0.65
6. Cache result (2s TTL)

**3.6.5 - Configuration**
- `FACE_RECOGNITION_ENABLED`: Toggle on/off
- `FACE_DISABLE_ON_CPU`: Disable nếu CPU-only
- `FACE_SIMILARITY_THRESHOLD`: 0.65
- `FACE_DET_SIZE`: 320 (detection input)
- `FACE_MAX_CROP_SIDE`: 320
- `FACE_MATCH_INTERVAL`: 3 (check mỗi 3 frame)
- `FACE_MAX_MATCH_PERSONS`: 2 (max persons/frame)
- `FACE_CACHE_TTL`: 2.0 (seconds)

---

### **CLUSTER 4: ĐIỀU KHIỂN & HÀNH ĐỘNG ROBOT**

#### **Thành phần 4.1 - Servo Control Algorithm**

**Input**:
- Person center (x, y) từ YOLO detection
- Frame center: (320, 240) cho 640×480

**Algorithm** (`SimulatedServoController`):
```
error_x = person_x - frame_center_x (320)
error_y = person_y - frame_center_y (240)

if abs(error_x) < dead_zone_x (30px):
    action = FORWARD
else:
    if error_x > 0:
        action = TURN_RIGHT
        turn_speed = abs(error_x) / max_error
    else:
        action = TURN_LEFT
        turn_speed = abs(error_x) / max_error

pan_angle = proportional_control(error_x, max_speed=2°/frame)
tilt_angle = proportional_control(error_y, max_speed=2°/frame)
```

#### **Thành phần 4.2 - Robot Motor Response** (SIN nhận MQTT robot/position)

**MQTT Message từ Server**:
```json
{
  "detected": true,
  "x": 320,
  "y": 240,
  "pan": 12.5,
  "tilt": -5.0,
  "confidence": 0.87,
  "track_id": 1
}
```

**Logic hành động**:
1. **Pan error < dead_zone** → Move forward (speed 140-220)
2. **Pan error > 0** → Turn right (speed proportional)
3. **Pan error < 0** → Turn left (speed proportional)
4. **Distance (VL53L0X) < 260mm** → Brake (hard stop)
5. **Distance 260-500mm** → Reduce speed (soft avoidance)
6. **PIR triggered** → Alert publish MQTT

#### **Thành phần 4.3 - Sensor Feedback** (ESP32 SIN → Server)

**MQTT robot/alert**:
```json
{
  "alert_type": "pir|distance|status",
  "distance_mm": 450,
  "pir": true,
  "detail": "Obstacle detected"
}
```

---

### **CLUSTER 5: CHẾ ĐỘ HOẠT ĐỘNG ROBOT**

| Chế độ | Hành vi | Trigger | Stop Condition |
|-------|--------|---------|---|
| **MONITOR** | Đứng yên, monitor PIR, gửi cảnh báo | Khởi động mặc định | Lệnh patrol/manual |
| **PATROL** | Tự động tuần tra, tránh chướng ngại, tìm người | `robot/command` action="patrol" | Phát hiện person → CHASE |
| **CHASE** | Theo dõi person, lock-on, điều khiển servo | Auto khi person detected in PATROL | Mất person detection |
| **MANUAL** | Điều khiển trực tiếp (WASD / button) | `robot/command` action="manual" | Lệnh dừng / chế độ khác |
| **OFFLINE** | Không kết nối | Tự động phát hiện | Kết nối lại |

---

### **CLUSTER 6: GIAO DIỆN NGƯỜI DÙNG (UI)**

#### **Thành phần 6.1 - Web Dashboard**
- **URL**: http://localhost:8000
- **File**: `server/static/` (HTML/JS/CSS)
- **Backend**: FastAPI server (port 8000)

**Chức năng**:
- **Live Stream**: MJPEG từ annotated frames (30fps)
- **Control Panel**: WASD / arrow keys / buttons
  - Forward, Backward, Left, Right, Stop
  - Mode: MONITOR, PATROL, CHASE, MANUAL
- **Detection History**: Paginated events with images
- **Robot Status**: Real-time state, connections, FPS
- **Sensor Alerts**: PIR, distance, camera status
- **Settings**:
  - Telegram config (token, chat_id, cooldown)
  - Confidence threshold (0.1 - 1.0)
  - Model selection

#### **Thành phần 6.2 - Mobile App (Flutter)**
- **Location**: `flutter_application/`
- **Language**: Dart
- **Platforms**: Android, iOS, Web

**Dependencies** (`pubspec.yaml`):
- `http`: REST API calls
- `shared_preferences`: Local cache
- `flutter_local_notifications`: Push alerts
- `image_picker`: Face training upload
- `cupertino_icons`: iOS UI

**Features**:
- Remote control (forward/backward/left/right)
- Mode selection (patrol/chase)
- Detection history viewer with images
- Real-time robot status (state, signal)
- Telegram settings UI
- Face training: upload training photos

---

## **PHẦN 2: LUỒNG DỮ LIỆU & KẾT NỐI**

### **Luồng processing chính (1 cycle phát hiện)**

```
[1] CAPTURE (5-15ms)
    ESP32-CAM → JPEG encode → TCP packet
    Format: [4-byte big-endian length][JPEG data]

[2] TRANSMIT (15-30ms)
    TCP → server:8765
    Frame → frame_queue (maxsize=2, oldest dropped if full)

[3] YOLO INFERENCE (30-50ms)
    Fetch latest frame from frame_queue
    ↓
    Preprocessing:
    - GaussianBlur (11×11)
    - CLAHE (8×8, clip=2.0)
    - Unsharp Mask
    ↓
    YOLOv8n.detect() on 640×480
    Output: bboxes, confidence scores, class IDs

[4] TRACKING & FILTERING (5-10ms)
    SORT tracker: assign track IDs
    DetectionTracker: confirm après 3 frame
    Output: stable track_id per person

[5] FACE RECOGNITION (async, 100-200ms per 3rd frame)
    If FACE_MATCH_INTERVAL hit:
    - Crop faces from person bbox
    - SCRFD detection
    - ArcFace embedding (512-dim)
    - Cosine similarity vs embeddings.npz
    - Cache result (2s TTL)
    Output: FaceMatch(name, similarity, is_known)

[6] SERVO CALCULATION (5ms)
    SimulatedServoController.update(person_center)
    error_x = person_x - 320
    error_y = person_y - 240
    ↓
    Proportional control with dead zone
    ↓
    Output: pan_angle, tilt_angle

[7] MQTT PUBLISH (5ms)
    Topic: robot/position
    Payload: {detected, x, y, pan, tilt, confidence, track_id}
    QoS: 1, Frequency: ~10-15 Hz

[8] ROBOT ACTION (ESP32 SIN receives)
    Parse MQTT robot/position
    ↓
    Pan error < dead_zone → Move forward
    Pan error > 0 → Turn right (proportional)
    Pan error < 0 → Turn left (proportional)
    ↓
    VL53L0X distance check:
    - < 260mm → Hard stop (brake)
    - 260-500mm → Reduce speed
    ↓
    PIR check: publish robot/alert if triggered

[9] DATABASE SAVE (5-10ms, every 5 second)
    Save: timestamp, detected bool, confidence, x, y, pan, tilt
    Save: annotated JPEG to ./images/
    Save: Insert row to detection_events table

[10] TELEGRAM NOTIFICATION (rate-limited 30s)
     On detection trigger:
     - Fetch annotated image
     - Prepare message: confidence, position, state
     - Send via Telegram Bot API
     - Update cooldown timer

[11] WEB DASHBOARD STREAM
     Annotated JPEG → HTTP MJPEG
     Frequency: ~10-15 Hz
     Clients can connect to /api/stream
```

### **Protocol & Communication Matrix**

| Kết nối | Protocol | Port | Direction | Định dạng | Tần suất |
|---------|----------|------|-----------|-----------|----------|
| ESP32-CAM → Server | TCP | 8765 | One-way | `[len][JPEG]` | 10-15 fps |
| Server ↔ Motor | MQTT | 1883 | Two-way | JSON | Real-time |
| Server → Web/Mobile | HTTP | 8000 | One-way | REST/MJPEG | On-demand |
| Server → Telegram | HTTPS | 443 | One-way | JSON | Rate-limited |

---

## **PHẦN 3: DEPLOYMENT & INFRASTRUCTURE**

### **Docker Compose Stack** (`server/docker-compose.yml`)

**Service 1: PostgreSQL Database**
- **Image**: postgres:16-alpine
- **Container name**: robot_db
- **Port**: 5432
- **Volume**: pg_data (persistent)
- **Env vars**:
  - POSTGRES_USER: robot
  - POSTGRES_PASSWORD: robot123
  - POSTGRES_DB: robot
- **Health check**: pg_isready -U robot

**Service 2: MQTT Broker**
- **Image**: eclipse-mosquitto:2
- **Container name**: mqtt_broker
- **Port**: 1883
- **Volume**: mosquitto/mosquitto.conf
- **Auth**: robot / robot123
- **Depends on**: None

**Service 3: Detection Server**
- **Build**: ./Dockerfile
- **Container name**: detection_server
- **Ports**: 8765 (TCP), 8000 (HTTP)
- **Depends on**: postgres (healthy), mosquitto (healthy)
- **Volumes**:
  - ./images: Detection output
  - ./model: Pre-trained weights
  - ./known_faces: Face embeddings
- **Env vars**:
  - MQTT_BROKER: mosquitto:1883
  - DATABASE_URL: postgresql://robot:robot123@postgres:5432/robot
  - TELEGRAM_BOT_TOKEN: {env}
  - TELEGRAM_CHAT_ID: {env}
  - TELEGRAM_ENABLED: true
  - TELEGRAM_COOLDOWN: 30

**Volumes**:
- `pg_data`: PostgreSQL data persistence
- `detection_images`: Saved detection frames

---

## **PHẦN 4: FILE MAPPING**

### **Cấu trúc thư mục chi tiết**

```
ROBOT/
│
├── [CLUSTER 1: HARDWARE]
│   ├── station/                 # ESP32-CAM firmware
│   │   ├── main/
│   │   │   ├── main.c
│   │   │   ├── camera_stream_httpd.c/h
│   │   │   ├── ws_sender.c/h
│   │   │   └── config.h
│   │   └── CMakeLists.txt
│   │
│   ├── SIN/                      # ESP32 Motor firmware
│   │   ├── main/
│   │   │   ├── main.c
│   │   │   ├── motor.c/h
│   │   │   ├── sensor.c/h
│   │   │   ├── servo.c/h
│   │   │   ├── mqtt_client_app.c/h
│   │   │   └── config.h
│   │   └── CMakeLists.txt
│   │
│   └── shared_config.h           # WiFi + Server IP shared config
│
├── [CLUSTER 2: SERVER]
│   ├── server/
│   │   ├── server.py             # Main orchestrator (TCP, YOLO, MQTT, FastAPI)
│   │   ├── config.py             # Server configuration
│   │   ├── api.py                # FastAPI REST endpoints
│   │   ├── database.py           # SQLAlchemy models + DB init
│   │   ├── detector.py           # [CLUSTER 3] YOLOv8 + SORT
│   │   ├── tracker.py            # [CLUSTER 3] SORT algorithm
│   │   ├── face_recognition_engine.py  # [CLUSTER 3] Face ID
│   │   ├── build_face_embeddings.py    # [CLUSTER 3] Train data builder
│   │   ├── servo_controller.py   # [CLUSTER 4] Servo control
│   │   ├── telegram_notifier.py  # Telegram alerts
│   │   ├── requirements.txt
│   │   ├── Dockerfile
│   │   ├── docker-compose.yml
│   │   ├── yolov8n.pt            # [CLUSTER 3] Pre-trained model
│   │   ├── static/               # [CLUSTER 6] Web Dashboard
│   │   ├── known_faces/          # [CLUSTER 3] Face training data
│   │   └── mosquitto/            # MQTT broker config
│   │
│   ├── servo_controller.py       # Top-level servo simulation
│   └── requirements.txt
│
├── [CLUSTER 5: UI]
│   ├── flutter_application/      # Mobile app
│   │   ├── lib/
│   │   ├── pubspec.yaml
│   │   ├── android/
│   │   ├── ios/
│   │   └── web/
│   │
│   └── [Web Dashboard in server/static/]
│
└── [DOCS]
    ├── README.md
    ├── TONG_QUAN_QUY_TRINH_HE_THONG.md
    ├── terminal_rules.md
    └── project_flowcharts.md
```

---

## **PHẦN 5: TÓMLƯỢC CHO VẼ SƠ ĐỒ**

### **5 CỤM CHÍNH**

1. **Hardware (Xe theo dõi)**
   - ESP32-CAM (ghi hình)
   - ESP32 Motor (động cơ, cảm biến)

2. **Server (Xử lý)**
   - TCP Receiver
   - YOLO Inference
   - MQTT Broker
   - PostgreSQL DB
   - FastAPI Web

3. **ML Model (Dữ liệu & Huấn luyện)**
   - Preprocessing (denoise, CLAHE, sharpen)
   - YOLOv8n Detection
   - SORT Tracking
   - Face Recognition (optional)

4. **Control (Điều khiển)**
   - Servo Calculator
   - Motor Commands via MQTT

5. **UI (Giao diện)**
   - Web Dashboard
   - Mobile App (Flutter)
   - Telegram Bot

### **LUỒNG CHÍNH**

```
ESP32-CAM (TCP)
    ↓
Server TCP Receiver (port 8765)
    ↓
YOLO Inference + SORT Tracking + Face ID
    ↓
Servo Control (Proportional + Dead zone)
    ↓
MQTT Publish `robot/position` (mosquitto:1883)
    ↓
ESP32 Motor (SIN) Receives
    ↓
Motor Control + Sensor Feedback
    ↓
(Parallel) Database Save + Telegram Alert + Web Stream
```

### **CÁC KÊNH GIAO TIẾP**

1. **TCP**: ESP32-CAM → Server (JPEG stream)
2. **MQTT**: Server ↔ Robot (commands & telemetry)
3. **HTTP**: Server ← Web/Mobile (API + stream)
4. **HTTPS**: Server → Telegram (alerts)
5. **PostgreSQL**: Server ← → Database (events & status)

---

## **PHẦN 6: KEY CONFIGURATION PARAMETERS**

### **Hardware (shared_config.h)**
- WiFi SSID: "Sin"
- Server IP: 172.20.10.2
- MQTT Broker: mqtt://172.20.10.2:1883

### **Server (server/config.py)**
- TCP Port: 8765
- API Port: 8000
- TCP Timeout: 60s
- Frame Queue Size: 2
- Image Save Interval: 5s

### **YOLO (server/detector.py)**
- Confidence Threshold: 0.35
- CLAHE Tile: 8×8
- CLAHE Clip: 2.0
- GaussianBlur Kernel: 11

### **SORT (server/tracker.py)**
- max_age: 5
- min_hits: 1
- iou_threshold: 0.3

### **Servo (servo_controller.py)**
- Dead zone X: 30px
- Dead zone Y: 20px
- Max speed: 2°/frame

### **Face Recognition (face_recognition_engine.py)**
- Enabled: configurable
- Similarity Threshold: 0.65
- Match Interval: 3 frames
- Cache TTL: 2.0 seconds

### **Telegram (telegram_notifier.py)**
- Enabled: configurable
- Cooldown: 30 seconds
- Requires: BOT_TOKEN, CHAT_ID

---

**End of Context File**
