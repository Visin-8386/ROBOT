"""
Database — SQLAlchemy models + session management
"""

import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, Float, String, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
import config

Base = declarative_base()


class DetectionEvent(Base):
    """Lịch sử phát hiện người."""
    __tablename__ = "detection_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    detected = Column(Boolean, default=False)
    confidence = Column(Float, nullable=True)
    track_id = Column(Integer, nullable=True)
    x = Column(Integer, default=0)
    y = Column(Integer, default=0)
    pan = Column(Float, default=0.0)
    tilt = Column(Float, default=0.0)
    image_path = Column(String(255), nullable=True)


class RobotStatus(Base):
    """Trạng thái robot (cập nhật liên tục)."""
    __tablename__ = "robot_status"

    id = Column(Integer, primary_key=True, default=1)
    state = Column(String(20), default="MONITOR")  # MONITOR / PATROL / CHASE / MANUAL / OFFLINE
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    mqtt_connected = Column(Boolean, default=False)
    camera_connected = Column(Boolean, default=False)


class SensorAlert(Base):
    """Cảnh báo từ sensor (PIR, ToF, Camera AI)."""
    __tablename__ = "sensor_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    alert_type = Column(String(20), nullable=False)  # pir, distance, camera, status
    detail = Column(Text, default="")
    distance_mm = Column(Integer, default=0)
    pir = Column(Boolean, default=False)
    acknowledged = Column(Boolean, default=False)


class Setting(Base):
    """Cài đặt key-value."""
    __tablename__ = "settings"

    key = Column(String(50), primary_key=True)
    value = Column(Text, default="")

# ========================== Engine + Session ==========================

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, pool_size=5)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    """Create tables if not exist."""
    Base.metadata.create_all(engine)
    print("[DB] Tables created/verified")

    # Ensure robot_status row exists
    with SessionLocal() as session:
        status = session.get(RobotStatus, 1)
        if not status:
            session.add(RobotStatus(id=1))
            session.commit()

    # Auto-cleanup: xóa records cũ hơn 7 ngày
    try:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        with SessionLocal() as session:
            del_events = session.query(DetectionEvent).filter(
                DetectionEvent.timestamp < cutoff
            ).delete()
            del_alerts = session.query(SensorAlert).filter(
                SensorAlert.timestamp < cutoff
            ).delete()
            session.commit()
            if del_events or del_alerts:
                print(f"[DB] Cleanup: removed {del_events} events + {del_alerts} alerts older than 7 days")
    except Exception as e:
        print(f"[DB] Cleanup error: {e}")

    print(f"[DB] Connected to {config.DATABASE_URL.split('@')[-1]}")


def get_db():
    """Dependency for FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
