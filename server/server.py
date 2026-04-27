"""
Detection Server — TCP + YOLO + MQTT + DB + FastAPI
Main entry point that orchestrates all components.
MULTI-THREADED PIPELINE VERSION
"""

import json
import sys
import socket
import struct
import time
import threading
import queue
from pathlib import Path
import numpy as np
import cv2
import paho.mqtt.client as mqtt
import paho.mqtt.publish as mqtt_publish
import uvicorn

# Đảm bảo module này có thể import từ api.py dù chạy qua __main__
if __name__ == "__main__":
    sys.modules["server"] = sys.modules[__name__]

import config
from detector import PersonDetector
from face_recognition_engine import FaceRecognitionEngine
from servo_controller import SimulatedServoController
from database import init_db, SessionLocal, DetectionEvent, RobotStatus, SensorAlert, Setting
from telegram_notifier import TelegramNotifier
from datetime import datetime, timezone
from metrics import get_metrics

# Shared state Pipeline Queues
frame_queue = queue.Queue(maxsize=2)         # TCP -> YOLO
processing_queue = queue.Queue(maxsize=2)    # YOLO -> Processing/Drawing
face_queue = queue.Queue(maxsize=2)          # YOLO -> FaceID

command_queue = queue.Queue(maxsize=10)      # Commands from API → MQTT

drawn_jpeg = None         # Ảnh đã qua AI để stream lên Web
jpeg_lock = threading.Lock()
latest_alert = None       

# Face Cache (track_id -> FaceMatch) - Smart Tracking Memory
confirmed_face_cache = {}
face_last_attempt_ts = {}
face_cache_lock = threading.Lock()

# GPU Lock for Thread-Safe CUDA
gpu_lock = threading.Lock()

det_fps_display = 0.0     
detector = None
face_engine = None
servo_controller = None
mqtt_client = None
telegram = None           
running = True
target_type = "person"    
locked_target_id = None

# Ensure only one active ESP32 connection at a time.
active_client_lock = threading.Lock()
active_client_conn = None


# ========================== TCP Receiver ==========================

def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data

def handle_client(conn, addr):
    global running, active_client_conn
    print(f"[TCP] ESP32-CAM connected from {addr[0]}:{addr[1]}")

    try:
        with SessionLocal() as db:
            status = db.get(RobotStatus, 1)
            if status:
                status.camera_connected = True
                status.last_seen = datetime.now(timezone.utc)
                db.commit()
    except Exception:
        pass

    frame_count = 0
    total_bytes = 0
    t_start = time.time()
    conn.settimeout(config.TCP_CLIENT_TIMEOUT)
    timeout_count = 0
    metrics = get_metrics()

    try:
        while running:
            try:
                hdr = recv_exact(conn, 4)
            except socket.timeout:
                timeout_count += 1
                # Keep connection alive across temporary network stalls.
                if timeout_count % 3 == 0:
                    print(f"[TCP] Read timeout x{timeout_count} from {addr[0]} (idle)")
                continue
            if hdr is None: break
            timeout_count = 0
            frame_len = struct.unpack("!I", hdr)[0]

            if frame_len == 0 or frame_len > 500_000:
                print(f"[TCP] Bad frame length: {frame_len}")
                break

            try:
                jpeg_data = recv_exact(conn, frame_len)
            except socket.timeout:
                timeout_count += 1
                continue
            if jpeg_data is None: break

            if frame_queue.full():
                try:
                    frame_queue.get_nowait()
                except queue.Empty:
                    pass
            frame_queue.put(jpeg_data)
            
            metrics.record_rx_frame(len(jpeg_data))

            frame_count += 1
            total_bytes += frame_len
            elapsed = time.time() - t_start
            if elapsed >= 3.0:
                fps = frame_count / elapsed
                avg_kb = total_bytes / max(frame_count, 1) / 1024
                print(f"[RX TCP] {fps:.1f} fps | {avg_kb:.1f} KB/frame")
                frame_count = 0
                total_bytes = 0
                t_start = time.time()

    except OSError as e:
        # When a new ESP32 reconnects, the old socket is intentionally closed.
        # Avoid noisy logs for that expected stale-connection path.
        with active_client_lock:
            is_stale_conn = active_client_conn is not conn
        expected_win_errors = {10038, 10053, 10054}
        if is_stale_conn and getattr(e, "winerror", None) in expected_win_errors:
            pass
        else:
            print(f"[TCP] Error: {e}")
            metrics.record_error('tcp_error')
    except Exception as e:
        print(f"[TCP] Error: {e}")
        metrics.record_error('tcp_error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
        print(f"[TCP] Disconnected ({addr[0]})")

        is_active_disconnect = False
        with active_client_lock:
            if active_client_conn is conn:
                active_client_conn = None
                is_active_disconnect = True

        try:
            # Only mark disconnected if this was the currently active socket.
            if is_active_disconnect:
                with SessionLocal() as db:
                    status = db.get(RobotStatus, 1)
                    if status:
                        status.camera_connected = False
                        db.commit()
        except Exception:
            pass

def server_thread():
    global running, active_client_conn
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((config.SERVER_HOST, config.SERVER_PORT))
        srv.listen(1)
        print(f"[TCP] Listening on {config.SERVER_HOST}:{config.SERVER_PORT}")

        while running:
            srv.settimeout(1.0)
            try:
                conn, addr = srv.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 524288)

                # Replace old connection to prevent dual-client contention.
                with active_client_lock:
                    if active_client_conn is not None and active_client_conn is not conn:
                        try:
                            active_client_conn.shutdown(socket.SHUT_RDWR)
                        except Exception:
                            pass
                        try:
                            active_client_conn.close()
                        except Exception:
                            pass
                        print("[TCP] Replaced stale client connection")
                    active_client_conn = conn

                t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
    except Exception as e:
        print(f"[TCP] Bind error: {e}")


