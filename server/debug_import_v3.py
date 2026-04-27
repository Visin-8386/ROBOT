import sys
import os

print(f"Python executable: {sys.executable}")
print(f"Python path: {sys.path}")

try:
    import ml_dtypes
    print(f"ml_dtypes version: {getattr(ml_dtypes, '__version__', 'unknown')}")
    print(f"ml_dtypes file: {ml_dtypes.__file__}")
    print(f"ml_dtypes contents: {dir(ml_dtypes)}")
    if hasattr(ml_dtypes, 'float4_e2m1fn'):
        print("ml_dtypes has float4_e2m1fn")
    else:
        print("ml_dtypes MISSING float4_e2m1fn")
except ImportError:
    print("ml_dtypes NOT INSTALLED")

try:
    from ultralytics import YOLO
    print("SUCCESS: Imported YOLO from ultralytics")
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
