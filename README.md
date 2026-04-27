# Robot Security System

A real-time AI security robotics platform that combines ESP32 edge devices, computer vision, MQTT control, a web dashboard, and PostgreSQL event persistence.

## Table of Contents

- [1. Overview](#1-overview)
- [2. System Architecture](#2-system-architecture)
- [3. Core Features](#3-core-features)
- [4. Technical Stack Deep Dive](#4-technical-stack-deep-dive)
- [4.1 Algorithms Used](#41-algorithms-used)
- [5. Key Differentiators](#5-key-differentiators)
- [6. English Project Description](#6-english-project-description)
- [7. Project Structure](#7-project-structure)
- [8. System Requirements](#8-system-requirements)
- [9. Quick Start](#9-quick-start)
- [10. Configuration Guide](#10-configuration-guide)
- [11. API and MQTT Contracts](#11-api-and-mqtt-contracts)
- [12. ESP32 Firmware Build](#12-esp32-firmware-build)
- [13. Internal Documentation](#13-internal-documentation)
- [14. Troubleshooting](#14-troubleshooting)

## 1. Overview

Robot Security System has three primary subsystems:

- **Station (ESP32-CAM)**: captures and streams JPEG frames to the server over TCP.
- **SIN (ESP32 motion controller)**: receives MQTT commands, reads sensors, and publishes alerts.
- **Server (FastAPI + AI + DB)**: performs detection, orchestrates control flow, serves the dashboard, and stores events.

The platform is designed for autonomous monitoring, event-driven response, and manual override through a browser-based control panel.

## 2. System Architecture

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

### Main Data Flow

1. `station/` streams JPEG frames to the TCP server.
2. `server/` runs person detection and publishes control-related data to MQTT.
3. `SIN/` consumes commands and publishes sensor/alert telemetry.
4. The dashboard visualizes live stream, status, and historical events.

## 3. Core Features

- Real-time person detection with YOLOv8.
- Multi-mode control model (Monitor, Patrol, Chase, Manual).
- Interactive web dashboard with button and keyboard control.
- PostgreSQL persistence for detections, alerts, and operational history.
- Optional face recognition pipeline (InsightFace).
- Optional Telegram notifications via environment configuration.

## 4. Technical Stack Deep Dive

### Backend and Real-Time Communication

- **FastAPI + Uvicorn** for high-performance APIs and dashboard serving.
- **TCP streaming (port 8765)** for JPEG frame ingestion using `[4-byte length][payload]` framing.
- **MQTT (Eclipse Mosquitto)** for decoupled command-and-telemetry messaging.

### AI/Computer Vision

- **YOLOv8 (Ultralytics)** for real-time person detection.
- **OpenCV + NumPy** for image transforms and geometric post-processing.
- **InsightFace + ONNXRuntime GPU** for face recognition and accelerated inference when CUDA is available.

### Data Layer and Telemetry

- **PostgreSQL + SQLAlchemy** for event persistence and queryable operational history.
- Centralized config via `server/config.py` and environment variables for Local/Docker parity.

### Embedded/Firmware

- **ESP-IDF** is used for both `station/` and `SIN/` firmware.
- `station/`: camera capture and TCP frame transport.
- `SIN/`: TB6612 motor control, MQTT command handling, PIR/distance sensor telemetry.

### Deployment and Operations

- **Docker Compose** provisions core services: `server`, `mosquitto`, `postgres`.
- Health checks reduce startup race conditions and improve service readiness.

### 4.1 Algorithms Used

This project uses multiple algorithms across perception, tracking, control, and obstacle handling.

| Algorithm | Purpose | Implementation |
|------|------|------|
| YOLOv8 object detection | Real-time person/pet detection from camera frames | `server/detector.py` |
| Image preprocessing pipeline (Gaussian blur + CLAHE + unsharp mask) | Improve low-light/noisy frame quality before inference | `server/detector.py` |
| SORT multi-object tracking | Keep stable target IDs across frames and reduce detection jitter | `server/tracker.py` |
| Kalman filter (state prediction/update) | Predict object motion (`cx, cy, w, h`) and smooth tracking | `server/tracker.py` |
| Hungarian assignment + IoU matching | Associate current detections to existing tracks | `server/tracker.py` |
| Largest-target / lock-on selection | Prioritize nearest or persisted target for robot reaction | `server/detector.py` |
| Closed-loop visual servoing (proportional control + dead zone) | Convert target offset to pan/tilt actions | `server/config.py`, `server/server.py` |
| FSM-based robot modes (Monitor/Patrol/Chase/Manual) | Switch behavior according to context and user control | `server/server.py`, `SIN/main/main.c` |
| Obstacle-avoidance thresholds + scan strategy | Soft avoid, hard stop, and directional bypass logic | `SIN/main/sensor.c`, `SIN/main/main.c` |
| Ultrasonic distance conversion | Convert echo pulse time to distance measurement | `SIN/main/distance_sensor_hcsr04.c` |

Related algorithm documentation and diagrams:

- Obstacle-avoidance deep dive: [docs/THUẬT_TOÁN_NÉ_VẬT_CẢN_CHI_TIẾT.md](docs/THUẬT_TOÁN_NÉ_VẬT_CẢN_CHI_TIẾT.md)
- System flowcharts: [docs/project_flowcharts.html](docs/project_flowcharts.html)
- Draw.io source: [docs/robot_flowchart.drawio](docs/robot_flowchart.drawio)

## 5. Key Differentiators

- **Hybrid edge-server architecture**: low-cost edge control with scalable server-side AI.
- **Closed-loop CV-driven control**: perception -> command generation -> sensor feedback.
- **Channel specialization**:
  - TCP for image transport.
  - MQTT for event-driven command and telemetry.
- **Operations-ready foundation**: dashboard, persistence, notifications, and supporting technical docs.
- **Modular extensibility**:
  - Swap AI model variants without redesigning the pipeline.
  - Add sensors/topics with minimal cross-module impact.

## 6. English Project Description

Robot Security System is a real-time AI-powered security robotics platform that combines ESP32 edge devices with a Python server stack.

The system ingests camera frames from an ESP32-CAM over TCP, performs person detection (YOLOv8) and optional face recognition (InsightFace), then publishes control commands to a motor controller board via MQTT. In parallel, sensor alerts and operational events are persisted to PostgreSQL and visualized through a FastAPI-based web dashboard.

### Key technical strengths

- Hybrid edge-server architecture for cost-efficient real-time intelligence.
- Decoupled communication channels: TCP for video transport, MQTT for control and telemetry.
- Production-friendly deployment using Docker Compose (API + broker + database).
- Extensible design for additional sensors, control modes, and AI models.

## 7. Project Structure

```text
ROBOT/
├─ server/                 # Backend FastAPI, AI detection, DB, MQTT
├─ station/                # ESP32-CAM firmware
├─ SIN/                    # ESP32 motor/sensor firmware
├─ flutter_application/    # Flutter app (optional)
├─ docs/                   # Project documents, flowcharts, slides
├─ notebooks/              # Research/experiment notebooks
├─ tools/notebook/         # Notebook utility scripts
├─ docker-compose.yml      # Root-level infrastructure compose
└─ README.md
```

## 8. System Requirements

### Server

- Docker + Docker Compose (recommended)
- Or Python 3.10+ for local runtime

### Firmware

- ESP-IDF compatible with both `station/` and `SIN/`
- ESP32/ESP32-CAM build toolchain

## 9. Quick Start

### Option 1: Full stack via Docker (recommended)

```bash
cd server
docker-compose up --build
```

After startup:

- Dashboard: `http://localhost:8000`
- TCP receiver: `localhost:8765`
- MQTT broker: `localhost:1883`
- PostgreSQL: `localhost:5432`

### Option 2: Local server with Dockerized services

```bash
cd server

# 1) Start DB + MQTT
docker-compose up postgres mosquitto -d

# 2) Install dependencies
pip install -r requirements.txt

# 3) Run backend
python server.py
```

## 10. Configuration Guide

### Primary Configuration Files

- `server/config.py`: server ports, MQTT, DB URL, YOLO threshold, face recognition, Telegram settings.
- `SIN/main/config.h`: Wi-Fi, MQTT broker, motor/sensor GPIO mapping, sensor thresholds.
- `station/main/config.h`: Wi-Fi, TCP server target, camera parameters.

### Important Environment Variables (server)

| Variable | Default | Description |
|------|----------|-------|
| `MQTT_BROKER` | `localhost` | MQTT broker host |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `DATABASE_URL` | `postgresql://robot:robot123@localhost:5432/robot` | Database connection string |
| `CONFIDENCE_THRESHOLD` | `0.35` | YOLO confidence threshold |
| `HEADLESS` | `1` | Run without GUI windows |
| `TELEGRAM_ENABLED` | `0` | Enable/disable Telegram alerts |

## 11. API and MQTT Contracts

### Main API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------|
| GET | `/` | Web dashboard |
| GET | `/api/status` | Current robot status |
| GET | `/api/stats` | Aggregated metrics |
| GET | `/api/events` | Detection history |
| GET | `/api/alerts` | Sensor alert history |
| GET | `/api/alerts/latest` | Latest alert |
| GET | `/api/stream` | MJPEG stream |
| POST | `/api/control?action=...` | Send control action |

### MQTT topics

| Topic | Direction | Sample Payload |
|-------|-----------|-------------|
| `robot/position` | Server -> ESP32 | `{detected, x, y, pan, tilt}` |
| `robot/command` | Server -> ESP32 | `{action}` |
| `robot/alert` | ESP32 -> Server | `{type, detail, distance_mm, pir}` |

## 12. ESP32 Firmware Build

```bash
# Station (ESP32-CAM)
cd station
idf.py build flash monitor

# Motor controller (SIN)
cd ../SIN
idf.py build flash monitor
```

## 13. Internal Documentation

- Architecture and flowcharts: `docs/project_flowcharts.html`, `docs/robot_flowchart.drawio`
- Process overview: `docs/TONG_QUAN_QUY_TRINH_HE_THONG.md`
- Obstacle-avoidance algorithm notes: `docs/THUẬT_TOÁN_NÉ_VẬT_CẢN_CHI_TIẾT.md`
- Slides and presentations: `docs/presentations/`
- Experiment notebook: `notebooks/notebooked4c917f13.ipynb`
- Notebook extraction helper: `tools/notebook/run_notebook_extract.bat`

## 14. Troubleshooting

### 1) MQTT connection failures

Check the following in order:

- Broker host/IP is reachable from each node.
- Port `1883` is open and broker is running.
- MQTT credentials match configured values.

### 2) Distance sensor incorrect values or timeout (SIN)

- Verify power delivery and signal wiring.
- Confirm the active sensor mode (VL53L0X or HC-SR04).
- Validate GPIO mapping in `SIN/main/config.h`.

### 3) No video stream on dashboard

- Confirm `station/` is sending TCP frames to the correct server IP.
- Ensure port `8765` is not blocked by firewall.
- Inspect `server/` logs for frame ingestion activity.

---

Suggested next documentation split:

- `README.md` for concise onboarding.
- `docs/OPERATIONS.md` for production-grade runbooks and checklists.
