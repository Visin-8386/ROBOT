# 📋 THUẬT TOÁN NÉ VẬT CẢN - CHI TIẾT ĐỦ CẤP ĐỘ CHUYÊN GIA

## 🎯 GIỚI THIỆU CHUNG

**Dự án**: AI Guard Robot (ESP32-based Security Robot)  
**Thành phần NÉ VẬT CẢN**: STM32 (trong SIN thư mục)  
**Cảm biến chính**: HC-SR04 Ultrasonic + Servo Pan tính vị trí  
**Tốc độ update**: 50ms (20 Hz)

---

# I. KIẾN TRÚC TỔNG THỂ

## 1. Sơ đồ khối hệ thống

```
┌─────────────────────────────────────────────────────────┐
│                    ROBOT SECURITY SYSTEM                │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │ ┌────────────────┐    ┌────────────────────────┐ │  │
│  │ │  HC-SR04       │◄──►│  Servo Pan Controller  │ │  │
│  │ │ (Ultrasonic)   │    │  (Camera servo)       │ │  │
│  │ │ - TRIG→GPIO9   │    │  - PWM: GPIO46        │ │  │
│  │ │ - ECHO←GPIO10  │    │  - Range: 1000-2000µs │ │  │
│  │ └────────────────┘    └────────────────────────┘ │  │
│  │         ▲                      ▲                 │  │
│  │         │ distance_mm          │ servo_us       │  │
│  │         │                      │                 │  │
│  │ ┌───────┴──────────────────────┴──────────────┐ │  │
│  │ │  ÉTAT MACHINE (Patrol/Chase/Manual)       │ │  │
│  │ │  - Phân loại vật cản (Small/Large)        │ │  │
│  │ │  - Lượn nhẹ (Soft Avoidance) 600-500mm   │ │  │
│  │ │  - Quét ±45° (Full Scan) 500mm<max       │ │  │
│  │ │  - Tránh bị kẹt (Anti-Stuck)             │ │  │
│  │ └──────┬──────────────────┬──────────────────┘ │  │
│  │        │                  │                    │  │
│  │        ▼                  ▼                    │  │
│  │  ┌─────────────────┐  ┌─────────────────┐    │  │
│  │  │  Motor Driver   │  │   PIR Sensor    │    │  │
│  │  │  (TB6612)       │  │  (Optional)     │    │  │
│  │  │  Left/Right     │  │                 │    │  │
│  │  │  PWM 20kHz      │  │                 │    │  │
│  │  └─────────────────┘  └─────────────────┘    │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

# II. CÔNG THỨC VÀ NGUYÊN LÝ

## A. HC-SR04 Ultrasonic Distance Measurement

### Phương trình tính khoảng cách

$$\text{Distance (mm)} = \frac{\text{pulse\_us} \times 343}{2000}$$

Trong đó:
- **pulse_us**: Độ dài xung ECHO (microseconds)
- **343**: Tốc độ âm thanh trong không khí @ 20°C (m/s)
- **2000**: Hệ số chuyển đổi (chia 2 vì im về + về, nhân 1000/2)

### Chi tiết công thức

```
Âm thanh đi từ cảm biến → chạm vật → quay về

Thời gian đi-về = pulse_us (microseconds)
Quãng đường một chiều = (pulse_us/2) × (343 m/s) / 1,000,000
                      = pulse_us × 343 / 2,000,000 meter
                      = pulse_us × 343 / 2000 mm

Ví dụ:
  pulse = 5882 µs
  distance = (5882 × 343) / 2000 = 1000 mm = 1 meter ✓

  pulse = 58.82 µs
  distance = (58.82 × 343) / 2000 = 10 mm ✓
```

### Quy trình đo khoảng cách

```
t0: Set TRIG = HIGH (1)              [+10µs]
t1: Set TRIG = LOW  (0)
    └─ Sensor phát xung siêu âm

t2: Chờ ECHO PIN lên HIGH            [+5ms max]
    └─ start_time = t2

t3: Chờ ECHO PIN xuống LOW           [+35ms max]
    └─ end_time = t3

t4: Tính pulse_us = end_time - start_time
    └─ if pulse_us ≤ 0 or > 35000µs → ERROR

