"""
test_database.py — Test database models + operations
======================================================

Module được test: server/database.py
Models:          DetectionEvent, RobotStatus, SensorAlert, Setting

MỤC ĐÍCH:
  Kiểm tra các thao tác CRUD (Create/Read/Update/Delete) trên database.
  Dùng SQLite in-memory để test nhanh mà không cần PostgreSQL.

CÁC TEST CASE:
  1. test_create_detection_event
     → Tạo 1 DetectionEvent → query lại đúng data
  
  2. test_create_sensor_alert
     → Tạo 1 SensorAlert → query lại đúng type, distance, pir
  
  3. test_robot_status
     → Đọc/cập nhật trạng thái robot (mode, mqtt_connected, camera_connected)
  
  4. test_setting_save_load
     → Lưu setting key-value → đọc lại đúng giá trị
  
  5. test_query_detected_events_only
     → Query chỉ lấy events có detected=True (giống API)
  
  6. test_multiple_alerts_order
     → Tạo nhiều alerts → query mới nhất trước (ORDER BY timestamp DESC)

KẾT QUẢ MONG ĐỢI:
  - Tất cả 6 test PASSED
  - CRUD hoạt động đúng trên SQLite (tương thích PostgreSQL)

CHẠY TEST:
  cd D:\\ROBOT\\server
  python -m pytest tests/test_database.py -v
"""