# ========================== MQTT ==========================

def _mqtt_rc_to_int(rc):
    if isinstance(rc, (int, float)):
        return int(rc)

    for attr in ("value", "rc"):
        value = getattr(rc, attr, None)
        if isinstance(value, (int, float)):
            return int(value)

    try:
        return int(rc)
    except Exception:
        return 0 if str(rc).strip().lower() == "success" else -1

def _create_mqtt_client():
    client_kwargs = {"client_id": config.MQTT_CLIENT_ID}
    callback_api_version = getattr(mqtt, "CallbackAPIVersion", None)

    if callback_api_version is not None:
        try:
            client = mqtt.Client(
                callback_api_version=callback_api_version.VERSION2,
                **client_kwargs,
            )
            print("[MQTT] Using paho-mqtt callback API v2")
            return client
        except TypeError:
            pass

    print("[MQTT] Using legacy paho-mqtt client API")
    return mqtt.Client(**client_kwargs)

def mqtt_on_connect(client, userdata, flags, rc, properties=None):
    rc_num = _mqtt_rc_to_int(rc)
    if rc_num == 0:
        print(f"[MQTT] Connected to {config.MQTT_BROKER}:{config.MQTT_PORT}")
        client.subscribe(config.MQTT_ALERT_TOPIC, qos=1)
        try:
            with SessionLocal() as db:
                status = db.get(RobotStatus, 1)
                if status:
                    status.mqtt_connected = True
                    db.commit()
        except Exception:
            pass
    else:
        print(f"[MQTT] Connection failed, code={rc_num}")

def mqtt_on_disconnect(client, userdata, *args):
    rc = 0
    if len(args) == 1:
        rc = args[0]
    elif len(args) >= 2:
        rc = args[1]

    rc_num = _mqtt_rc_to_int(rc)
    try:
        with SessionLocal() as db:
            status = db.get(RobotStatus, 1)
            if status:
                status.mqtt_connected = False
                db.commit()
    except Exception:
        pass

    if rc_num != 0:
        print(f"[MQTT] Disconnected unexpectedly, code={rc_num}")


def _extract_robot_state(payload: dict, detail: str) -> str:
    state = str(payload.get("state", "")).strip().upper()
    if state in {"MONITOR", "PATROL", "CHASE", "MANUAL"}:
        return state

    # Backward-compatible fallback when firmware only sends detail text.
    d = (detail or "").upper()
    for candidate in ["MONITOR", "PATROL", "CHASE", "MANUAL"]:
        if candidate in d:
            return candidate
    return ""