t5: Áp dụng công thức
    distance = (pulse_us × 343) / 2000
    
t6: Validate
    if distance < 20mm or > 4000mm
    └─ Status = NO_TARGET
    else
    └─ Status = OK
```

---

## B. Servo PWM Control

### Mapping Servo Position → PWM

| Servo Position | PWM (µs) | Độ | Ý nghĩa |
|---|---|---|---|
| **CENTER** | 1500 | 90° | Phía trước (nhìn về phía trước) |
| **LEFT** | 2000 | 135° | Quay trái 45° |
| **RIGHT** | 1000 | 45° | Quay phải 45° |

### Zone Detection

```
Servo_CENTER = 1500 µs
SWEEP_CENTER_ZONE = ±144 µs (± 13 độ)

┌────────────────────────────────────────────┐
│ CENTER ZONE = [1356, 1644] µs               │
│ ↓                                           │
│ [-13°, +13°] từ phía trước                 │
│                                            │
│ Nếu vật cản phát hiện tại zone này         │
│ → Vật lớn (LỚN) chắc chắn                  │
│ → Cần quét ±45° hoàn chỉnh                 │
└────────────────────────────────────────────┘
```

---

## C. Motor PWM Control

### Điều khiển L298N Motor Driver

```c
ESP32-S3 Pinout:
┌──────────────────────────────────────────┐
│ Motor A (Bánh Trái) — L298N               │
│  • PWM: GPIO4 (LEDC Channel 0)           │
│  • IN1: GPIO6 (Direction)                │
│  • IN2: GPIO5 (Direction)                │
├──────────────────────────────────────────┤
│ Motor B (Bánh Phải) — L298N               │
│  • PWM: GPIO17 (LEDC Channel 1)          │
│  • IN1: GPIO15 (Direction)               │
│  • IN2: GPIO16 (Direction)               │
└──────────────────────────────────────────┘

PWM Configuration:
  • Resolution: 8-bit (0-255)
  • Frequency: 20 kHz
  • Soft-start ramp: ±40 per 15ms
```

### Speed Mapping

| Hành động | Speed Value | % Duty | Ghi chú |
|---|---|---|---|
| `SPEED_PATROL` | 165 | 64.7% | Tuần tra bình thường |
| `SPEED_CHASE` | 200 | 78.4% | Đuổi theo người |
| `SPEED_TURN` | 255 | 100% | Quay tại chỗ |
| Slow (lượn nhẹ) | 90 | 35.3% | 55% của SPEED_PATROL |

---

# III. NGƯỠNG PHÁT HIỆN VẬT CẢN

## Các Threshold Quan Trọng

```c
// config.h - Line 138+

SOFT_AVOID_DIST_MAX = 600 mm    ← Bắt đầu lượn nhẹ (1 bánh giảm 55%)
OBSTACLE_DIST_MM = 500 mm       ← Phát hiện vật cản → increment confidence
HARD_STOP_DIST_MM = 350 mm      ← Quá gần → dừng khẩn cấp
STOP_DIST_MM = 550 mm           ← Chế độ CHASE, giảm tốc
SCAN_MIN_CLEAR_MM = 450 mm      ← Ngưỡng "thông thoáng" để rẽ

SWEEP_AMP_US = 278 µs = ±25°    ← Swing servo khi tuần tra
SWEEP_HALF_PERIOD_MS = 900 ms   ← Mỗi 900ms đổi hướng (chu kỳ 1.8s)
SWEEP_CENTER_ZONE_US = 144 µs   ← ±13° zone phía trước
```

## Mối Quan Hệ Các Threshold

```
Distance (mm)
    ↑
    │         DANGER!    OBSTACLE!   SOFT_AVOID      CLEAR
    │         ────────   ─────────   ──────────     ──────
6000│
    │
    │
