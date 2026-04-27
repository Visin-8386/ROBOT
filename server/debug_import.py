import ultralytics
import os
print(f"Location: {ultralytics.__file__}")
try:
    from ultralytics import YOLO
    print("Successfully imported YOLO")
except ImportError as e:
    print(f"ImportError: {e}")
    print(f"Contents of ultralytics: {dir(ultralytics)}")