import sys
import os
from datetime import datetime, timezone, timedelta
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestDatabase:
    """
    Test database models và operations.
    
    Sử dụng SQLite in-memory (từ fixture test_db trong conftest.py).
    Mỗi test có database riêng, không ảnh hưởng nhau.
    """

    def test_create_detection_event(self, test_db):
        """
        Test: Tạo DetectionEvent → query lại đúng data
        
        Đầu vào:
          - detected=True, confidence=0.92, x=320, y=240
        
        Kết quả mong đợi:
          - Record được lưu vào DB
          - Query lại → đúng giá trị đã lưu
        
        Giải thích:
          → Mỗi khi YOLO phát hiện người, server lưu 1 DetectionEvent
          → Bao gồm: tọa độ, confidence, góc pan/tilt, đường dẫn ảnh
        """
        from database import DetectionEvent

        # Tạo event mới
        event = DetectionEvent(
            detected=True,
            confidence=0.92,
            x=320,
            y=240,
            pan=5.5,
            tilt=-2.3,
            image_path="/app/images/test.jpg"
        )
        test_db.add(event)
        test_db.commit()

        # Query lại
        saved = test_db.query(DetectionEvent).first()

        assert saved is not None, "Event phải được lưu vào DB"
        assert saved.detected == True, "detected phải = True"
        assert saved.confidence == pytest.approx(0.92), f"confidence phải ≈ 0.92, nhận {saved.confidence}"
        assert saved.x == 320, f"x phải = 320, nhận {saved.x}"
        assert saved.y == 240, f"y phải = 240, nhận {saved.y}"
        assert saved.pan == pytest.approx(5.5), f"pan phải ≈ 5.5"
        assert saved.image_path == "/app/images/test.jpg"
        print("✅ DetectionEvent: tạo + query thành công")

    def test_create_sensor_alert(self, test_db):
        """
        Test: Tạo SensorAlert → query lại đúng data
        
        Đầu vào:
          - alert_type="pir", detail="Motion detected", pir=True
        
        Kết quả mong đợi:
          - Alert được lưu vào DB
          - Query lại → đúng giá trị
        
        Giải thích:
          → ESP32 gửi alert qua MQTT khi PIR phát hiện chuyển động
            hoặc VL53L0X đo khoảng cách gần
          → Server lưu vào DB để hiển thị trên dashboard
        """
        from database import SensorAlert

        alert = SensorAlert(
            alert_type="pir",
            detail="Motion detected in room",
            distance_mm=0,
            pir=True,
            acknowledged=False
        )
        test_db.add(alert)
        test_db.commit()

        saved = test_db.query(SensorAlert).first()

        assert saved is not None, "Alert phải được lưu"
        assert saved.alert_type == "pir", f"Type phải = 'pir', nhận '{saved.alert_type}'"
        assert saved.pir == True, "PIR phải = True"
        assert saved.acknowledged == False, "Mới tạo → chưa acknowledged"
        print("✅ SensorAlert: tạo + query thành công")

    def test_robot_status(self, test_db):
        """
        Test: Đọc/cập nhật RobotStatus
        
        Tình huống:
          - Tạo RobotStatus mặc định (MONITOR, offline)
          - Update sang PATROL, mqtt_connected=True
        
        Kết quả mong đợi:
          - State = "PATROL" sau update
          - mqtt_connected = True
        
        Giải thích:
          → Bảng robot_status chỉ có 1 row (id=1)
          → Được update liên tục bởi server main loop
        """
        from database import RobotStatus

        # Tạo status ban đầu
        status = RobotStatus(
            id=1,
            state="MONITOR",
            mqtt_connected=False,
            camera_connected=False
        )
        test_db.add(status)
        test_db.commit()

        # Update trạng thái
        status.state = "PATROL"
        status.mqtt_connected = True
        test_db.commit()

        # Query lại
        saved = test_db.query(RobotStatus).get(1)

        assert saved.state == "PATROL", f"State phải = 'PATROL', nhận '{saved.state}'"
        assert saved.mqtt_connected == True, "MQTT phải connected"
        print("✅ RobotStatus: update thành công")

    def test_setting_save_load(self, test_db):
        """
        Test: Lưu và đọc Setting (key-value store)
        
        Tình huống:
          - Lưu setting: telegram_token = "abc123"
          - Query lại → đúng giá trị
        
        Kết quả mong đợi:
          - Setting được lưu với key + value đúng
        
        Giải thích:
          → Bảng settings dùng để lưu cấu hình persistent
            (Telegram token, chat ID, cooldown...)
          → Tồn tại giữa các lần restart server
        """
        from database import Setting

        setting = Setting(key="telegram_token", value="abc123xyz")
        test_db.add(setting)
        test_db.commit()

        saved = test_db.query(Setting).filter_by(key="telegram_token").first()

        assert saved is not None, "Setting phải được lưu"
        assert saved.value == "abc123xyz", f"Value phải = 'abc123xyz', nhận '{saved.value}'"
        print("✅ Setting: save + load thành công")

    def test_query_detected_events_only(self, test_db):
        """
        Test: Query chỉ lấy events có detected=True
        
        Tình huống:
          - Tạo 3 events: 2 detected=True, 1 detected=False
          - Query với filter detected=True
        
        Kết quả mong đợi:
          - Trả về 2 events (chỉ những cái detected=True)
        
        Giải thích:
          → API endpoint GET /api/events?detected_only=true
            mặc định chỉ lấy events có phát hiện người
          → Lọc bỏ events rỗng (không phát hiện)
        """
        from database import DetectionEvent

        # Tạo 3 events
        test_db.add(DetectionEvent(detected=True, confidence=0.9))
        test_db.add(DetectionEvent(detected=False, confidence=0.0))
        test_db.add(DetectionEvent(detected=True, confidence=0.8))
        test_db.commit()

        # Query chỉ detected=True
        detected_events = test_db.query(DetectionEvent) \
            .filter(DetectionEvent.detected == True) \
            .all()

        assert len(detected_events) == 2, \
            f"Phải có 2 events detected=True, nhận {len(detected_events)}"
        print("✅ Query detected_only → đúng 2 events")

    def test_multiple_alerts_order(self, test_db):
        """
        Test: Nhiều alerts → query mới nhất trước
        
        Tình huống:
          - Tạo 3 alerts với thời gian khác nhau
          - Query ORDER BY timestamp DESC
        
        Kết quả mong đợi:
          - Alert mới nhất ở đầu list
        
        Giải thích:
          → Dashboard hiển thị alerts mới nhất trước
          → Cần đảm bảo thứ tự đúng
        """
        from database import SensorAlert

        # Tạo alerts với thời gian khác nhau
        now = datetime.now(timezone.utc)
        test_db.add(SensorAlert(
            alert_type="pir", detail="first",
            timestamp=now - timedelta(minutes=10)
        ))
        test_db.add(SensorAlert(
            alert_type="distance", detail="second",
            timestamp=now - timedelta(minutes=5)
        ))
        test_db.add(SensorAlert(
            alert_type="pir", detail="third (newest)",
            timestamp=now
        ))
        test_db.commit()

        # Query mới nhất trước
        alerts = test_db.query(SensorAlert) \
            .order_by(SensorAlert.timestamp.desc()) \
            .all()

        assert len(alerts) == 3, f"Phải có 3 alerts, nhận {len(alerts)}"
        assert alerts[0].detail == "third (newest)", \
            f"Alert đầu tiên phải là mới nhất, nhận '{alerts[0].detail}'"
        print("✅ Query alerts ORDER BY timestamp DESC → đúng thứ tự")