1500│
    │
 600│ ┌─────────────────────────────────────────────────────┐
    │ │                 (SAFE ZONE)                         │
 550│ │ ┌──────────────────────────────────────────────────┐│
    │ │ │ (CHASE SLOWDOWN)                                ││
 500│ │ │┌────────────────────────────────────────────────┐││
    │ │ ││ (OBSTACLE DETECTED)                        ││││
    │ │ ││ confidence++                               ││││
    │ │ ││ if confidence ≥ 2 or at_center:            ││││
    │ │ ││   → LARGE (full scan ±45°)                 ││││
    │ │ ││ else:                                      ││││
    │ │ ││   → SMALL (bypass 1s)                      ││││
    │ │ ││                                            ││││
 350│ ││┌─────────────────────────────────────────────┐│││
    │ │││ HARD STOP ZONE                             │││││
    │ │││ motor_stop() ← gặp nguy hiểm                 │││││
    │ │││                                             ││││
    │ │││ if distance < 350:                          │││││
    │ │││   reverse(300ms) trước khi scan             │││││
    │ └┴┴─────────────────────────────────────────────┴┴┘│
    │                                                    │
    └─────────────────────────────────────────────────────┘
        0mm  (too close, error)
```

---

# IV. THUẬT TOÁN PHÂN LOẠI VẬT CẢN

## Logic Classification

### Định Nghĩa

```c
bool at_center = (obstacle_detect_us >= (1500-144)) && 
                 (obstacle_detect_us <= (1500+144));
                 // = [1356 .. 1644] µs = ±13° phía trước

bool is_large = (obstacle_confidence >= 2) || at_center;

if (is_large)
  → LARGE OBSTACLE (vật lớn: tường, ghế lớn, ...)
else
  → SMALL OBSTACLE (vật nhỏ: chân bàn, chân ghế hẹp, ...)
```

### Lập Bảng Quyết Định

| Hoàn cảnh | Confidence | Position | Phân loại | Hành động |
|---|---|---|---|---|
| Phát hiện lần 1 tại CENTER | 1 | [1356-1644] | LARGE | Scan ±45° |
| Phát hiện lần 1 tại CORNER | 1 | <1356 hoặc >1644 | SMALL | Bypass 1s |
| Phát hiện 2 lần liên tiếp | 2+ | anywhere | LARGE | Scan ±45° |
| Scan chưa xong | <1 | - | WAITING | Motor stop |

---

# V. STATE MACHINE CHI TIẾT

## A. Obstacle Scan State Machine

```
STATE                    TIMEOUT/CONDITION              ACTION
═════════════════════════════════════════════════════════════════

SCAN_IDLE
  ├─ Điều kiện: distance < OBSTACLE (500mm)
  └─ Sự kiện: confidence ≥ 1 & !is_small
     ↓ → start_obstacle_scan()

SCAN_MOVING_LEFT
  ├─ Hành động: servo_move_smooth(1750µs, 10µs/ms)
  ├─ Timeout: servo_is_moving() = FALSE
  └─ Thời gian dự tính: (2000-1500)/10 = 50ms + buffer
     ↓

SCAN_SETTLE_LEFT
  ├─ Hành động: vTaskDelay(400ms) — chờ cơ học ổn định
  └─ Khi timeout:
       scan_dist_left = sensor_get_distance_mm()
     ↓

SCAN_MOVING_RIGHT
  ├─ Hành động: servo_move_smooth(1250µs, 10µs/ms)
  ├─ Timeout: servo_is_moving() = FALSE
  └─ Thời gian dự tính: ~50ms
     ↓

SCAN_SETTLE_RIGHT
  ├─ Hành động: vTaskDelay(400ms)
  └─ Khi timeout:
       scan_dist_right = sensor_get_distance_mm()
     ↓

SCAN_RETURNING
  ├─ Hành động: servo_move_smooth(1500µs, 10µs/ms)
  ├─ Timeout: servo_is_moving() = FALSE hoặc 1500ms
  └─ Khi xong: QUYẾT ĐỊNH HƯỚNG RẼ
     ├─ if (scan_left = 0 && scan_right = 0)
     │    → scan_turn_left = TRUE (fallback trái)
     ├─ if (scan_left = 0)
     │    → scan_turn_left = FALSE (rẽ phải)
     ├─ if (scan_right = 0)
     │    → scan_turn_left = TRUE (rẽ trái)
     └─ else
          → scan_turn_left = (scan_left ≥ scan_right)?
     ↓

SCAN_DONE
  └─ Khi: do_patrol() kĩ nhận
     ├─ Thực hiện: perform_pivot_turn(scan_turn_left, SPEED_TURN)
     ├─ Duration: 600-1000ms (tùy khoảng cách)
     └─ State → SCAN_IDLE
