# Robot Security System

Hệ thống robot an ninh tích hợp AI nhận diện người, điều khiển robot qua MQTT, giám sát thời gian thực trên Web Dashboard và lưu lịch sử sự kiện vào PostgreSQL.

## Mục lục

- [1. Tổng quan](#1-tổng-quan)
- [2. Kiến trúc hệ thống](#2-kiến-trúc-hệ-thống)
- [3. Tính năng chính](#3-tính-năng-chính)
- [4. Cấu trúc dự án](#4-cấu-trúc-dự-án)
- [5. Yêu cầu hệ thống](#5-yêu-cầu-hệ-thống)
- [6. Khởi động nhanh](#6-khởi-động-nhanh)
- [7. Cấu hình quan trọng](#7-cấu-hình-quan-trọng)
- [8. API và MQTT contract](#8-api-và-mqtt-contract)
- [9. Build firmware ESP32](#9-build-firmware-esp32)
- [10. Tài liệu nội bộ](#10-tài-liệu-nội-bộ)
- [11. Troubleshooting](#11-troubleshooting)

## 1. Tổng quan

Robot Security System gồm 3 khối chính:

- **Station (ESP32-CAM)**: gửi frame JPEG về server qua TCP.
- **SIN (ESP32 điều khiển chuyển động)**: nhận lệnh MQTT, đọc sensor, phát cảnh báo.
- **Server (FastAPI + AI + DB)**: nhận ảnh, chạy YOLO, điều phối robot, hiển thị dashboard, lưu lịch sử.

Mục tiêu của hệ thống là giám sát tự động, phản ứng theo tình huống và hỗ trợ điều khiển thủ công từ giao diện web.

## 2. Kiến trúc hệ thống

```text
ESP32-CAM (station/)                 ESP32 Motor (SIN/)
  TCP frame :8765                           MQTT client
        │                                        │
        └──────────────┐             ┌───────────┘
                       ▼             ▼
              ┌──────────────────────────────┐
              │       Server (server/)       │
              │  - TCP Receiver              │
              │  - YOLO Detection            │
              │  - MQTT Publisher/Subscriber │
              │  - FastAPI + Dashboard       │
              │  - PostgreSQL persistence    │
              └──────────────────────────────┘
                          │
                          ▼
                 Browser (http://localhost:8000)
```

### Luồng dữ liệu chính

1. `station/` gửi JPEG về TCP server.
2. `server/` detect người, tính vị trí và publish MQTT.
3. `SIN/` nhận lệnh điều khiển và gửi trạng thái/sensor alert.
4. Dashboard hiển thị stream, trạng thái và lịch sử sự kiện.

## 3. Tính năng chính

- Phát hiện người thời gian thực bằng YOLO.
- Điều khiển robot theo chế độ vận hành (Monitor, Patrol, Chase, Manual).
- Dashboard điều khiển trực tiếp bằng nút và phím tắt.
- Lưu lịch sử detection/alert vào PostgreSQL.
- Tích hợp nhận diện khuôn mặt (InsightFace) ở phía server.
- Hỗ trợ thông báo Telegram (tùy chọn qua biến môi trường).

## 4. Cấu trúc dự án

```text
ROBOT/
├─ server/                 # Backend FastAPI, AI detection, DB, MQTT
├─ station/                # ESP32-CAM firmware
├─ SIN/                    # ESP32 motor/sensor firmware
├─ flutter_application/    # Ứng dụng Flutter (nếu dùng)
├─ docs/                   # Tài liệu dự án, flowchart, slide
├─ notebooks/              # Notebook phân tích/thử nghiệm
├─ tools/notebook/         # Script tiện ích cho notebook
├─ docker-compose.yml      # Compose root (hạ tầng cơ bản)
└─ README.md
```

## 5. Yêu cầu hệ thống

### Server

- Docker + Docker Compose (khuyến nghị)
- Hoặc Python 3.10+ nếu chạy local

### Firmware

- ESP-IDF phù hợp với `station/` và `SIN/`
- Toolchain build cho ESP32/ESP32-CAM

## 6. Khởi động nhanh

### Cách 1: Chạy full stack bằng Docker (khuyến nghị)

```bash
cd server
docker-compose up --build
```

Sau khi chạy:

- Dashboard: `http://localhost:8000`
- TCP receiver: `localhost:8765`
- MQTT broker: `localhost:1883`
- PostgreSQL: `localhost:5432`

### Cách 2: Chạy server local + dịch vụ bằng Docker

```bash
cd server

# 1) Khởi động DB + MQTT
docker-compose up postgres mosquitto -d

# 2) Cài dependencies
pip install -r requirements.txt

# 3) Chạy backend
python server.py
```

## 7. Cấu hình quan trọng

### File cấu hình chính

- `server/config.py`: cổng server, MQTT, DB URL, YOLO threshold, face recognition, Telegram.
- `SIN/main/config.h`: Wi-Fi, broker MQTT, chân GPIO motor/sensor, ngưỡng cảm biến.
- `station/main/config.h`: Wi-Fi, địa chỉ server TCP, tham số camera.

### Biến môi trường quan trọng (server)

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `MQTT_BROKER` | `localhost` | Địa chỉ MQTT broker |
| `MQTT_PORT` | `1883` | Cổng MQTT |
| `DATABASE_URL` | `postgresql://robot:robot123@localhost:5432/robot` | Chuỗi kết nối DB |
| `CONFIDENCE_THRESHOLD` | `0.35` | Ngưỡng confidence YOLO |
| `HEADLESS` | `1` | Chế độ không hiển thị cửa sổ GUI |
| `TELEGRAM_ENABLED` | `0` | Bật/tắt gửi cảnh báo Telegram |

## 8. API và MQTT contract

### API chính

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/` | Web dashboard |
| GET | `/api/status` | Trạng thái robot hiện tại |
| GET | `/api/stats` | Thống kê tổng hợp |
| GET | `/api/events` | Lịch sử phát hiện đối tượng |
| GET | `/api/alerts` | Lịch sử cảnh báo sensor |
| GET | `/api/alerts/latest` | Cảnh báo mới nhất |
| GET | `/api/stream` | MJPEG stream |
| POST | `/api/control?action=...` | Gửi lệnh điều khiển |

### MQTT topics

| Topic | Direction | Payload mẫu |
|-------|-----------|-------------|
| `robot/position` | Server -> ESP32 | `{detected, x, y, pan, tilt}` |
| `robot/command` | Server -> ESP32 | `{action}` |
| `robot/alert` | ESP32 -> Server | `{type, detail, distance_mm, pir}` |

## 9. Build firmware ESP32

```bash
# Station (ESP32-CAM)
cd station
idf.py build flash monitor

# Motor controller (SIN)
cd ../SIN
idf.py build flash monitor
```

## 10. Tài liệu nội bộ

- Kiến trúc và flowchart: `docs/project_flowcharts.html`, `docs/robot_flowchart.drawio`
- Tổng quan quy trình: `docs/TONG_QUAN_QUY_TRINH_HE_THONG.md`
- Thuật toán tránh vật cản: `docs/THUẬT_TOÁN_NÉ_VẬT_CẢN_CHI_TIẾT.md`
- Slide/presentation: `docs/presentations/`
- Notebook thử nghiệm: `notebooks/notebooked4c917f13.ipynb`
- Script trích xuất notebook: `tools/notebook/run_notebook_extract.bat`

## 11. Troubleshooting

### 1) MQTT không kết nối được

Kiểm tra lần lượt:

- Broker host/IP có đúng mạng không.
- Port `1883` đã mở và broker đang chạy.
- User/password MQTT khớp cấu hình.

### 2) Sensor khoảng cách trả sai hoặc timeout (SIN)

- Kiểm tra nguồn cấp và dây tín hiệu.
- Kiểm tra đúng chế độ cảm biến đang dùng (VL53L0X hoặc HC-SR04).
- Xác nhận wiring GPIO đúng với `SIN/main/config.h`.

### 3) Không thấy video stream trên dashboard

- Xác nhận `station/` đang gửi TCP đến đúng IP server.
- Kiểm tra port `8765` không bị chặn firewall.
- Kiểm tra log `server/` xem có nhận frame không.

---

Nếu bạn muốn, có thể tách README này thành 2 bản:

- `README.md` cho onboarding nhanh (ngắn gọn)
- `docs/OPERATIONS.md` cho vận hành chi tiết (production checklist)