def mqtt_on_message(client, userdata, msg):
    try:
        if msg.topic == config.MQTT_ALERT_TOPIC:
            data = json.loads(msg.payload.decode())
            alert_type = data.get("type", "unknown")
            detail = data.get("detail", "")
            distance_mm = data.get("distance_mm", 0)
            pir = data.get("pir", False)
            reported_state = _extract_robot_state(data, detail)

            try:
                with SessionLocal() as db:
                    # Always refresh connectivity heartbeat when ESP32 sends alerts/status.
                    status = db.get(RobotStatus, 1)
                    if status:
                        status.mqtt_connected = True
                        status.last_seen = datetime.now(timezone.utc)
                        if reported_state:
                            status.state = reported_state

                    if alert_type != "status":
                        print(f"[ALERT] {alert_type}: {detail} (dist={distance_mm}mm, pir={pir})")
                        alert = SensorAlert(
                            alert_type=alert_type, detail=detail,
                            distance_mm=distance_mm, pir=pir
                        )
                        db.add(alert)

                    db.commit()
            except Exception as e:
                print(f"[DB] Alert save/update error: {e}")

            global latest_alert
            latest_alert = {
                "type": alert_type, "detail": detail,
                "distance_mm": distance_mm, "pir": pir,
                "state": reported_state,
                "ts": data.get("ts", 0)
            }
    except Exception as e:
        print(f"[MQTT] Message parse error: {e}")

def init_mqtt():
    client = _create_mqtt_client()
    client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)
    client.on_connect = mqtt_on_connect
    client.on_disconnect = mqtt_on_disconnect
    client.on_message = mqtt_on_message
    client.reconnect_delay_set(min_delay=1, max_delay=10)

    try:
        # Use async connect so app boot does not fail if broker is briefly unavailable.
        client.connect_async(config.MQTT_BROKER, config.MQTT_PORT, keepalive=60)
        client.loop_start()
        print(f"[MQTT] Connecting async to {config.MQTT_BROKER}:{config.MQTT_PORT} ...")
        return client
    except Exception as e:
        print(f"[MQTT] Init failed: {e}")
        return None

def publish_position(detected, center=None, pan=0.0, tilt=0.0, target_lost=False, area_pct=0.0):
    if mqtt_client is None or not mqtt_client.is_connected(): return
    if target_lost:
        payload = {"detected": False, "camera_offline": True, "ts": int(time.time() * 1000)}
    else:
        payload = {
            "detected": detected,
            "x": center[0] if center else 0,
            "y": center[1] if center else 0,
            "pan": round(pan, 1),
            "tilt": round(tilt, 1),
            "area_pct": round(area_pct, 1),
            "ts": int(time.time() * 1000)
        }
    mqtt_client.publish(config.MQTT_TOPIC, json.dumps(payload), qos=0)


# ========================== DB API ==========================
def save_detection_event(detected, confidence, track_id, x, y, pan, tilt):
    # Keep event records in DB but do not persist frame images to disk.
    image_path = None

    try:
        with SessionLocal() as db:
            event = DetectionEvent(
                detected=detected, confidence=confidence, track_id=track_id,
                x=x, y=y, pan=round(pan, 1), tilt=round(tilt, 1), image_path=image_path
            )
            db.add(event)
            db.commit()
    except Exception as e:
        print(f"[DB] Save error: {e}")


# ========================== THREAD: Face Recognition ==========================
def face_recognition_thread():
    """Luồng nhận diện khuôn mặt bất đồng bộ."""
    global running, face_engine, confirmed_face_cache
    print("[FaceID Thread] Started")
    
    metrics = get_metrics()
    
    while running:
        try:
            # Lấy ảnh và danh sách chưa xác định
            frame_copy, to_match_dets = face_queue.get(timeout=1.0)
            
            if face_engine is None or len(face_engine.known_names) == 0:
                continue
                
            face_t0 = time.time()
            use_gpu_lock = bool(face_engine and face_engine.device == "CUDA/ONNX")
            if use_gpu_lock:
                with gpu_lock:
                    new_matches = face_engine.match_all_persons(frame_copy, to_match_dets)
            else:
                new_matches = face_engine.match_all_persons(frame_copy, to_match_dets)
            now_ts = time.time()
            
            with face_cache_lock:
                for det_id, match in new_matches.items():
                    # Lưu cả known/unknown để hiển thị trạng thái FaceID trên dashboard.
                    confirmed_face_cache[det_id] = {
                        "match": match,
                        "ts": now_ts,
                        "confirmed": bool(match.is_known and match.similarity >= config.FACE_SIMILARITY_THRESHOLD),
                    }
                    if confirmed_face_cache[det_id]["confirmed"]:
                        print(f"[FaceID] Đã xác định track_id={det_id} là {match.name} ({match.similarity:.2f}). Đã cache!")
            face_ms = (time.time() - face_t0) * 1000
            if len(to_match_dets) > 0:
                metrics.record_face(face_ms)
        except queue.Empty:
            continue
        except Exception as e:
            print(f"[FaceID Thread] Lỗi: {e}")
            metrics.record_error('face_error')