```

**Total Scan Time**: 50 + 400 + 50 + 400 + 50 = ~950ms

## B. Patrol Sweep State Machine

```
Điều kiện: sweep_active = TRUE

SWEEP_CYCLE:
  ├─ Hiện tại: servo = 1500 µs (CENTER)
  ├─ Time elapsed < 900ms?
  │   └─ Không làm gì
  │
  ├─ Time elapsed ≥ 900ms?
  │   ├─ Đổi hướng: sweep_dir_left = !sweep_dir_left
  │   └─ Tính target:
  │       if sweep_dir_left:
  │         target = 1500 + 278 = 1778 µs (quét trái +25°)
  │       else:
  │         target = 1500 - 278 = 1222 µs (quét phải -25°)
  │
  └─ servo_move_smooth(target, 2.5µs/ms)
     └─ Khoảng thời gian: 278/2.5 = ~112ms
        Tiếp tục tăng/giảm tốc mịn mà không nhảy đột ngột
```

**Chu kỳ**: 1800ms (±25° quét lắc)

---

# VI. THUẬT TOÁN NÉ VẬT CẢN (SOFT AVOIDANCE)

## Điều Kiện Kích Hoạt

```c
if (600 >= distance_mm >= 500)  // SOFT_AVOID range
   && scan_state == SCAN_IDLE
   && !patrol_turning
```

## Công Thức Differential Steering

### Bước 1: Xác định hướng vật cản

```c
uint16_t servo_pos = servo_get_current_pos();

if (servo_pos < 1500):
   → Vật cản ở PHẢI (servo quay sang phải)
   → Nên rẽ TRÁI để tránh
   
if (servo_pos >= 1500):
   → Vật cản ở TRÁI (servo quay sang trái)
   → Nên rẽ PHẢI để tránh
```

### Bước 2: Tính tốc độ từng bánh

$$\text{slow\_speed} = \frac{\text{SPEED\_PATROL} \times 55}{100} = \frac{165 \times 55}{100} = 90$$

### Bước 3: Áp dụng Motor Control

```c
if (rẽ_trái):
    motor_left = slow_speed = 90
    motor_right = SPEED_PATROL = 165
    → Bánh phải nhanh hơn, robot xoay trái
    
if (rẽ_phải):
    motor_left = SPEED_PATROL = 165
    motor_right = slow_speed = 90
    → Bánh trái nhanh hơn, robot xoay phải
```

### Biểu Diễn Hình Học

```
    VẬT CẢN
    (phía phải)
         ↑
         │
    ┌────┴────┐
    │ servo>  │  Servo quay phải (>center)
    │  1500µs │
    └────┬────┘
         │
    ────►●◄────  ROBOT
    R=165   L=90
    
    Bánh TRÁI (L) chậm hơn → Robot lượn TRÁI
    (tránh vật cản ở PHẢI)
```

---

# VII. HANDLE SMALL OBSTACLE

## Tình Huống

```
Điều kiện:
  • Phát hiện lần 1 (confidence = 1)
  • Vị trí servo ∉ CENTER_ZONE (ngoài ±13°)
  → Nghi ngờ = chân bàn, chân ghế hẹp

Ví dụ:
  distance = 480mm
  servo_pos = 1200µs (quay phải, <1500)
  confidence = 1
  → Vật nhỏ nằm BÊN PHẢI
```

## Sequence Xử Lý

```
Step 1: patrol_sweep_stop()
        └─ Dừng dao động servo, servo trở về CENTER

Step 2: bool bypass_left = (obstacle_detect_us < 1500)
        ├─ true = rẽ TRÁI (vật bên PHẢI nên rẽ ngược)
        └─ false = rẽ PHẢI

Step 3: motor_stop() → vTaskDelay(150ms)
        └─ Dừng lại, chờ ổn định

Step 4: perform_pivot_turn(bypass_left, SPEED_TURN=255, 0)
        └─ Rẽ tại chỗ 600ms (quay khoảng 90°)

Step 5: motor_forward(SPEED_PATROL=165)
        └─ Tiến 300ms vượt qua vật nhỏ

