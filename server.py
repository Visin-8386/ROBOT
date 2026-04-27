"""
WebSocket Server - Person Detection for ESP32
Server phát hiện người, nhận ảnh từ ESP32-CAM và gửi lệnh điều khiển cho ESP32
"""

from flask import Flask
from flask_socketio import SocketIO, emit
import base64
import numpy as np
import cv2
import config
from detector import PersonDetector
from servo_controller import SimulatedServoController

app = Flask(__name__)
app.config['SECRET_KEY'] = 'robot_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Khởi tạo detector và servo controller
print("[Server] Đang khởi tạo...")
detector = PersonDetector()
# Frame mặc định 640x480 - sẽ cập nhật khi nhận frame đầu tiên
servo_controller = SimulatedServoController(640, 480)

# State machine cho chuỗi điều khiển:
# 1) Servo căn người vào giữa
# 2) Xe quay theo góc pan đã bù
# 3) Servo trả về góc ban đầu (0, 0)
tracking_phase = "CENTERING_SERVO"
stable_center_frames = 0
pending_rotate_angle = 0.0
print("[Server] Sẵn sàng!")


@app.route('/health')
def health():
    """Health check endpoint"""
    return {'status': 'ok', 'message': 'Server đang chạy'}


@socketio.on('connect')
def handle_connect():
    """Xử lý khi client kết nối"""
    print("[Server] Client đã kết nối!")
    emit('status', {'message': 'Kết nối thành công!'})


@socketio.on('disconnect')
def handle_disconnect():
    """Xử lý khi client ngắt kết nối"""
    print("[Server] Client đã ngắt kết nối!")


@socketio.on('frame')
def handle_frame(data):
    """
    Xử lý frame ảnh từ ESP32-CAM
    
    Input: {'image': base64_encoded_jpeg}
    Output: emit 'result' với detection data
    """
    global tracking_phase, stable_center_frames, pending_rotate_angle
    try:
        # Decode base64 image
        img_data = base64.b64decode(data['image'])
        nparr = np.frombuffer(img_data, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if frame is None:
            emit('result', {'error': 'Không thể decode ảnh'})
            return
        
        # Cập nhật kích thước frame nếu khác
        h, w = frame.shape[:2]
        if w != servo_controller.frame_width or h != servo_controller.frame_height:
            servo_controller.frame_width = w
            servo_controller.frame_height = h
            servo_controller.frame_center_x = w // 2
            servo_controller.frame_center_y = h // 2
        
        # Phát hiện người
        detections = detector.detect(frame)
        main_person = detector.get_largest_person(detections)
        
        if main_person:
            person_center = main_person['center']
            vehicle_command = None
            servo_controller.calculate_error(person_center)

            if tracking_phase == "CENTERING_SERVO":
                servo_controller.update(person_center)
                if servo_controller.is_centered():
                    stable_center_frames += 1
                else:
                    stable_center_frames = 0

                if stable_center_frames >= config.CENTER_STABLE_FRAMES:
                    current_pan, _ = servo_controller.get_servo_angles()
                    if abs(current_pan) >= config.CAR_ROTATE_MIN_ANGLE:
                        pending_rotate_angle = current_pan
                        tracking_phase = "ROTATE_VEHICLE"
                    else:
                        stable_center_frames = 0

            elif tracking_phase == "ROTATE_VEHICLE":
                if pending_rotate_angle > 0:
                    rotate_direction = "RIGHT"
                elif pending_rotate_angle < 0:
                    rotate_direction = "LEFT"
                else:
                    rotate_direction = "NONE"

                vehicle_command = {
                    'action': 'rotate_vehicle',
                    'direction': rotate_direction,
                    'signed_angle_deg': round(pending_rotate_angle, 2),
                    'angle_deg': round(abs(pending_rotate_angle), 2)
                }
                tracking_phase = "RETURN_SERVO"

            elif tracking_phase == "RETURN_SERVO":
                servo_controller.return_to_center_step(config.SERVO_RETURN_SPEED)
                if servo_controller.is_servo_near_origin(config.SERVO_RETURN_EPSILON):
                    servo_controller.reset()
                    tracking_phase = "CENTERING_SERVO"
                    stable_center_frames = 0
                    pending_rotate_angle = 0.0

            pan, tilt = servo_controller.get_servo_angles()
            direction = servo_controller.get_direction_text()
            is_centered = servo_controller.is_centered()
            need_vehicle_rotate = round(pan, 2)

            result = {
                'detected': True,
                'confidence': round(main_person['confidence'], 2),
                'person_x': person_center[0],
                'person_y': person_center[1],
                'pan': round(pan, 2),
                'tilt': round(tilt, 2),
                'direction': direction,
                'centered': is_centered,
                'phase': tracking_phase,
                'stable_center_frames': stable_center_frames,
                'need_vehicle_rotate_deg': need_vehicle_rotate,
                'vehicle_command': vehicle_command,
                'servo_returning': tracking_phase == "RETURN_SERVO"
            }
        else:
            tracking_phase = "CENTERING_SERVO"
            stable_center_frames = 0
            pending_rotate_angle = 0.0
            result = {
                'detected': False,
                'confidence': 0,
                'person_x': 0,
                'person_y': 0,
                'pan': 0,
                'tilt': 0,
                'direction': 'NO PERSON',
                'centered': False,
                'phase': tracking_phase,
                'stable_center_frames': 0,
                'need_vehicle_rotate_deg': 0.0,
                'vehicle_command': None,
                'servo_returning': False
            }
        
        emit('result', result)
        
    except Exception as e:
        print(f"[Server] Lỗi: {e}")
        emit('result', {'error': str(e)})


@socketio.on('reset_servo')
def handle_reset():
    """Reset servo về vị trí trung tâm"""
    global tracking_phase, stable_center_frames, pending_rotate_angle
    servo_controller.reset()
    tracking_phase = "CENTERING_SERVO"
    stable_center_frames = 0
    pending_rotate_angle = 0.0
    emit('result', {
        'message': 'Servo đã reset',
        'pan': 0,
        'tilt': 0,
        'phase': tracking_phase,
        'vehicle_command': None
    })


if __name__ == '__main__':
    print("=" * 50)
    print("PERSON DETECTION WEBSOCKET SERVER")
    print("=" * 50)
    print("[Server] Chạy tại ws://0.0.0.0:5000")
    print("[Server] ESP32-CAM gửi ảnh qua event 'frame'")
    print("[Server] ESP32 motor nhận kết quả qua event 'result'")
    print("=" * 50)
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
