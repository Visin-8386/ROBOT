# Robot Security System

Hệ thống robot an ninh tự động sử dụng ESP32, Camera AI (YOLOv8), MQTT và Web Dashboard.

## Kiến trúc hệ thống

```
ESP32-CAM (station/)          ESP32 Motor (SIN/)
   │ TCP :8765                    │ MQTT
   ▼                              ▼
┌──────────────────────────────────────┐
│         Server (server/)             │
│  ┌──────────┐  ┌──────────────────┐  │
│  │ YOLO AI  │  │ FastAPI :8000    │  │
│  │ Detect   │  │ Web Dashboard    │  │
│  └──────────┘  └──────────────────┘  │
│  ┌──────────┐  ┌──────────────────┐  │
│  │ MQTT     │  │ PostgreSQL       │  │
│  │ :1883    │  │ :5432            │  │
│  └──────────┘  └──────────────────┘  │
└──────────────────────────────────────┘
         │
         ▼
   Web Browser (localhost:8000)
```

## Chế độ hoạt động

| Chế độ | Mô tả |
|--------|--------|
| **MONITOR** (mặc định) | Robot đứng yên, giám sát bằng Camera/PIR/ToF → gửi cảnh báo lên web |
| **PATROL** | Tự tuần tra quanh nhà, tránh vật cản, phát hiện người → CHASE |
| **CHASE** | Đuổi theo người dựa trên vị trí từ Camera AI |
| **MANUAL** | Điều khiển trực tiếp từ web (WASD / mũi tên) |

## Thành phần

### ESP32-CAM (`station/`)
- Chụp ảnh JPEG → gửi TCP tới server
- Protocol: `[4-byte big-endian length][JPEG data]`

### ESP32 Motor Controller (`SIN/`)
- Điều khiển motor TB6612 (2 bánh tank-drive)
- Sensor: VL53L0X (laser distance) + PIR (motion)
- Nhận lệnh qua MQTT, gửi cảnh báo sensor lên MQTT

### Server (`server/`)
- **TCP receiver**: nhận frame từ ESP32-CAM
- **YOLO AI**: phát hiện người, tính góc pan/tilt
- **MQTT**: gửi vị trí người + nhận cảnh báo sensor
- **FastAPI**: REST API + Web Dashboard
- **PostgreSQL**: lưu detection events + sensor alerts

## Cài đặt & Chạy

### Chạy bằng Docker (khuyên dùng)

```bash
cd server
docker-compose up --build
```

Truy cập web dashboard: **http://localhost:8000**

### Chạy thủ công

```bash
# 1. Khởi động DB + MQTT
cd server
docker-compose up postgres mosquitto -d

# 2. Cài dependencies
pip install -r requirements.txt

# 3. Chạy server
python server.py
```

### Build ESP32 (ESP-IDF)

```bash
# ESP32-CAM
cd station
idf.py build flash monitor

# ESP32 Motor
cd SIN
idf.py build flash monitor
```

## Cấu hình

| File | Mô tả |
|------|--------|
| `server/config.py` | Server, MQTT, DB, YOLO config |
| `SIN/main/config.h` | WiFi, MQTT broker IP, motor pins, speed, sensor thresholds |
| `station/main/config.h` | WiFi, server IP/port, camera settings |

## Điều khiển từ Web

- **Nút ▲▼◀▶**: di chuyển robot
- **Phím W/A/S/D**: di chuyển robot
- **Phím 1/2/3**: chuyển chế độ Monitor/Patrol/Chase
- **Space**: dừng
- Camera stream real-time
- Cảnh báo sensor trực tiếp (PIR, khoảng cách)
- Lịch sử phát hiện người + ảnh

## MQTT Topics

| Topic | Hướng | Mô tả |
|-------|-------|--------|
| `robot/position` | Server → ESP32 | Vị trí người `{detected, x, y, pan, tilt}` |
| `robot/command` | Server → ESP32 | Lệnh điều khiển `{action}` |
| `robot/alert` | ESP32 → Server | Cảnh báo sensor `{type, detail, distance_mm, pir}` |

## API Endpoints

| Method | URL | Mô tả |
|--------|-----|--------|
| GET | `/` | Web Dashboard |
| GET | `/api/status` | Trạng thái robot |
| GET | `/api/stats` | Thống kê |
| GET | `/api/events` | Lịch sử detection |
| GET | `/api/alerts` | Lịch sử cảnh báo sensor |
| GET | `/api/alerts/latest` | Cảnh báo mới nhất (real-time) |
| GET | `/api/stream` | MJPEG camera stream |
| POST | `/api/control?action=xxx` | Gửi lệnh điều khiển |
