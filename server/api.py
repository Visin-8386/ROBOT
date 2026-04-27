"""
FastAPI — REST API for Robot Dashboard
Runs alongside the TCP detection server.
"""

import os
import json
import time
import re
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, Depends, Query, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel

import config
from database import DetectionEvent, RobotStatus, SensorAlert, Setting, SessionLocal, get_db
from build_face_embeddings import build_embeddings

app = FastAPI(title="Robot Security API", version="1.0")

# Static files
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# CORS — cho phép web dashboard gọi API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========================== Pydantic Models ==========================

class ServoCommand(BaseModel):
    action: str  # servo_left, servo_right, servo_center


def get_mqtt():
    """Dùng chung mqtt_client từ server.py (tránh tạo client riêng)."""
    import server as srv
    if srv.mqtt_client and srv.mqtt_client.is_connected():
        return srv.mqtt_client
    return None


# ========================== Events API ==========================

@app.get("/api/events")
def get_events(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    detected_only: bool = Query(True),
    db: Session = Depends(get_db)
):
    """Lịch sử detection events (pagination)."""
    query = db.query(DetectionEvent)
    if detected_only:
        query = query.filter(DetectionEvent.detected == True)

    total = query.count()
    events = (query
              .order_by(desc(DetectionEvent.timestamp))
              .offset((page - 1) * limit)
              .limit(limit)
              .all())

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "events": [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "detected": e.detected,
                "confidence": e.confidence,
                "track_id": getattr(e, "track_id", None),
                "x": e.x,
                "y": e.y,
                "pan": e.pan,
                "tilt": e.tilt,
                "has_image": e.image_path is not None,
            }
            for e in events
        ]
    }


@app.get("/api/events/{event_id}/image")
def get_event_image(event_id: int, db: Session = Depends(get_db)):
    """Xem ảnh detection."""
    event = db.get(DetectionEvent, event_id)
    if not event or not event.image_path:
        raise HTTPException(404, "Image not found")

    path = os.path.join(config.IMAGE_STORAGE_PATH, event.image_path)
    if not os.path.exists(path):
        raise HTTPException(404, "Image file missing")

    return FileResponse(path, media_type="image/jpeg")


# ========================== Status API ==========================

@app.get("/api/status")
def get_status(db: Session = Depends(get_db)):
    """Trạng thái robot real-time."""
    status = db.get(RobotStatus, 1)
    if not status:
        return {"state": "UNKNOWN"}

    import server as srv
    return {
        "state": status.state,
        "last_seen": status.last_seen.isoformat() if status.last_seen else None,
        "mqtt_connected": status.mqtt_connected,
        "camera_connected": status.camera_connected,
        "target_type": srv.target_type if hasattr(srv, "target_type") else "person",
    }


# ========================== Control API ==========================

@app.post("/api/control")
def control_robot(action: str = Query(..., description="forward|backward|left|right|stop|patrol|chase|monitor")):
    """
    Gửi lệnh điều khiển robot qua MQTT.
    Actions: forward, backward, left, right, stop, patrol, chase, monitor
    """
    valid_actions = ["forward", "backward", "left", "right", "stop", "patrol", "chase", "monitor"]
    if action not in valid_actions:
        raise HTTPException(400, f"Invalid action. Use: {valid_actions}")

    # Push to command_queue — main loop will publish via MQTT
    import server as srv
    payload = json.dumps({
        "action": action,
        "ts": int(time.time() * 1000)
    })
    try:
        srv.command_queue.put(payload, timeout=2)
        print(f"[API] Command '{action}' → queued")
    except Exception as e:
        print(f"[API] Command '{action}' → queue FULL: {e}")
        raise HTTPException(503, "Command queue full")

    # Update DB state for mode-change commands
    if action in ["monitor", "patrol", "chase", "stop"]:
        try:
            with SessionLocal() as db:
                status = db.get(RobotStatus, 1)
                if status:
                    if action == "stop":
                        status.state = "MANUAL"
                    else:
                        status.state = action.upper()
                    db.commit()
        except Exception:
            pass

    return {"status": "ok", "action": action}


@app.post("/api/target")
def set_target(type: str = Query(..., description="person|pet")):
    """Thay đổi mục tiêu nhận diện."""
    if type not in ["person", "pet"]:
        raise HTTPException(400, "Invalid target type. Use: person, pet")

    import server as srv
    srv.target_type = type
    print(f"[API] Switched target to: {type}")
    return {"status": "ok", "target_type": type}


# ========================== Servo Control API ==========================

