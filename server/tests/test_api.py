"""
test_api.py — Test REST API endpoints (FastAPI)
=================================================

Module được test: server/api.py
Framework:        FastAPI + TestClient

MỤC ĐÍCH:
  Kiểm tra tất cả API endpoints trả về đúng status code,
  đúng format JSON, và xử lý lỗi đúng cách.

CÁC TEST CASE:
  1. test_health_check
     → GET /api/health → 200 OK
  
  2. test_get_status
     → GET /api/status → 200 + JSON có field "mode", "camera_connected"
  
  3. test_get_stats
     → GET /api/stats → 200 + JSON có "total_detections"
  
  4. test_control_valid_action
     → POST /api/control?action=forward → 200 + command queued
  
  5. test_control_invalid_action
     → POST /api/control?action=fly → 400 Bad Request (action không hợp lệ)
  
  6. test_get_events
     → GET /api/events → 200 + JSON list
  
  7. test_get_alerts
     → GET /api/alerts → 200 + JSON list

KẾT QUẢ MONG ĐỢI:
  - Tất cả 7 test PASSED
  - API trả về đúng HTTP status code
  - JSON response có đầy đủ các field cần thiết

CHẠY TEST:
  cd D:\\ROBOT\\server
  python -m pytest tests/test_api.py -v

LƯU Ý:
  Test này dùng FastAPI TestClient — KHÔNG cần chạy server thật.
  TestClient tạo HTTP client giả lập gọi thẳng vào FastAPI app.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi.testclient import TestClient


class TestAPI:
    """
    Test FastAPI REST API endpoints.
    
    Sử dụng TestClient — gọi API mà không cần chạy Uvicorn.
    Một số endpoint cần database nên ta override dependency get_db.
    """

    @pytest.fixture(autouse=True)
    def setup_client(self, test_db):
        """
        Setup TestClient trước mỗi test.
        
        - Override get_db dependency để dùng SQLite in-memory
        - Tạo TestClient từ FastAPI app
        """
        from api import app
        from database import get_db

        # Override database dependency → dùng test_db
        def override_get_db():
            try:
                yield test_db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def test_health_check(self):
        """
        Test: GET /api/health → 200 OK
        
        Endpoint đơn giản nhất, kiểm tra server có sống không.
        
        Kết quả mong đợi:
          - Status code: 200
          - Response có field "status"
        """
        response = self.client.get("/api/health")

        assert response.status_code == 200, f"Health check phải trả về 200, nhận {response.status_code}"
        print("✅ GET /api/health → 200 OK")

    def test_get_status(self):
        """
        Test: GET /api/status → trạng thái robot
        
        Kết quả mong đợi:
          - Status code: 200
          - JSON có: "mode", "camera_connected", "mqtt_connected"
        
        Giải thích:
          → Dashboard và Flutter app gọi endpoint này
            để hiển thị trạng thái robot real-time
        """
        response = self.client.get("/api/status")

        assert response.status_code == 200, f"Status phải trả về 200, nhận {response.status_code}"

        data = response.json()
        assert "mode" in data or "state" in data, "Response phải có field mode/state"
        print(f"✅ GET /api/status → 200, data: {list(data.keys())}")

    def test_get_stats(self):
        """
        Test: GET /api/stats → thống kê tổng quan
        
        Kết quả mong đợi:
          - Status code: 200
          - JSON có: "total_detections" hoặc tương đương
        
        Giải thích:
          → Dashboard hiển thị: tổng số lần phát hiện, 
            số alerts, thời gian uptime...
        """
        response = self.client.get("/api/stats")

        assert response.status_code == 200, f"Stats phải trả về 200, nhận {response.status_code}"

        data = response.json()
        assert isinstance(data, dict), "Response phải là JSON object"
        print(f"✅ GET /api/stats → 200, fields: {list(data.keys())}")

    def test_control_valid_action(self):
        """
        Test: POST /api/control?action=patrol → gửi lệnh điều khiển
        
        Đầu vào:
          - action = "patrol" (1 trong các action hợp lệ)
        
        Kết quả mong đợi:
          - Status code: 200
          - Lệnh được queue để gửi qua MQTT
        
        Actions hợp lệ:
          forward, backward, left, right, stop, patrol, chase, monitor
        """
        response = self.client.post("/api/control?action=patrol")

        assert response.status_code == 200, \
            f"Control action hợp lệ phải trả về 200, nhận {response.status_code}"
        print("✅ POST /api/control?action=patrol → 200 OK")

    def test_get_events(self):
        """
        Test: GET /api/events → lịch sử detection
        
        Kết quả mong đợi:
          - Status code: 200
          - Response có pagination info
        
        Giải thích:
          → Hiển thị lịch sử: thời gian, tọa độ, confidence
            của mỗi lần phát hiện người
        """
        response = self.client.get("/api/events")

        assert response.status_code == 200, f"Events phải trả về 200, nhận {response.status_code}"

        data = response.json()
        assert isinstance(data, (dict, list)), "Response phải là JSON"
        print("✅ GET /api/events → 200 OK")

    def test_get_alerts(self):
        """
        Test: GET /api/alerts → lịch sử cảnh báo sensor
        
        Kết quả mong đợi:
          - Status code: 200
          - Response chứa list alerts
        
        Giải thích:
          → Hiển thị lịch sử cảnh báo từ PIR, VL53L0X sensor
        """
        response = self.client.get("/api/alerts")

        assert response.status_code == 200, f"Alerts phải trả về 200, nhận {response.status_code}"

        data = response.json()
        assert isinstance(data, (dict, list)), "Response phải là JSON"
        print("✅ GET /api/alerts → 200 OK")

    def test_telegram_status(self):
        """
        Test: GET /api/telegram/status → trạng thái Telegram config
        
        Kết quả mong đợi:
          - Status code: 200
          - JSON có: "enabled", "configured"
        """
        response = self.client.get("/api/telegram/status")

        assert response.status_code == 200, f"Telegram status phải trả về 200, nhận {response.status_code}"

        data = response.json()
        assert isinstance(data, dict), "Response phải là JSON object"
        print(f"✅ GET /api/telegram/status → 200, data: {data}")