Step 6: Reset:
        ├─ obstacle_confidence = 0
        ├─ obstacle_detect_us = 0
        └─ patrol_sweep_start()

╔════════════════════════════════════╗
║ TỔNG THỜI GIAN: ~1050ms (~1 giây) ║
╚════════════════════════════════════╝
```

---

# VIII. HANDLE LARGE OBSTACLE

## Tình Huống

```
Điều kiện:
  • Phát hiện ≥ 2 lần liên tiếp (confidence ≥ 2), HOẶC
  • Phát hiện lần 1 tại CENTER_ZONE (servo ∈ [1356..1644])
  → Vật lớn (tường, ghế lớn, ...)

Ví dụ:
  distance = 480mm
  servo_pos = 1500µs (trực tiếp phía trước)
  confidence = 1
  → VẬT LỚN (tại center)
```

## Sequence Xử Lý

```
Step 1: patrol_sweep_stop()
        └─ Dừng sweep servo

Step 2: motor_stop() → vTaskDelay(OBSTACLE_STOP_MS=220ms)
        └─ Dừng motor, chờ ổn định

Step 3: if (distance < HARD_STOP_DIST_MM = 350):
        ├─ motor_backward(SPEED_PATROL - 20 = 145)
        ├─ vTaskDelay(300ms) ← lùi 300ms
        └─ motor_stop() → vTaskDelay(70ms)
        (Nếu quá gần, lùi trước khi quét)

Step 4: start_obstacle_scan()
        ├─ SCAN_MOVING_LEFT → 50ms
        ├─ SCAN_SETTLE_LEFT → 400ms (đo distance_left)
        ├─ SCAN_MOVING_RIGHT → 50ms
        ├─ SCAN_SETTLE_RIGHT → 400ms (đo distance_right)
        ├─ SCAN_RETURNING → 50ms
        └─ SCAN_DONE → Quyết định hướng rẽ
           (~1400ms tổng)

Step 5: Xử lý kết quả scan:
        ├─ if (scan_left < 450 && scan_right < 450):
        │    └─ Extra reverse 400ms (cả 2 bên có vật)
        │
        ├─ Nếu scan ≥ 4 lần xoay liên tiếp:
        │    └─ Đảo hướng + thêm 200ms (tránh xoay vô hạn)
        │
        └─ perform_pivot_turn(scan_turn_left, SPEED_TURN, distance)
           └─ Rẽ 600-800ms

Step 6: Reset:
        ├─ obstacle_confidence = 0
        ├─ obstacle_detect_us = 0
        └─ patrol_sweep_start()

╔════════════════════════════════════════╗
║ TỔNG THỜI GIAN: ~2-3 giây (tùy trường hợp)║
╚════════════════════════════════════════╝
```

---

# IX. ANTI-STUCK MECHANISM

## Phát Hiện Kẹt

```c
Check mỗi: SWEEP_HALF_PERIOD_MS × 2 = 1800ms

Điều kiện kẹt:
  • 0 < distance < 1500mm
  • !patrol_turning
  • scan_state = SCAN_IDLE

So sánh với lần kiểm tra trước:
  ├─ distance_delta = |current_dist - last_dist|
  ├─ angle_delta = |current_angle - last_angle|
  │
  └─ if (distance_delta < 30mm && angle_delta < 60us):
       stuck_count++
     else:
       stuck_count = 0
       last_dist = current_dist
       last_angle = current_angle

Nếu stuck_count ≥ 4:
  → TRIGGER ESCAPE SEQUENCE
```

## Escape Sequence

```
Step 1: motor_stop() → vTaskDelay(100ms)

Step 2: motor_backward(SPEED_PATROL - 20 = 145)
        └─ Lùi với tốc độ yếu hơn
        └─ vTaskDelay(1000ms) — lùi 1 giây

Step 3: motor_stop() → vTaskDelay(100ms)

Step 4: perform_pivot_turn(true, SPEED_TURN, 0)
        └─ Rẽ TRÁI tại chỗ
        └─ vTaskDelay(700ms) — quay ~80°

Step 5: patrol_sweep_start()
        └─ Tiếp tục tuần tra

