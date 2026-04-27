import sys
import os
import cv2
import numpy as np

# Add server directory to path
sys.path.insert(0, r"d:\ROBOT\server")

from detector import PersonDetector

def test_detector():
    try:
        print("[TEST] Initializing PersonDetector...")
        detector = PersonDetector(enable_preprocess=False)
        print("[TEST] Initialization OK")
        
        # Create a dummy image (100x100 black image)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        
        print("[TEST] Running detection with empty frame...")
        detections, confirmed = detector.detect_confirmed(frame)
        print(f"[TEST] Result: Detections: {len(detections)}, Confirmed: {confirmed}")
        
        print("[TEST] Detection loop OK. No crash on empty.")
        
    except Exception as e:
        print(f"[TEST] ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_detector()