# ========================== THREAD: YOLO ==========================
def yolo_inference_thread():
    """Luồng chính chuyên dùng GPU để YOLO Inference nhanh nhất có thể."""
    global running, target_type, det_fps_display, confirmed_face_cache, face_last_attempt_ts
    print("[YOLO Thread] Started")
    
    det_total_frames = 0
    det_t0 = time.time()
    face_infer_cycle = 0
    metrics = get_metrics()

    while running:
        try:
            jpeg_bytes = None
            while not frame_queue.empty():
                jpeg_bytes = frame_queue.get()
            if jpeg_bytes is None:
                jpeg_bytes = frame_queue.get(timeout=1.0)
                
            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None: continue

            t0 = time.time()
            # 1. Chạy YOLO
            with gpu_lock:
                detections, confirmed = detector.detect_confirmed(frame, target_type=target_type)
            yolo_ms = (time.time() - t0) * 1000
            metrics.record_yolo(yolo_ms)

            # 2. Xóa các Track_ID cũ khỏi Face Cache nếu người đó đã biến mất
            active_ids = {int(d.get("id", -1)) for d in detections if d.get("id") is not None}
            with face_cache_lock:
                stale_ids = [k for k in confirmed_face_cache.keys() if k not in active_ids]
                for sid in stale_ids:
                    cached = confirmed_face_cache.get(sid, {})
                    cached_match = cached.get("match")
                    if cached_match and cached.get("confirmed"):
                        print(f"[FaceID] Người {cached_match.name} (track_id={sid}) đã rời đi. Xoá cache.")
                    del confirmed_face_cache[sid]
                    face_last_attempt_ts.pop(sid, None)

                # Dọn cache UNKNOWN quá hạn để tránh hiển thị nhầm lâu.
                now_ts = time.time()
                expired_unknown = [
                    k for k, v in confirmed_face_cache.items()
                    if not v.get("confirmed") and (now_ts - float(v.get("ts", 0.0))) > config.FACE_CACHE_TTL
                ]
                for sid in expired_unknown:
                    del confirmed_face_cache[sid]
                    face_last_attempt_ts.pop(sid, None)
                    
            # 3. Kích hoạt nhận diện mặt (Định kỳ)
            if face_engine and target_type == "person" and len(detections) > 0:
                face_infer_cycle += 1
                if face_infer_cycle % max(1, config.FACE_MATCH_INTERVAL) == 0:
                    to_match = []
                    # Chỉ quét những đối tượng chưa định danh được ID
                    now_ts = time.time()
                    with face_cache_lock:
                        for det in detections:
                            det_id = int(det.get("id", -1))
                            cached = confirmed_face_cache.get(det_id)
                            # Chỉ bỏ qua khi đã xác định known chắc chắn.
                            if cached and cached.get("confirmed"):
                                continue
                            # Cooldown retry để tránh quét lại UNKNOWN quá dày.
                            last_try = float(face_last_attempt_ts.get(det_id, 0.0))
                            if (now_ts - last_try) < config.FACE_UNKNOWN_RETRY_SEC:
                                continue
                            to_match.append(det)

                    if len(to_match) > config.FACE_MAX_MATCH_PERSONS:
                        to_match = sorted(
                            to_match,
                            key=lambda d: int(d.get("area", 0)),
                            reverse=True,
                        )[:config.FACE_MAX_MATCH_PERSONS]
                                
                    if len(to_match) > 0 and not face_queue.full():
                        # Có ng lạ chưa biết => Ném sang Queue cho Thread Face làm việc
                        with face_cache_lock:
                            mark_ts = time.time()
                            for det in to_match:
                                det_id = int(det.get("id", -1))
                                face_last_attempt_ts[det_id] = mark_ts
                        face_queue.put((frame.copy(), to_match))

            # Tính lại FPS
            det_total_frames += 1
            elapsed_fps = time.time() - det_t0
            if elapsed_fps >= 1.0:
                det_fps_display = det_total_frames / elapsed_fps
                det_total_frames = 0
                det_t0 = time.time()

            # Pass to process queue
            if processing_queue.full():
                try: processing_queue.get_nowait()
                except queue.Empty: pass
            
            processing_queue.put((frame, detections, confirmed, target_type, yolo_ms))

        except queue.Empty:
            continue
        except Exception as e:
            print(f"[YOLO Thread] Lỗi: {e}")
            metrics.record_error('yolo_error')