╔════════════════════════════════════════╗
║ TỔNG THỜI GIAN: ~2 giây (lùi + rẽ)     ║
╚════════════════════════════════════════╝
```

## Ví Dụ Kẹt Phát Hiện

```
Tình huống:
  Robot cố chạy vào một khe hẹp, cảm biến phát hiện vật
  nhưng motor chưa có sức đẩy đủ thoát ra.

Check 1 (t=0ms):      distance=550mm, angle=1500us, stuck_count=0
Check 2 (t=1800ms):   distance=552mm, angle=1502us
                      delta_d=2<30 ✓, delta_a=2<60 ✓
                      → stuck_count=1

Check 3 (t=3600ms):   distance=556mm, angle=1501us
                      delta_d=4<30 ✓
                      → stuck_count=2

Check 4 (t=5400ms):   distance=560mm, angle=1500us
                      delta_d=4<30 ✓
                      → stuck_count=3

Check 5 (t=7200ms):   distance=563mm, angle=1499us
                      delta_d=3<30 ✓
                      → stuck_count=4 ≥ THRESHOLD
                      
TRIGGER ANTI-STUCK:
  ├─ motor_stop() 100ms
  ├─ motor_backward(145) 1000ms
  ├─ motor_stop() 100ms
  ├─ perform_pivot_turn(true, 255) 700ms
  └─ Tiếp tục tuần tra
```

---

# X. FLOW QUYẾT ĐỊNH TOÀN BỘ (PSEUDO CODE)

```python
def main_loop():
    while True:
        # Chu kỳ: 50ms
        
        # 1. Đọc cảm biến
        distance_mm = sensor_get_distance_mm()
        servo_pos_us = servo_get_current_pos()
        
        # 2. Nếu chế độ PATROL
        if state == STATE_PATROL:
            do_patrol(distance_mm)
        
        # 3. Cập nhật servo
        update_obstacle_scan_fsm()
        update_patrol_sweep()
        
        # 4. Gửi trạng thái
        send_mqtt_status()
        
        vTaskDelay(50ms)


def do_patrol(distance_mm):
    # === Bước 0: Anti-Stuck Check ===
    if check_stuck_timer_expired():
        if is_robot_stuck():
            trigger_anti_stuck_escape()
            return
    
    # === Bước 1: Update Confidence ===
    if distance_mm > 0 and distance_mm < OBSTACLE_DIST_MM:  # 500mm
        obstacle_confidence += 1
        if obstacle_detect_us == 0:
            obstacle_detect_us = servo_pos_us
    else:
        obstacle_confidence = 0
        obstacle_detect_us = 0
    
    # === Bước 2: Scan Done? ===
    if scan_state == SCAN_DONE:
        # Thực hiện rẽ theo kết quả scan
        perform_pivot_turn(scan_turn_left, SPEED_TURN, distance_mm)
        scan_state = SCAN_IDLE
        obstacle_confidence = 0
        patrol_sweep_start()
        return
    
    # === Bước 3: Phân Loại & Xử Lý Vật Cản ===
    if obstacle_confidence >= 1 and scan_state == SCAN_IDLE and not patrol_turning:
        # Phân loại
        at_center = (1500-144 <= obstacle_detect_us <= 1500+144)
        is_large = (obstacle_confidence >= 2) or at_center
        
        if not is_large:
            # Vật nhỏ → Bypass
            handle_small_obstacle(distance_mm)
            return
        else:
            # Vật lớn → Scan
            patrol_sweep_stop()
            motor_stop()
            
            if distance_mm < HARD_STOP_DIST_MM:  # 350mm
                motor_backward(SPEED_PATROL - 20)
                vTaskDelay(300ms)
                motor_stop()
                vTaskDelay(70ms)
            
            start_obstacle_scan()
            return
    
    # === Bước 4: Đang Xoay? ===
    if patrol_turning:
        if now - patrol_turn_start > patrol_turn_duration:
            patrol_turning = False
        else:
            return
    
    # === Bước 5: Tiến Thẳng hoặc Lượn Nhẹ ===
    if distance_mm >= OBSTACLE_DIST_MM:  # 500mm
        
        if distance_mm <= SOFT_AVOID_DIST_MAX:  # 600mm
            # Soft Avoidance
            if servo_pos_us < 1500:
                # Vật phải → Lượn trái
                motor_set(90, 165)  # [55%, 100%]
            else:
                # Vật trái → Lượn phải
                motor_set(165, 90)  # [100%, 55%]
        else:
            # Đường thoáng
            motor_forward(SPEED_PATROL=165)
        
        patrol_sweep_start()
