/**
 * ============================================================
 *  ROBOT CONFIG — Cấu hình ESP32 Motor Controller
 * ============================================================
 *  WiFi + Server IP → sửa tại D:\ROBOT\shared_config.h
 *  Phần cứng + Motion → sửa tại đây
 * ============================================================
 */

#ifndef ROBOT_CONFIG_H
#define ROBOT_CONFIG_H

/* ---- Import WiFi + MQTT broker URI từ file chung ---- */
#include "../../shared_config.h"

/* ---- MQTT Topics ---- */
#define MQTT_TOPIC "robot/position"
#define MQTT_COMMAND_TOPIC "robot/command"
#define MQTT_ALERT_TOPIC "robot/alert"
#define MQTT_USERNAME "robot"
#define MQTT_PASSWORD "robot123"

#define DIST_SENSOR_BACKEND_VL53L0X 1
#define DIST_SENSOR_BACKEND_HCSR04 2

#define DIST_SENSOR_BACKEND DIST_SENSOR_BACKEND_HCSR04

/*
 * Pin map by target:
 * - ESP32-S3: avoid common flash/PSRAM/strap/USB pins.
 * - ESP32: keep previous wiring.
 */
#if CONFIG_IDF_TARGET_ESP32S3
/* ---- Motor A (Trái) — L298N ---- */
#define PIN_PWMA 4
#define PIN_AIN2 5
#define PIN_AIN1 6

/* ---- L298N Standby (Not used) ---- */
// #define PIN_STBY 7

/* ---- Motor B (Phải) — L298N ---- */
#define PIN_BIN1 15
#define PIN_BIN2 16
#define PIN_PWMB 17

/* ---- VL53L0X (I2C) ---- */
#define PIN_SDA 8
#define PIN_SCL 18
#define VL53L0X_ADDR 0x29

/* ---- HC-SR04 (adjust to match wiring when used) ---- */
#define PIN_HCSR04_TRIG 9
#define PIN_HCSR04_ECHO 10

/* ---- PIR Sensor ---- */
#define PIN_PIR 3

/* ---- Servo Pan (Camera servo) ---- */
#define PIN_SERVO_PAN 46
#else
/* ---- Motor A (Trái) — L298N ---- */
#define PIN_PWMA 25
#define PIN_AIN1 26
#define PIN_AIN2 27

/* ---- Motor B (Phải) — L298N ---- */
#define PIN_PWMB 14
#define PIN_BIN1 12
#define PIN_BIN2 13

/* ---- L298N Standby (Not used) ---- */
// #define PIN_STBY 33

/* ---- VL53L0X (I2C) ---- */
#define PIN_SDA 21
#define PIN_SCL 22
#define VL53L0X_ADDR 0x29

/* ---- HC-SR04 (adjust to match wiring when used) ---- */
#define PIN_HCSR04_TRIG 18
#define PIN_HCSR04_ECHO 19

/* ---- PIR Sensor ---- */
#define PIN_PIR 32

/* ---- Servo Pan (Camera servo) ---- */
#define PIN_SERVO_PAN 46
#endif

#define HCSR04_ECHO_TIMEOUT_US 35000
#define HCSR04_MIN_DISTANCE_MM 20
#define HCSR04_MAX_DISTANCE_MM 4000

/* ---- PWM Settings (Motors) ---- */
#define MOTOR_LEDC_SPEED_MODE LEDC_LOW_SPEED_MODE
#define MOTOR_LEDC_TIMER LEDC_TIMER_0
#define MOTOR_LEDC_CH_A LEDC_CHANNEL_0
#define MOTOR_LEDC_CH_B LEDC_CHANNEL_1
#define PWM_RESOLUTION LEDC_TIMER_8_BIT /* 0-255 */
#define PWM_FREQ 20000

/* ---- PWM Settings (Servo) ---- */
#define SERVO_LEDC_SPEED_MODE LEDC_LOW_SPEED_MODE
#define SERVO_LEDC_TIMER LEDC_TIMER_1
#define SERVO_LEDC_CHANNEL LEDC_CHANNEL_2