# ========================== THREAD: Processing & MQTT ==========================
def processing_thread():
    """Luồng xử lý CPU: Tính Servo, Vẽ hình, Lưu DB, Gửi stream."""
    global running, locked_target_id, drawn_jpeg
    print("[Processing Thread] Started")
    
    save_counter = 0
    camera_timeout_count = 0
    metrics = get_metrics()

    while running:
        try:
            # Nếu ko kéo được ảnh mới sau 1 giây ngầm hiểu cam đã disconnect
            frame, detections, confirmed, cur_target_type, yolo_ms = processing_queue.get(timeout=1.0)
            camera_timeout_count = 0
        except queue.Empty:
            camera_timeout_count += 1
            if camera_timeout_count >= 2:
                publish_position(False, target_lost=True)
            continue
        except Exception as e:
            print(f"[Processing Thread] Queue error: {e}")
            metrics.record_error('proc_error')
            continue
            
        try:
            proc_t0 = time.time()
            h, w = frame.shape[:2]
            if w != servo_controller.frame_width or h != servo_controller.frame_height:
                servo_controller.frame_width = w
                servo_controller.frame_height = h
                servo_controller.frame_center_x = w // 2
                servo_controller.frame_center_y = h // 2

            main_person = detector.get_largest_person(detections, target_id=locked_target_id)
            if main_person:
                locked_target_id = main_person.get('id')
            else:
                locked_target_id = None

            pan, tilt = 0.0, 0.0
            if main_person:
                center = main_person["center"]
                servo_controller.update(center)
                pan, tilt = servo_controller.get_servo_angles()
                # Tính % diện tích bbox so với khung hình
                frame_area = w * h
                person_area = main_person.get("area", 0)
                area_pct = (person_area / frame_area * 100) if frame_area > 0 else 0.0
                publish_position(True, center, pan, tilt, area_pct=area_pct)

                if confirmed:
                    save_counter += 1
                    if save_counter >= 5:
                        save_counter = 0
                        threading.Thread(target=save_detection_event, args=(
                            True, main_person["confidence"], main_person.get("id"),
                            center[0], center[1], pan, tilt
                        ), daemon=True).start()
                        
                    if telegram:
                        robot_state = "UNKNOWN"
                        # Gửi Tele không block frame
                        threading.Thread(target=telegram.send_detection, args=(
                            frame.copy(), main_person["confidence"], center, robot_state
                        ), daemon=True).start()

                # Vẽ Box
                x1, y1, x2, y2 = main_person['bbox']
                color = (0, 0, 255) if locked_target_id == main_person.get('id') else (0, 255, 0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.circle(frame, center, 5, color, -1)

                # Vẽ Face Label nếu ĐÃ CÓ TRONG CACHE CHẮC CHẮN
                face_label = ""
                main_id = int(main_person.get('id', -1))
                with face_cache_lock:
                    cached = confirmed_face_cache.get(main_id)
                    if cached:
                        face_match = cached.get("match")
                        if face_match is not None:
                            fx1, fy1, fx2, fy2 = face_match.face_bbox_global
                            is_confirmed = bool(cached.get("confirmed"))
                            face_color = (0, 255, 0) if is_confirmed else (0, 165, 255)
                            cv2.rectangle(frame, (fx1, fy1), (fx2, fy2), face_color, 2)
                            face_label = f" {face_match.name}({face_match.similarity:.2f})"

                cv2.putText(frame, f"ID:{main_person.get('id')} Conf:{main_person['confidence']:.2f}{face_label}",
                           (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            else:
                publish_position(False)
                label_text = "NO TARGET" if cur_target_type == "pet" else "NO PERSON"
                cv2.putText(frame, label_text, (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

            # Vẽ thông số FPS
            cv2.putText(frame, f"AI FPS: {det_fps_display:.1f}", (w - 150, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                       
            if not config.HEADLESS:
                cv2.putText(frame, f"YOLO: {yolo_ms:.1f}ms", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                cv2.putText(frame, f"Pan:{pan:.1f} Tilt:{tilt:.1f}", (10, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 100, 0), 2)

            with face_cache_lock:
                known_count = sum(1 for v in confirmed_face_cache.values() if v.get("confirmed"))
                unknown_count = sum(1 for v in confirmed_face_cache.values() if not v.get("confirmed"))
            cv2.putText(frame, f"Face Known:{known_count} Unknown:{unknown_count}", (10, h - 15),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

            # Nén hình và set kết quả stream
            proc_ms = (time.time() - proc_t0) * 1000
            metrics.record_processing(proc_ms)
            metrics.update_queues(frame_queue, processing_queue, face_queue)
            metrics.display()
            
            ret, encoded_img = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
            if ret:
                with jpeg_lock:
                    drawn_jpeg = encoded_img.tobytes()

            if not config.HEADLESS:
                cv2.imshow("Robot Server Stream", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    running = False

        except Exception as e:
            print(f"[Process Thread] Lỗi: {e}")
            metrics.record_error('processing_error')


# ========================== API & MAIN ==========================

def api_thread():
    from api import app as fastapi_app
    uvi_config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=config.API_PORT, log_level="warning")
    uvicorn.Server(uvi_config).run()

def command_publisher():
    while running:
        try:
            cmd_payload = command_queue.get(timeout=1.0)
            mqtt_publish.single(
                config.MQTT_COMMAND_TOPIC, payload=cmd_payload, qos=0,
                hostname=config.MQTT_BROKER, port=config.MQTT_PORT,
                client_id="cmd_publisher",
                auth={"username": config.MQTT_USERNAME, "password": config.MQTT_PASSWORD} if config.MQTT_USERNAME else None,
            )
            print(f"[CMD] Published: {cmd_payload}")
        except queue.Empty: continue
        except Exception as e: print(f"[CMD] Publish error: {e}")

def main():
    global detector, face_engine, servo_controller, mqtt_client, telegram, running
    print("=" * 60)
    print("  ROBOT SECURITY SERVER (MULTI-THREADED PIPELINE)")
    print("  TCP:8765 | API:8000 | MQTT | DB")
    print("=" * 60)

    init_db()

    print("[YOLO] Loading model...")
    detector = PersonDetector(enable_preprocess=config.YOLO_PREPROCESS_ENABLED)
    servo_controller = SimulatedServoController(640, 480)

    if config.FACE_RECOGNITION_ENABLED:
        embedding_path = Path(config.FACE_EMBEDDINGS_PATH)
        if not embedding_path.is_absolute():
            embedding_path = Path(__file__).resolve().parent / embedding_path
        try:
            face_engine = FaceRecognitionEngine(
                embedding_db_path=str(embedding_path),
                similarity_threshold=config.FACE_SIMILARITY_THRESHOLD,
                det_size=config.FACE_DET_SIZE,
                max_crop_side=config.FACE_MAX_CROP_SIDE,
            )
            if face_engine.device != "CUDA/ONNX" and config.FACE_DISABLE_ON_CPU:
                print("[FaceID] Disabled: running on CPU would severely reduce FPS (set FACE_DISABLE_ON_CPU=0 to force)")
                face_engine = None
            else:
                print(f"[FaceID] Enabled | device={face_engine.device} | known={len(face_engine.known_names)}")
        except Exception as e:
            print(f"[FaceID] Disabled (init error): {e}")

    mqtt_client = init_mqtt()
    telegram = TelegramNotifier()
    try:
        with SessionLocal() as db:
            saved = {s.key: s.value for s in db.query(Setting).filter(Setting.key.like("telegram_%")).all()}
            if saved:
                telegram.update_config(
                    bot_token=saved.get("telegram_bot_token"),
                    chat_id=saved.get("telegram_chat_id"),
                    enabled=saved.get("telegram_enabled") == "1" if "telegram_enabled" in saved else None,
                    cooldown=int(saved["telegram_cooldown"]) if "telegram_cooldown" in saved else None,
                )
    except Exception: pass

    # Khởi chạy các Threads
    threads = [
        threading.Thread(target=server_thread, daemon=True, name="TCP_Receiver"),
        threading.Thread(target=command_publisher, daemon=True, name="MQTT_CmdPub"),
        threading.Thread(target=api_thread, daemon=True, name="FastAPI"),
        threading.Thread(target=yolo_inference_thread, daemon=True, name="YOLO"),
        threading.Thread(target=processing_thread, daemon=True, name="Processing")
    ]
    if face_engine:
        threads.append(threading.Thread(target=face_recognition_thread, daemon=True, name="FaceID"))

    for t in threads: t.start()

    print("[Server] Đã khởi chạy hoàn toàn các khối chức năng. Ấn Ctrl+C để thoát.")
    try:
        while running: time.sleep(1)
    except KeyboardInterrupt:
        running = False

    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
    if not config.HEADLESS: cv2.destroyAllWindows()
    print("[Server] Stopped.")

if __name__ == "__main__":
    main()