```

---

# XI. BỘ ĐỊA CHỈ PIN & CẤU HÌNH PHẦN CỨNG

```c
// ESP32-S3 Specific

// === HC-SR04 ===
#define PIN_HCSR04_TRIG 9
#define PIN_HCSR04_ECHO 10
#define HCSR04_ECHO_TIMEOUT_US 35000
#define HCSR04_MIN_DISTANCE_MM 20
#define HCSR04_MAX_DISTANCE_MM 4000

// === Servo Pan ===
#define PIN_SERVO_PAN 46
#define SERVO_ANGLE_CENTER 1500    // µs
#define SERVO_ANGLE_LEFT 2000
#define SERVO_ANGLE_RIGHT 1000
#define SERVO_LEDC_TIMER LEDC_TIMER_1
#define SERVO_LEDC_CHANNEL LEDC_CHANNEL_2

// === Motor (TB6612) ===
#define PIN_PWMA 4       // Left motor PWM
#define PIN_AIN1 6       // Left motor direction 1
#define PIN_AIN2 5       // Left motor direction 2

#define PIN_PWMB 17      // Right motor PWM
#define PIN_BIN1 15      // Right motor direction 1
#define PIN_BIN2 16      // Right motor direction 2

#define MOTOR_LEDC_TIMER LEDC_TIMER_0
#define MOTOR_LEDC_CH_A LEDC_CHANNEL_0
#define MOTOR_LEDC_CH_B LEDC_CHANNEL_1
#define PWM_FREQ 20000
#define PWM_RESOLUTION LEDC_TIMER_8_BIT  // 0-255
```

---

# XII. BẢNG THỜI GIAN & PERFORMANCE

| Sự kiện | Thời gian | Ghi chú |
|---------|-----------|--------|
| Main loop cycle | 50ms | FreeRTOS tick |
| HC-SR04 measurement | 5-35ms | Phụ thuộc khoảng cách |
| Servo smooth move | ~10-200ms | Tùy khoảng cách, speed_us_per_ms |
| Servo settle | 400ms | Chờ rung tắt |
| Sweep half period | 900ms | Đổi hướng quét |
| Scan full (L+R) | ~1400ms | 2×settle + moving |
| Small obstacle bypass | ~1050ms | Rẽ 600ms + forward 300ms |
| Pivot turn | 600-800ms | Rẽ tại chỗ |
| Anti-stuck escape | ~2000ms | Backward 1000ms + turn 700ms |
| PIR alert cooldown | 5000ms | Tránh spam |
| CHASE timeout | 3000ms | Quay lại PATROL |

---

# XIII. CÁC CÔNG THỨC TÓNG HỢP

## Công Thức Toán Học

$$\text{Distance} = \frac{\text{pulse\_duration\_µs} \times 343 \text{ (m/s)}}{2000}$$

$$\text{Soft\_Speed} = \frac{\text{SPEED\_PATROL} \times 55}{100} = \frac{165 \times 55}{100} = 90$$

$$\text{Servo\_Zone} = \text{SERVO\_CENTER} \pm \text{SWEEP\_CENTER\_ZONE} = 1500 \pm 144 = [1356, 1644] \text{ µs}$$

$$\text{Sweep\_Range} = \text{SERVO\_CENTER} \pm \text{SWEEP\_AMP} = 1500 \pm 278 = [1222, 1778] \text{ µs}$$

## Constants Định Nghĩa

| Hằng số | Giá trị | Ý nghĩa |
|--------|--------|--------|
| SOUND_SPEED | 343 m/s | Tốc độ âm thanh @ 20°C |
| DISTANCE_DIVISOR | 2000 | Chuyển µs → mm |
| SOFT_REDUCE | 55% | Giảm 55% bánh phía vật cản |
| PWM_RESOLUTION | 256 | 8-bit = 0-255 |
| RAMP_STEP | 40 | Soft-start increment |
| RAMP_DELAY | 15ms | Soft-start delay |

---

# XIV. TÓM TẮT HỆ THỐNG

```
┌──────────────────────────────────────────────────────────┐
│ THUẬT TOÁN NÉ VẬT CẢN — TỔNG HỢP                         │
├──────────────────────────────────────────────────────────┤
│                                                          │
│ ✓ Cảm biến: HC-SR04 ultrasonic                          │
│   ├─ Tính khoảng cách: (pulse_µs × 343) / 2000 mm     │
│   └─ Range: 20-4000mm, accuracy ±5mm                   │
│                                                          │
│ ✓ Vị trí servo: PWM 1000-2000µs (45° - 135°)           │
│   ├─ Center zone: ±13° phụ quyết định size            │
│   └─ Swing servo: ±25° khi tuần tra                     │
│                                                          │
│ ✓ Phân loại vật cản:                                    │
│   ├─ SMALL: 1 lần detect + ngoài center → bypass 1s   │
│   └─ LARGE: 2+ lần detect hoặc tại center → scan ±45°  │
│                                                          │
│ ✓ Lượn nhẹ (Soft Avoidance):                            │
│   ├─ 600-500mm: Giảm 55% bánh phía vật cản             │
│   └─ Differential steering                             │
│                                                          │
│ ✓ Anti-Stuck:                                           │
│   ├─ Phát hiện: distance_delta<30mm && angle_delta<60  │
│   └─ Escape: Lùi 1s + Rẽ 0.7s                          │
│                                                          │
│ ✓ Motor control: TB6612 L298N                           │
│   ├─ PWM 20kHz 8-bit (0-255)                           │
│   ├─ Soft-start ramp: +40/15ms                         │
│   └─ Speed: PATROL=165, CHASE=200, TURN=255           │
│                                                          │
│ ✓ Update frequency: 50ms (20Hz)                        │
│   └─ Đủ nhanh để phản ứng thời gian thực              │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