/* ---- Servo Parameters ---- */
#define SERVO_ANGLE_CENTER 1500   /* us — 90 độ (center/neutral) */
#define SERVO_ANGLE_LEFT 2000     /* us — phía trái (~135 độ) */
#define SERVO_ANGLE_RIGHT 1000    /* us — phía phải (~45 độ) */
#define SERVO_SPEED_MAX 10        /* độ/ms — tốc độ quay max tự nhiên */
#define SERVO_STABLE_FRAMES 3     /* frames ổn định trước khi robot xoay */
#define SERVO_RETURN_SPEED_MS 800 /* ms — thời gian trả servo về center */

/* ---- Obstacle Scan Parameters (servo quét trái/phải để đo khoảng trống) ---- */
#define SCAN_ANGLE_LEFT 1750  /* us — quét trái ~45° từ center (1500us) */
#define SCAN_ANGLE_RIGHT 1250 /* us — quét phải ~45° từ center (1500us) */
#define SCAN_SETTLE_MS 400    /* ms — chờ servo/sensor ổn định sau khi xoay */
#define SCAN_MIN_CLEAR_MM 450 /* mm — ngưỡng coi là "thông thoáng" (< này = blocked) */

/* ---- Patrol Sweep (servo dao động khi tuần tra để phát hiện vật cản hẹp) ---- */
#define SWEEP_AMP_US 278         /* ±278us = ±25° từ center — phủ vùng 50° phía trước */
#define SWEEP_HALF_PERIOD_MS 900 /* ms — đổi chiều mỗi 900ms, chu kỳ 1.8s */
#define SWEEP_SPEED_UMS 2.5f     /* us/ms — chậm/nuột để sensor ổn định */
#define SWEEP_CENTER_ZONE_US 144 /* ±13° (144us) — phát hiện trong zone này = vật cản LỚN */

/* ---- Motion Parameters ---- */
#define SPEED_PATROL 165 /* Tốc độ tuần tra (0-255) */
#define SPEED_CHASE 180  /* Tốc độ đuổi theo (0-255) */
#define SPEED_TURN 150   /* Tốc độ rẽ tại chỗ (0-255) */

#define TURN_LEFT_BOOST 10  /* Bù lực xoay trái do lệch cơ khí */
#define TURN_RIGHT_BOOST 14 /* Bù lực xoay phải do lệch cơ khí */
#define TURN_MIN_SPEED 170  /* Sàn tốc độ xoay */
#define TURN_MAX_SPEED 200  /* Trần tốc độ xoay */
#define TURN_BRAKE_MS 45    /* Dừng quán tính trước khi xoay */

#define SOFT_AVOID_DIST_MAX 600 /* Bắt đầu lượn né nhẹ (mm) */
#define OBSTACLE_DIST_MM 500    /* Khoảng cách vật cản (mm) -> phanh và xoay vòng khẩn cấp */
#define HARD_STOP_DIST_MM 350   /* Quá gần vật cản -> dừng khẩn */
#define STOP_DIST_MM 550        /* Khoảng cách giảm tốc khi đuổi người (mm) */
#define PAN_DEADZONE 10.0f      /* Góc pan nhỏ hơn giá trị này → chạy thẳng */
#define OBSTACLE_STOP_MS 220    /* Gặp vật cản -> dừng bắt buộc trước khi xử lý */

/* ---- Stuck Escape Parameters ---- */
#define STUCK_CYCLES_THRESHOLD 4 /* 4 vòng quét giữ nguyên thông số phạt kẹt */
#define STUCK_DIST_MARGIN 30     /* Chênh lệch 30mm coi như cùng 1 vật cố định */

#define CHASE_TIMEOUT_MS 3000 /* Mất tín hiệu người > 3s → về PATROL */
#define PATROL_TURN_MS 1000   /* Thời gian rẽ mặc định khi gặp vật cản (ms) */

/* ---- Monitor Mode (default) ---- */
#define PIR_COOLDOWN_MS 5000    /* Gửi alert PIR tối đa mỗi 5s */
#define DIST_ALERT_MM 1000      /* Cảnh báo khi có vật thể <1m */
#define DIST_COOLDOWN_MS 5000   /* Gửi alert distance tối đa mỗi 5s */
#define ALERT_INTERVAL_MS 45000 /* Gửi sensor report mỗi 45s (lệch 30s keepalive) */

#endif /* ROBOT_CONFIG_H */