@app.post("/api/servo")
def servo_control(cmd: ServoCommand):
    """
    Gửi lệnh điều khiển servo qua MQTT.
    Actions: servo_left, servo_right, servo_center
    """
    valid_actions = ["servo_left", "servo_right", "servo_center"]
    if cmd.action not in valid_actions:
        raise HTTPException(400, f"Invalid action. Use: {valid_actions}")

    # Push to command_queue — main loop will publish via MQTT
    import server as srv
    payload = json.dumps({
        "action": cmd.action,
        "ts": int(time.time() * 1000)
    })
    try:
        srv.command_queue.put(payload, timeout=2)
        print(f"[API] Servo command '{cmd.action}' → queued")
    except Exception as e:
        print(f"[API] Servo command '{cmd.action}' → queue FULL: {e}")
        raise HTTPException(503, "Command queue full")

    return {"status": "ok", "action": cmd.action}


# ========================== Stats API ==========================

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    """Thống kê tổng quan."""
    from sqlalchemy import func

    total_events = db.query(func.count(DetectionEvent.id)).scalar()
    total_detected = db.query(func.count(DetectionEvent.id)).filter(
        DetectionEvent.detected == True
    ).scalar()

    # Events trong 24h qua
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = db.query(func.count(DetectionEvent.id)).filter(
        DetectionEvent.timestamp >= since,
        DetectionEvent.detected == True
    ).scalar()

    return {
        "total_events": total_events,
        "total_detections": total_detected,
        "detections_24h": recent,
    }


# ========================== Alerts API ==========================

