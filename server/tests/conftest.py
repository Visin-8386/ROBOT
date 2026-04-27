"""
conftest.py — Fixtures chung cho tất cả test files
=====================================================

File này chứa các pytest fixture dùng chung:
  - test_db: Database SQLite in-memory (không cần PostgreSQL thật)
  - sample_frame: Ảnh giả lập từ ESP32-CAM
  - sample_frame_with_person: Ảnh có hình người (để test YOLO)

Pytest sẽ tự động tìm và load file này trước khi chạy test.
"""

import sys
import os
import pytest
import numpy as np

# ── Thêm thư mục server/ vào path để import được các module ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ================================================================
#  Fixture: Database in-memory (SQLite)
# ================================================================
@pytest.fixture
def test_db():
    """
    Tạo database SQLite in-memory cho test.
    
    Tại sao dùng SQLite thay vì PostgreSQL?
    → Không cần cài/chạy PostgreSQL khi test
    → Mỗi test có DB riêng, không ảnh hưởng nhau
    → Tự động xóa sau khi test xong
    
    Yields:
        session: SQLAlchemy Session object
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import Base

    # Tạo engine SQLite in-memory
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    yield session  # Test sẽ dùng session này

    # Cleanup sau khi test xong
    session.close()
    engine.dispose()


# ================================================================
#  Fixture: Frame ảnh giả lập
# ================================================================
@pytest.fixture
def sample_frame():
    """
    Tạo frame ảnh giả lập 640x480 (giống kích thước ESP32-CAM).
    
    Ảnh chỉ là noise ngẫu nhiên, KHÔNG có người.
    Dùng để test trường hợp "không phát hiện người".
    
    Returns:
        numpy array shape (480, 640, 3) dtype uint8 (BGR)
    """
    # Tạo ảnh ngẫu nhiên 640x480 BGR
    return np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)


@pytest.fixture
def black_frame():
    """
    Frame đen hoàn toàn — test edge case ảnh tối.
    
    Returns:
        numpy array shape (480, 640, 3) toàn số 0
    """
    return np.zeros((480, 640, 3), dtype=np.uint8)
