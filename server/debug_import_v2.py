import sys
import os

print(f"Python executable: {sys.executable}")
print(f"Python path: {sys.path}")

try:
    import ultralytics
    print(f"Ultralytics file: {ultralytics.__file__}")
    print(f"Ultralytics version: {getattr(ultralytics, '__version__', 'unknown')}")
    
    from ultralytics import YOLO
    print("SUCCESS: Imported YOLO from ultralytics")
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
    # Try alternate import
    try:
        from ultralytics.models import YOLO
        print("SUCCESS: Imported YOLO from ultralytics.models")
    except Exception as e2:
        print(f"FAILED alternate: {type(e2).__name__}: {e2}")

    # Inspect the module
    import ultralytics
    print(f"Ultralytics dir: {dir(ultralytics)}")