@app.get("/api/alerts")
def get_alerts(
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    alert_type: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Lịch sử cảnh báo sensor (PIR, ToF, Camera)."""
    query = db.query(SensorAlert)
    if alert_type:
        query = query.filter(SensorAlert.alert_type == alert_type)

    total = query.count()
    alerts = (
        query.order_by(desc(SensorAlert.timestamp))
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "alerts": [
            {
                "id": a.id,
                "timestamp": a.timestamp.isoformat() if a.timestamp else None,
                "type": a.alert_type,
                "detail": a.detail,
                "distance_mm": a.distance_mm,
                "pir": a.pir,
                "acknowledged": a.acknowledged,
            }
            for a in alerts
        ]
    }


@app.get("/api/alerts/latest")
def get_latest_alert():
    """Latest real-time sensor alert (from memory, no DB query)."""
    import server as srv
    if srv.latest_alert:
        return srv.latest_alert
    return {"type": "none", "detail": "Ch\u01b0a c\u00f3 c\u1ea3nh b\u00e1o"}


@app.post("/api/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, db: Session = Depends(get_db)):
    """\u0110\u00e1nh d\u1ea5u \u0111\u00e3 x\u00e1c nh\u1eadn c\u1ea3nh b\u00e1o."""
    alert = db.get(SensorAlert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.acknowledged = True
    db.commit()
    return {"status": "ok"}


# ========================== Camera Stream ==========================

@app.get("/api/stream")
async def video_stream():
    """MJPEG stream from latest drawn camera frame (async so it doesn't block workers)."""
    import asyncio
    import server as srv

    async def generate():
        last_jpeg = None
        while True:
            with srv.jpeg_lock:
                jpeg = srv.drawn_jpeg  # Lấy ảnh ĐÃ VẼ AI (thay vì ảnh thô như cũ)
            if jpeg and jpeg is not last_jpeg:
                last_jpeg = jpeg
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n"
                       b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
                       b"\r\n" + jpeg + b"\r\n")
            await asyncio.sleep(0.02)  # Poll every 20ms for smoother streaming

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ========================== Health ==========================

@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


# ========================== Dashboard ==========================

@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve web dashboard."""
    html_path = Path(__file__).parent / "static" / "index.html"
    if not html_path.exists():
        raise HTTPException(404, "Dashboard not found")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/servo.html", response_class=HTMLResponse)
def servo_page():
    """Serve servo control page."""
    html_path = Path(__file__).parent / "static" / "servo.html"
    if not html_path.exists():
        raise HTTPException(404, "Servo page not found")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ========================== Telegram Notification API ==========================

@app.get("/api/telegram/status")
def telegram_status():
    """Lấy trạng thái cấu hình Telegram."""
    import server as srv
    tg = srv.telegram
    if not tg:
        return {"enabled": False, "configured": False}
    return {
        "enabled": tg.enabled,
        "configured": tg.is_configured,
        "has_token": bool(tg.bot_token),
        "has_chat_id": bool(tg.chat_id),
        "cooldown": tg.cooldown,
    }


@app.post("/api/telegram/config")
def telegram_config(
    bot_token: str = Query(None, description="Telegram Bot Token"),
    chat_id: str = Query(None, description="Telegram Chat ID"),
    enabled: Optional[bool] = Query(None),
    cooldown: Optional[int] = Query(None, ge=5, le=3600),
    db: Session = Depends(get_db),
):
    """Cập nhật cấu hình Telegram và lưu vào DB."""
    import server as srv
    tg = srv.telegram
    if not tg:
        raise HTTPException(503, "Telegram notifier not initialized")

    # Update runtime config
    tg.update_config(
        bot_token=bot_token,
        chat_id=chat_id,
        enabled=enabled,
        cooldown=cooldown,
    )

    # Persist to DB settings table
    settings = {}
    if bot_token is not None:
        settings["telegram_bot_token"] = bot_token
    if chat_id is not None:
        settings["telegram_chat_id"] = chat_id
    if enabled is not None:
        settings["telegram_enabled"] = "1" if enabled else "0"
    if cooldown is not None:
        settings["telegram_cooldown"] = str(cooldown)

    for key, value in settings.items():
        existing = db.query(Setting).filter(Setting.key == key).first()
        if existing:
            existing.value = value
        else:
            db.add(Setting(key=key, value=value))
    db.commit()

    return {
        "status": "ok",
        "enabled": tg.enabled,
        "configured": tg.is_configured,
        "cooldown": tg.cooldown,
    }


@app.post("/api/telegram/test")
def telegram_test():
    """Gửi tin nhắn test để kiểm tra kết nối."""
    import server as srv
    tg = srv.telegram
    if not tg:
        raise HTTPException(503, "Telegram notifier not initialized")
    if not tg.is_configured:
        raise HTTPException(400, "Chưa cấu hình Token hoặc Chat ID")

    result = tg.test_connection()
    if result["ok"]:
        return {"status": "ok", "bot_name": result.get("bot_name"),
                "bot_username": result.get("bot_username")}
    else:
        raise HTTPException(400, result.get("error", "Unknown error"))


# ========================== Family Face Data API ==========================

FACES_DIR = Path(__file__).resolve().parent / "known_faces"
EMBEDDINGS_PATH = FACES_DIR / "embeddings.npz"
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _safe_person_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9 _-]+", "", name).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    if not cleaned:
        raise HTTPException(400, "Tên người không hợp lệ")
    return cleaned[:64]


def _count_images(person_dir: Path) -> int:
    return len([
        p for p in person_dir.glob("**/*")
        if p.is_file() and p.suffix.lower() in ALLOWED_IMAGE_EXT
    ])


def _reload_face_engine_embeddings() -> None:
    try:
        import server as srv
        if getattr(srv, "face_engine", None) is not None:
            srv.face_engine.load_embeddings()
    except Exception as e:
        print(f"[FaceDB] Runtime reload warning: {e}")


@app.get("/api/faces")
def list_face_members():
    """Liệt kê người nhà đã thêm và số ảnh mỗi người."""
    FACES_DIR.mkdir(parents=True, exist_ok=True)
    members = []
    for person_dir in sorted([d for d in FACES_DIR.iterdir() if d.is_dir()], key=lambda p: p.name.lower()):
        image_count = _count_images(person_dir)
        if image_count == 0:
            continue
        members.append({
            "name": person_dir.name,
            "image_count": image_count,
        })

    return {
        "total": len(members),
        "members": members,
        "embeddings_exists": EMBEDDINGS_PATH.exists(),
    }


@app.post("/api/faces/upload")
async def upload_face_image(
    person_name: str = Form(..., description="Tên người nhà"),
    image: UploadFile = File(..., description="Ảnh khuôn mặt"),
):
    """Thêm ảnh mới cho người nhà và rebuild embeddings."""
    safe_name = _safe_person_name(person_name)
    ext = Path(image.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(400, f"Định dạng ảnh không hỗ trợ: {ext or 'unknown'}")

    person_dir = FACES_DIR / safe_name
    person_dir.mkdir(parents=True, exist_ok=True)

    ts = int(time.time() * 1000)
    dst = person_dir / f"{safe_name}_{ts}{ext}"
    data = await image.read()
    if not data:
        raise HTTPException(400, "File ảnh rỗng")

    with open(dst, "wb") as f:
        f.write(data)

    try:
        total_identities = build_embeddings(str(FACES_DIR), str(EMBEDDINGS_PATH))
        _reload_face_engine_embeddings()
    except Exception as e:
        # Keep uploaded image; user can upload more valid photos later.
        raise HTTPException(500, f"Đã lưu ảnh nhưng rebuild embeddings thất bại: {e}")

    return {
        "status": "ok",
        "person": safe_name,
        "saved_file": dst.name,
        "person_image_count": _count_images(person_dir),
        "total_identities": total_identities,
    }