# XV. CÁC CÂUHỎI THƯỜNG GẶP VÀ TRỬA LỜI

### Q1: Tại sao phải chia 2000 trong công thức khoảng cách?

**A:** 
- Nếu pulse = 5882µs, âm thanh đi về mất 5882µs
- Quãng đường đi-về = 5882µs × 343m/s = 5882/1,000,000 × 343 m = 2.017m
- Quãng đường một chiều = 2.017m / 2 = 1.0085m = 1008.5mm
- Công thức: (pulse × 343) / 2,000,000 = pulse × 343 / 2000 (tính bằng mm)

### Q2: Tại sao sweep ±25° (278µs) chứ không phải ±45°?

**A:** 
- ±45° là cho full scan mỗi khi gặp vật lớn
- ±25° là sweep nhanh khi tuần tra, phủ vùng 50° phía trước
- 900ms mỗi nửa chu kỳ dớc để servo quay mượt mà + cảm biến ổn định

### Q3: Tại sao phân loại vật cản dựa trên confidence thay vì khoảng cách?

**A:** 
- Vật nhỏ (chân bàn) chỉ phát hiện 1-2 lần ở góc cạnh
- Vật lớn (tường) phát hiện liên tục tại center
- Dùng confidence + position server chính xác hơn dùng khoảng cách

### Q4: Tại sao chỉ giảm bánh này 55% (90 speed) thay vì dừng hoàn toàn?

**A:** 
- Giảm 55% = robot lượn nhẹ từ từ, mượt mà
- Dừng hoàn toàn = robot có thể kẹt vô, cần xử lý anti-stuck
- 55% tốc độ đủ để robot tránh ngang an toàn

### Q5: Servo scan ±45° mất bao lâu? Có thể tối ưu không?

**A:** 
- Thời gian: ~1400ms (L-settle-R-settle-return)
- Tối ưu: Reduce settle time từ 400ms xuống 200ms → ~900ms
- Trade-off: Giảm settle time → cảm biến chưa ổn định → đo không chính xác

---

**HẾT**

Tài liệu này cung cấp đủ chi tiết để bạn trả lời mọi câu hỏi từ thầy về:
- ✅ Công thức & toán học
- ✅ State machine & logic
- ✅ Phân loại vật cản
- ✅ Soft avoidance
- ✅ Anti-stuck mechanism
- ✅ Motor control
- ✅ Timing & performance
