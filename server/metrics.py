"""
Metrics Tracker — Display comprehensive diagnostics for server & station
Shows FPS, timing, queue status, memory, and error counts
"""

import time
import psutil
import os
from collections import deque
from datetime import datetime

class MetricsTracker:
    """Track and display real-time metrics for all pipeline stages."""
    
    def __init__(self, window_size=30):  # 30-second rolling window
        self.window_size = window_size
        self.start_time = time.time()
        
        # RX (TCP receive)
        self.rx_frames = deque(maxlen=window_size)
        self.rx_events = deque(maxlen=window_size)  # (timestamp, frame_size)
        
        # YOLO detection
        self.yolo_frames = deque(maxlen=window_size)
        self.yolo_times = deque(maxlen=window_size)  # ms per frame
        
        # Face recognition
        self.face_frames = deque(maxlen=window_size)
        self.face_times = deque(maxlen=window_size)  # ms per frame
        
        # Processing (drawing, servo, etc)
        self.proc_frames = deque(maxlen=window_size)
        self.proc_times = deque(maxlen=window_size)  # ms per frame
        
        # Queue status
        self.queue_stats = {}
        
        # Error counts
        self.errors = {
            'tcp_timeout': 0,
            'frame_drop': 0,
            'yolo_error': 0,
            'face_error': 0,
            'proc_error': 0,
            'mqtt_error': 0,
        }
        
        # Memory tracking
        self.process = psutil.Process(os.getpid())
        
        # Last display time
        self.last_display = time.time()
        self.display_interval = 10  # Every 10 seconds

    def record_rx_frame(self, frame_size):
        """Record received frame."""
        now = time.time()
        self.rx_frames.append(now)
        self.rx_events.append((now, frame_size))

    def record_yolo(self, elapsed_ms):
        """Record YOLO inference timing."""
        self.yolo_frames.append(time.time())
        self.yolo_times.append(elapsed_ms)

    def record_face(self, elapsed_ms):
        """Record Face recognition timing."""
        self.face_frames.append(time.time())
        self.face_times.append(elapsed_ms)

    def record_processing(self, elapsed_ms):
        """Record Processing (draw/servo) timing."""
        self.proc_frames.append(time.time())
        self.proc_times.append(elapsed_ms)

    def update_queues(self, frame_q, processing_q, face_q):
        """Update queue statistics."""
        self.queue_stats = {
            'frame': (frame_q.qsize(), frame_q.maxsize),
            'processing': (processing_q.qsize(), processing_q.maxsize),
            'face': (face_q.qsize(), face_q.maxsize),
        }

    def record_error(self, error_type):
        """Record an error occurrence."""
        if error_type in self.errors:
            self.errors[error_type] += 1

    def get_fps(self, timestamps):
        """Calculate FPS from timestamp deque."""
        if len(timestamps) < 2:
            return 0.0
        elapsed = timestamps[-1] - timestamps[0]
        if elapsed <= 0:
            return 0.0
        return len(timestamps) / elapsed

    def get_avg_time(self, times):
        """Get average time from deque (in ms)."""
        if len(times) == 0:
            return 0.0
        return sum(times) / len(times)

    def get_memory_info(self):
        """Get memory usage."""
        info = self.process.memory_info()
        return {
            'rss_mb': info.rss / 1024 / 1024,  # Resident set size
            'percent': self.process.memory_percent(),
        }

    def should_display(self):
        """Check if it's time to display metrics."""
        now = time.time()
        if now - self.last_display >= self.display_interval:
            self.last_display = now
            return True
        return False

    def display(self):
        """Print comprehensive metrics dashboard."""
        if not self.should_display():
            return
        
        print("\n" + "="*90)
        print(f"[METRICS] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*90)
        
        # FPS Metrics
        rx_fps = self.get_fps(self.rx_frames)
        yolo_fps = self.get_fps(self.yolo_frames)
        face_fps = self.get_fps(self.face_frames)
        proc_fps = self.get_fps(self.proc_frames)
        
        print(f"\n📊 PIPELINE FPS:")
        print(f"  RX (TCP):        {rx_fps:6.2f} fps ", end="")
        if len(self.rx_events) > 1:
            elapsed = self.rx_events[-1][0] - self.rx_events[0][0]
            bytes_in_window = sum(size for _, size in self.rx_events)
            mbps = (bytes_in_window / elapsed / 1024 / 1024) * 8 if elapsed > 0 else 0
            print(f"| {mbps:6.2f} Mbps")
        else:
            print()
        
        print(f"  YOLO (GPU):      {yolo_fps:6.2f} fps | avg {self.get_avg_time(self.yolo_times):6.2f}ms")
        print(f"  FaceID (GPU):    {face_fps:6.2f} fps | avg {self.get_avg_time(self.face_times):6.2f}ms")
        print(f"  Processing (CPU):{proc_fps:6.2f} fps | avg {self.get_avg_time(self.proc_times):6.2f}ms")
        
        # Queue Status
        print(f"\n📦 QUEUE STATUS:")
        for name, (current, maxsize) in self.queue_stats.items():
            usage_pct = (current * 100.0 / maxsize) if maxsize > 0 else 0
            bar_len = int(usage_pct / 5)  # 20-char bar
            bar = "█" * bar_len + "░" * (20 - bar_len)
            print(f"  {name:15s}: [{bar}] {current}/{maxsize}")
        
        # Memory Usage
        mem = self.get_memory_info()
        print(f"\n💾 MEMORY:")
        print(f"  Process RSS:     {mem['rss_mb']:8.1f} MB ({mem['percent']:5.1f}%)")
        
        # Error Counts
        total_errors = sum(self.errors.values())
        if total_errors > 0:
            print(f"\n⚠️  ERRORS (Total: {total_errors}):")
            for error_type, count in self.errors.items():
                if count > 0:
                    print(f"  {error_type:20s}: {count:3d}")
        
        # Uptime
        uptime_secs = time.time() - self.start_time
        hours = int(uptime_secs // 3600)
        minutes = int((uptime_secs % 3600) // 60)
        secs = int(uptime_secs % 60)
        print(f"\n⏱️  UPTIME: {hours:02d}:{minutes:02d}:{secs:02d}")
        print("="*90 + "\n")


# Global metrics instance
_metrics = None

def get_metrics():
    """Get or create global metrics tracker."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsTracker()
    return _metrics
