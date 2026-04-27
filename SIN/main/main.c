/**
 * ESP32 Robot Controller — Main Application
 * -------------------------------------------
 * State Machine:
 *   PATROL  → Robot tuần tra, tránh vật cản
 *   CHASE   → Nhận vị trí người từ MQTT, chạy tới đó
 *   MANUAL  → Điều khiển từ web dashboard
 *
 * Flow:
 *   1. Init: Motor, Sensors, WiFi, MQTT
 *   2. Main loop (50ms cycle):
 *      - Read web command (highest priority)
 *      - Read sensors (distance, PIR)
 *      - Read MQTT data (person position)
 *      - Switch state: PATROL ↔ CHASE ↔ MANUAL
 *      - Execute motor commands
 */

#include "config.h"
#include "motor.h"
#include "sensor.h"
#include "mqtt_client_app.h"
#include "servo.h"

#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

/* Fix brownout reset */
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

static const char *TAG = "robot";

/* ========================== State Machine ========================== */

typedef enum
{
    STATE_MONITOR, /* Default: stay still, detect & alert */
    STATE_PATROL,
    STATE_CHASE,
    STATE_MANUAL,
} robot_state_t;

static robot_state_t state = STATE_MONITOR;
static bool patrol_turning = false;
static int64_t patrol_turn_start = 0;
static int patrol_turn_duration_ms = PATROL_TURN_MS;
static bool patrol_turn_left = false;
static int64_t manual_last_cmd = 0;
static bool motor_is_stopped = true; /* Cache trạng thái motor — tránh gọi PWM thừa */

/* Servo tracking state machine */
typedef enum
{
    SERVO_IDLE,             /* Không do gì */
    SERVO_MOVING_TO_TARGET, /* Servo đang xoay tới vị trí trái/phải */
    SERVO_WAITING_STABLE,   /* Servo ổn định, chờ trước khi robot xoay */
    SERVO_ROBOT_ROTATING,   /* Robot xoay, servo stby */
    SERVO_RETURNING,        /* Servo quay về center */
} servo_state_t;

static servo_state_t servo_state = SERVO_IDLE;
static int servo_stable_frames = 0;
static int64_t servo_phase_start = 0;
static bool servo_turn_left = false; /* Lệnh: trái hay phải */
static uint16_t servo_target_angle = SERVO_ANGLE_CENTER;

/* Obstacle scan state machine — servo quét trái/phải để chọn hướng tránh vật cản */
typedef enum
{
    SCAN_IDLE,
    SCAN_MOVING_LEFT,  /* Servo đang xoay sang trái  */
    SCAN_SETTLE_LEFT,  /* Chờ servo ổn định bên trái  */
    SCAN_MOVING_RIGHT, /* Servo đang xoay sang phải  */
    SCAN_SETTLE_RIGHT, /* Chờ servo ổn định bên phải */
    SCAN_RETURNING,    /* Servo về center             */
    SCAN_DONE,         /* Xong, kết quả sẵn sàng     */
} obstacle_scan_state_t;

static obstacle_scan_state_t scan_state = SCAN_IDLE;
static int64_t scan_phase_start = 0;
// static int64_t camera_last_online_ms = 0;  /* unused — kept for reference */
static uint16_t scan_dist_left = 0;  /* mm đo được bên trái */
static uint16_t scan_dist_right = 0; /* mm đo được bên phải */
static bool scan_turn_left = false;  /* Hướng robot nên rẽ (kết quả scan) */

/* ==== Patrol Sweep state ==== */
static bool sweep_active = false;  /* Sweep đang chạy? */
static bool sweep_dir_left = true; /* Hướng quét: true=trái, false=phải */
static int64_t sweep_last_ms = 0;  /* Lần cuối đổi chiều (ms) */

/* ==== Obstacle Confidence Classifier ==== */
static uint8_t obstacle_confidence = 0; /* Số lần liên tiếp dist < OBSTACLE_DIST_MM */
static uint16_t obstacle_detect_us = 0; /* Góc servo lúc phát hiện lần đầu (0=chưa set) */

/* Alert cooldowns for MONITOR mode */
static int64_t last_pir_alert = 0;
static int64_t last_dist_alert = 0;
static int64_t last_status_report = 0;

#define MANUAL_TIMEOUT_MS 2000
#define CAMERA_ALERT_COOLDOWN_MS 10000 /* Camera alert tối đa mỗi 10s */
/*
 * Không có camera_offline fallback về MONITOR nữa.
 * PATROL hoàn toàn tự lái, không cần camera.
 * CHASE sẽ tự chuyển về PATROL khi person_active=false (bao gồm cả luc camera offline).
 */

static int64_t now_ms(void)
{
    return esp_timer_get_time() / 1000;
}

static const char *state_name(robot_state_t s)
{
    switch (s)
    {
    case STATE_MONITOR:
        return "MONITOR";
    case STATE_PATROL:
        return "PATROL";
    case STATE_CHASE:
        return "CHASE";
    case STATE_MANUAL:
        return "MANUAL";
    default:
        return "UNKNOWN";
    }
}

static const char *distance_status_name(sensor_distance_status_t status)
{
    switch (status)
    {
    case SENSOR_DISTANCE_STATUS_OK:
        return "OK";
    case SENSOR_DISTANCE_STATUS_NO_TARGET:
        return "NO_TARGET";
    case SENSOR_DISTANCE_STATUS_TIMEOUT:
        return "TIMEOUT";
    case SENSOR_DISTANCE_STATUS_ERROR:
        return "ERROR";
    case SENSOR_DISTANCE_STATUS_NOT_READY:
        return "NOT_READY";
    case SENSOR_DISTANCE_STATUS_NOT_SAMPLED:
    default:
        return "NOT_SAMPLED";
    }
}

static void set_state(robot_state_t new_state, const char *reason,
                      uint16_t distance_mm, bool pir)
{
    if (state == new_state)
        return;
    state = new_state;
    mqtt_publish_status(state_name(state), reason, distance_mm, pir);
}

static int build_turn_speed(bool turn_left, int base_speed, float abs_pan, uint16_t distance_mm)
{
    int speed = base_speed;

    if (abs_pan > 20.0f)
        speed += 10;
    if (abs_pan > 35.0f)
        speed += 10;
    if (distance_mm > 0 && distance_mm < HARD_STOP_DIST_MM)
        speed += 15;
    speed += turn_left ? TURN_LEFT_BOOST : TURN_RIGHT_BOOST;

    if (speed < TURN_MIN_SPEED)
        speed = TURN_MIN_SPEED;
    if (speed > TURN_MAX_SPEED)
        speed = TURN_MAX_SPEED;
    return speed;
}

/* ========================== MONITOR ========================== */

static void do_monitor(uint16_t distance_mm, bool pir, bool person_active)
{
    /* Chỉ gọi motor_stop() 1 lần khi vào MONITOR, không gọi mỗi 50ms */
    if (!motor_is_stopped)
    {
        motor_stop();
        motor_is_stopped = true;
    }

    int64_t now = now_ms();

    /* PIR triggered → alert */
    if (pir && (now - last_pir_alert > PIR_COOLDOWN_MS))
    {
        last_pir_alert = now;
        ESP_LOGI(TAG, "MONITOR: PIR motion detected!");
        mqtt_publish_alert("pir", "Phát hiện chuyển động (PIR)", distance_mm, pir);
    }

    /* Object too close → alert */
    if (distance_mm > 0 && distance_mm < DIST_ALERT_MM &&
        (now - last_dist_alert > DIST_COOLDOWN_MS))
    {
        last_dist_alert = now;
        ESP_LOGI(TAG, "MONITOR: Object at %d mm!", distance_mm);
        char detail[64];
        snprintf(detail, sizeof(detail), "Vật thể cách %d mm", distance_mm);
        mqtt_publish_alert("distance", detail, distance_mm, pir);
    }

    /* Camera alert đã xóa — server tự biết có người rồi, không cần ESP32 gửi lại */

    /* Periodic status report */
    if (now - last_status_report > ALERT_INTERVAL_MS)
    {
        last_status_report = now;
        mqtt_publish_status("MONITOR", "Đang giám sát", distance_mm, pir);
    }
}

/* ========================== PATROL ========================== */

static int patrol_consecutive_turns = 0;

static void perform_pivot_turn(bool turn_left, int base_speed, uint16_t distance_mm)
{
    int turn_speed = build_turn_speed(turn_left, base_speed, 0.0f, distance_mm);

    /* Cắt quán tính trước khi quay để robot xoay "gắt" hơn */
    motor_stop();
    vTaskDelay(pdMS_TO_TICKS(TURN_BRAKE_MS));

    if (turn_left)
    {
        motor_turn_left(turn_speed);
    }
    else
    {
        motor_turn_right(turn_speed);
    }
}

/* ========================== OBSTACLE SCAN ========================== */

/**
 * Khởi động quét vật cản:
 *   Servo xoay trái 45° → đo → xoay phải 45° → đo → về center → quyết định hướng.
 */
static void start_obstacle_scan(void)
{
    if (scan_state != SCAN_IDLE)
        return; /* Đang scan rồi, bỏ qua */
    if (servo_state != SERVO_IDLE)
        return; /* Servo đang dùng cho web cmd, bỏ qua */

    scan_dist_left = 0;
    scan_dist_right = 0;
    scan_phase_start = now_ms();
    scan_state = SCAN_MOVING_LEFT;
    patrol_turning = false; /* Ensure we are not in a 'turning' state while scanning */
    servo_move_smooth(SCAN_ANGLE_LEFT, 10.0f);
    ESP_LOGI(TAG, "[SCAN] Start — servo moving LEFT 45°");
    /* Thông báo server robot đang scan (không phải mất kết nối) */
    mqtt_publish_status("PATROL", "Obstacle scan in progress", 0, false);
}

/**
 * Cập nhật state machine quét vật cản — gọi mỗi vòng lặp chính.
 * Read the active distance backend when the servo is stable, then return
 * the servo to center and keep the scan result.
 */
static void obstacle_scan_update(void)
{
    if (scan_state == SCAN_IDLE || scan_state == SCAN_DONE)
        return;

    int64_t now = now_ms();

    switch (scan_state)
    {

    case SCAN_MOVING_LEFT:
        /* Chờ servo tới vị trí trái */
        if (!servo_is_moving())
        {
            scan_state = SCAN_SETTLE_LEFT;
            scan_phase_start = now;
            ESP_LOGI(TAG, "[SCAN] At LEFT — settling %d ms", SCAN_SETTLE_MS);
        }
        break;

    case SCAN_SETTLE_LEFT:
        /* Chờ rung tắt rồi đo */
        if (now - scan_phase_start >= SCAN_SETTLE_MS)
        {
            scan_dist_left = sensor_get_distance_mm();
            ESP_LOGI(TAG, "[SCAN] dist_left = %d mm", scan_dist_left);
            scan_state = SCAN_MOVING_RIGHT;
            scan_phase_start = now;
            servo_move_smooth(SCAN_ANGLE_RIGHT, 10.0f);
        }
        break;

    case SCAN_MOVING_RIGHT:
        /* Chờ servo tới vị trí phải */
        if (!servo_is_moving())
        {
            scan_state = SCAN_SETTLE_RIGHT;
            scan_phase_start = now;
            ESP_LOGI(TAG, "[SCAN] At RIGHT — settling %d ms", SCAN_SETTLE_MS);
        }
        break;

    case SCAN_SETTLE_RIGHT:
        /* Chờ rung tắt rồi đo */
        if (now - scan_phase_start >= SCAN_SETTLE_MS)
        {
            scan_dist_right = sensor_get_distance_mm();
            ESP_LOGI(TAG, "[SCAN] dist_right = %d mm", scan_dist_right);
            /* Trả servo về center */
            scan_state = SCAN_RETURNING;
            scan_phase_start = now;
            servo_move_smooth(SERVO_ANGLE_CENTER, 10.0f);
        }
        break;

    case SCAN_RETURNING:
        /* Chờ servo về center xong (+ timeout 1500ms phòng servo_is_moving() kẹt) */
        if (!servo_is_moving() || (now - scan_phase_start >= 1500))
        {
            if (scan_dist_left == 0 && scan_dist_right == 0)
            {
                scan_turn_left = true;
            }
            else if (scan_dist_left == 0)
            {
                scan_turn_left = false;
            }
            else if (scan_dist_right == 0)
            {
                scan_turn_left = true;
            }
            else
            {
                scan_turn_left = (scan_dist_left >= scan_dist_right);
            }
            ESP_LOGI(TAG, "[SCAN] Done! left=%dmm right=%dmm → turn %s",
                     scan_dist_left, scan_dist_right,
                     scan_turn_left ? "LEFT" : "RIGHT");
            scan_state = SCAN_DONE;
        }
        break;

    default:
        break;
    }
}

/* ========================== PATROL SWEEP ========================== */

static void patrol_sweep_start(void)
{
    if (sweep_active)
        return;
    sweep_active = true;
    sweep_dir_left = true;
    sweep_last_ms = now_ms();
    ESP_LOGD(TAG, "[SWEEP] Started");
}

static void patrol_sweep_stop(void)
{
    if (!sweep_active)
        return;
    sweep_active = false;
    servo_move_smooth(SERVO_ANGLE_CENTER, SWEEP_SPEED_UMS);
    ESP_LOGD(TAG, "[SWEEP] Stopped — servo returning to center");
}

static void patrol_sweep_update(void)
{
    if (!sweep_active)
        return; /* Sweep not active */
    if (servo_state != SERVO_IDLE)
        return; /* Web command đang dùng servo */
    if (scan_state != SCAN_IDLE)
        return; /* Obstacle scan đang dùng servo */

    int64_t now = now_ms();
    if (now - sweep_last_ms < SWEEP_HALF_PERIOD_MS)
        return;

    sweep_last_ms = now;
    sweep_dir_left = !sweep_dir_left;
    uint16_t target = sweep_dir_left
                          ? (uint16_t)(SERVO_ANGLE_CENTER + SWEEP_AMP_US)  /* +25° trái */
                          : (uint16_t)(SERVO_ANGLE_CENTER - SWEEP_AMP_US); /* -25° phải */
    servo_move_smooth(target, SWEEP_SPEED_UMS);
    ESP_LOGD(TAG, "[SWEEP] → %s (%d us)", sweep_dir_left ? "LEFT" : "RIGHT", target);
}

static uint16_t last_stuck_dist = 0;
static uint16_t last_stuck_angle = 0;
static uint8_t stuck_count = 0;
static int64_t last_stuck_check = 0;

/**
 * Xử lý vật cản nhỏ (chân bàn, chân ghế): bypass nhanh ~1.05s.
 */
static void handle_small_obstacle(uint16_t distance_mm)
{
    patrol_sweep_stop();
    bool bypass_left = (obstacle_detect_us < SERVO_ANGLE_CENTER);
    ESP_LOGI(TAG, "[OBSTACLE] SMALL @ servo=%d us (độ lệch=%d us) — bypass %s",
             obstacle_detect_us,
             (int)obstacle_detect_us - SERVO_ANGLE_CENTER,
             bypass_left ? "LEFT" : "RIGHT");

    motor_stop();
    vTaskDelay(pdMS_TO_TICKS(150));

    /* Rẽ về phía OPPOSITE với góc phát hiện */
    perform_pivot_turn(bypass_left, SPEED_TURN, distance_mm);
    vTaskDelay(pdMS_TO_TICKS(600));

    /* Tiến thẳng ngắn để vượt qua chân bàn */
    motor_forward(SPEED_PATROL);
    vTaskDelay(pdMS_TO_TICKS(300));

    obstacle_confidence = 0;
    obstacle_detect_us = 0;
    patrol_sweep_start();
}

static void do_patrol(uint16_t distance_mm)
{
    /* Nếu scan đang chạy (không phải IDLE/DONE) → robot đã dừng, chờ xong */
    if (scan_state != SCAN_IDLE && scan_state != SCAN_DONE)
        return;

    /* ---- Bước 0: Kiểm tra kẹt (Anti-Stuck Tracker) ---- */
    if (now_ms() - last_stuck_check >= (SWEEP_HALF_PERIOD_MS * 2))
    {
        last_stuck_check = now_ms();
        if (distance_mm > 0 && distance_mm < 1500 && !patrol_turning && scan_state == SCAN_IDLE)
        {
            uint16_t current_angle = servo_get_current_pos();
            int d_diff = (int)distance_mm - (int)last_stuck_dist;
            if (d_diff < 0)
                d_diff = -d_diff;
            int a_diff = (int)current_angle - (int)last_stuck_angle;
            if (a_diff < 0)
                a_diff = -a_diff;

            if (d_diff < STUCK_DIST_MARGIN && a_diff < 60)
            {
                stuck_count++;
            }
            else
            {
                stuck_count = 0;
                last_stuck_dist = distance_mm;
                last_stuck_angle = current_angle;
            }
        }
        else
        {
            stuck_count = 0;
        }

        if (stuck_count >= STUCK_CYCLES_THRESHOLD)
        {
            ESP_LOGW(TAG, "PATROL: Anti-Stuck triggered! Escaping.");
            stuck_count = 0;
            patrol_sweep_stop();
            motor_stop();
            vTaskDelay(pdMS_TO_TICKS(100));
            motor_backward(SPEED_PATROL);
            vTaskDelay(pdMS_TO_TICKS(1000));
            motor_stop();
            vTaskDelay(pdMS_TO_TICKS(100));
            perform_pivot_turn(true, SPEED_TURN, 0); /* rẽ trái để thoát ra */
            vTaskDelay(pdMS_TO_TICKS(700));
            patrol_sweep_start();
            return;
        }
    }

    /* ---- Bước 1: Cập nhật Confidence Counter ---- */
    if (distance_mm > 0 && distance_mm < OBSTACLE_DIST_MM)
    {
        obstacle_confidence++;
        if (obstacle_detect_us == 0)
        {
            obstacle_detect_us = (uint16_t)servo_get_current_pos();
        }
    }
    else
    {
        obstacle_confidence = 0;
        obstacle_detect_us = 0;
    }

    /* ---- Bước 2: Scan xong → thực hiện rẽ ---- */
    if (scan_state == SCAN_DONE)
    {
        ESP_LOGI(TAG, "[SCAN] Executing turn: %s", scan_turn_left ? "LEFT" : "RIGHT");
        scan_state = SCAN_IDLE;
        patrol_consecutive_turns++;
        patrol_turning = true;
        patrol_turn_start = now_ms();
        patrol_turn_duration_ms = PATROL_TURN_MS;

        if (scan_dist_left < SCAN_MIN_CLEAR_MM && scan_dist_right < SCAN_MIN_CLEAR_MM)
        {
            ESP_LOGW(TAG, "[SCAN] Both sides blocked! Extra reverse");
            motor_backward(SPEED_PATROL - 20);
            vTaskDelay(pdMS_TO_TICKS(400));
            motor_stop();
            vTaskDelay(pdMS_TO_TICKS(70));
            patrol_turn_duration_ms += 300;
        }

        if (patrol_consecutive_turns >= 4)
        {
            patrol_turn_left = !scan_turn_left;
            patrol_consecutive_turns = 1;
            patrol_turn_duration_ms += 200;
        }
        else
        {
            patrol_turn_left = scan_turn_left;
        }

        perform_pivot_turn(patrol_turn_left, SPEED_TURN, distance_mm);
        motor_is_stopped = false;
        obstacle_confidence = 0;
        obstacle_detect_us = 0;
        patrol_sweep_start();
        return;
    }

    /* ---- Bước 3: Vật cản hiện diện → phân loại & xử lý ---- */
    if (obstacle_confidence >= 1 && scan_state == SCAN_IDLE && !patrol_turning)
    {
        /*
         * Phân loại vật cản:
         *   LỚN: confidence ≥ 2 (bền vững), hoặc phát hiện tại zone center ±13°
         *   NHỎ: chỉ 1 lần đọc ở góc lệch (nghi là chân bàn/ghế hẹp)
         */
        bool at_center = (obstacle_detect_us == 0) ||
                         (obstacle_detect_us >= SERVO_ANGLE_CENTER - SWEEP_CENTER_ZONE_US &&
                          obstacle_detect_us <= SERVO_ANGLE_CENTER + SWEEP_CENTER_ZONE_US);
        bool is_large = (obstacle_confidence >= 2) || at_center;

        if (!is_large)
        {
            /* Vật nhỏ nghi ngờ → bypass nhanh ~1s */
            handle_small_obstacle(distance_mm);
            return;
        }

        /* Vật lớn chắc chắn → full scan ±45° */
        ESP_LOGI(TAG, "PATROL: [LARGE] Obstacle %dmm conf=%d us=%d → full scan",
                 distance_mm, obstacle_confidence, obstacle_detect_us);
        patrol_sweep_stop();
        motor_stop();
        motor_is_stopped = true;
        vTaskDelay(pdMS_TO_TICKS(OBSTACLE_STOP_MS));

        if (distance_mm < HARD_STOP_DIST_MM)
        {
            ESP_LOGW(TAG, "PATROL: Too close (%dmm) — reversing", distance_mm);
            motor_backward(SPEED_PATROL - 20);
            vTaskDelay(pdMS_TO_TICKS(300));
            motor_stop();
            vTaskDelay(pdMS_TO_TICKS(70));
        }

        start_obstacle_scan();
        return;
    }

    /* ---- Bước 4: Đang xoay → kiểm tra thời gian ---- */
    if (patrol_turning)
    {
        if (now_ms() - patrol_turn_start > patrol_turn_duration_ms)
        {
            patrol_turning = false;
        }
        else
        {
            return;
        }
    }

    /* ---- Bước 5: Tiến thẳng hoặc Đánh lái lượn (Soft Avoidance) ---- */
    patrol_consecutive_turns = 0;
    patrol_turn_duration_ms = PATROL_TURN_MS;

    if (distance_mm >= OBSTACLE_DIST_MM && distance_mm <= SOFT_AVOID_DIST_MAX)
    {
        uint16_t servo_pos = servo_get_current_pos();
        bool turn_left = (servo_pos < SERVO_ANGLE_CENTER); // Vật cản nằm bên phải -> Lượn trái

        /* Bánh bên phía vật cản giữ 100%, bánh còn lại giảm 45% (còn 55%) */
        int slow_speed = (SPEED_PATROL * 55) / 100;
        if (turn_left)
        {
            motor_set(slow_speed, SPEED_PATROL); // Lượn trái
        }
        else
        {
            motor_set(SPEED_PATROL, slow_speed); // Lượn phải
        }
        motor_is_stopped = false;
    }
    else
    {
        /* Đường thoáng hoàn toàn */
        motor_forward(SPEED_PATROL);
        motor_is_stopped = false;
    }
    patrol_sweep_start();
}

/* ========================== CHASE ========================== */

static void do_chase(person_data_t *person, uint16_t distance_mm)
{
    if (distance_mm > 0 && distance_mm < HARD_STOP_DIST_MM)
    {
        motor_stop();
        motor_is_stopped = true;
        return;
    }

    if (distance_mm > 0 && distance_mm < OBSTACLE_DIST_MM)
    {
        /* Trong CHASE cũng ưu tiên dừng khi gặp vật cản để tránh va chạm */
        motor_stop();
        motor_is_stopped = true;
        return;
    }

    if (distance_mm > 0 && distance_mm < STOP_DIST_MM)
    {
        /* Gần vật cản nhưng chưa quá sát: giảm tốc để áp sát mượt hơn */
        motor_forward(SPEED_PATROL);
        motor_is_stopped = false;
        return;
    }

    float pan = person->pan;
    float abs_pan = (pan >= 0.0f) ? pan : -pan;

    if (pan > PAN_DEADZONE)
    {
        int turn_speed = build_turn_speed(false, SPEED_TURN, abs_pan, distance_mm);
        motor_turn_right(turn_speed);
        motor_is_stopped = false;
    }
    else if (pan < -PAN_DEADZONE)
    {
        int turn_speed = build_turn_speed(true, SPEED_TURN, abs_pan, distance_mm);
        motor_turn_left(turn_speed);
        motor_is_stopped = false;
    }
    else
    {
        motor_forward(SPEED_CHASE);
        motor_is_stopped = false;
    }
}

/* ========================== MANUAL ========================== */

static void do_manual(robot_command_t *cmd)
{
    switch (cmd->action)
    {
    case CMD_FORWARD:
        motor_forward(SPEED_CHASE);
        break;
    case CMD_BACKWARD:
        motor_backward(SPEED_CHASE);
        break;
    case CMD_LEFT:
        perform_pivot_turn(true, SPEED_TURN + 20, 0);
        break;
    case CMD_RIGHT:
        perform_pivot_turn(false, SPEED_TURN + 20, 0);
        break;
    case CMD_STOP:
        motor_stop();
        motor_is_stopped = true;
        break;
    default:
        break;
    }
    if (cmd->action != CMD_STOP)
        motor_is_stopped = false;
}

/* ========================== SERVO CONTROL ========================== */

static void servo_tracking_update(void)
{
    int64_t now = now_ms();

    switch (servo_state)
    {
    case SERVO_IDLE:
        /* Chờ lệnh từ server */
        break;

    case SERVO_MOVING_TO_TARGET:
        /* Servo đang xoay tới vị trí target (trái/phải) */
        if (!servo_is_moving())
        {
            /* Servo đã tới target → chuyển sang chờ ổn định */
            servo_state = SERVO_WAITING_STABLE;
            servo_stable_frames = 0;
            servo_phase_start = now;
            ESP_LOGI(TAG, "[SERVO] Reached target, waiting %d frames to stabilize",
                     SERVO_STABLE_FRAMES);
        }
        break;

    case SERVO_WAITING_STABLE:
        /* Sau mỗi 50ms cycle (1 frame), tăng counter */
        servo_stable_frames++;
        if (servo_stable_frames >= SERVO_STABLE_FRAMES)
        {
            /* Ổn định đủ rồi → bắt robot xoay */
            servo_state = SERVO_ROBOT_ROTATING;
            servo_phase_start = now;

            if (servo_turn_left)
            {
                ESP_LOGI(TAG, "[SERVO] Starting robot LEFT rotation");
                perform_pivot_turn(true, SPEED_TURN, 0);
            }
            else
            {
                ESP_LOGI(TAG, "[SERVO] Starting robot RIGHT rotation");
                perform_pivot_turn(false, SPEED_TURN, 0);
            }
        }
        break;

    case SERVO_ROBOT_ROTATING:
        /* Robot đang xoay, chờ nó xoay xong (khoảng 1 giây) */
        if (now - servo_phase_start > PATROL_TURN_MS)
        {
            /* Robot xoay xong → servo trả về center */
            servo_state = SERVO_RETURNING;
            servo_phase_start = now;
            servo_move_smooth(SERVO_ANGLE_CENTER, 10.0f);
            ESP_LOGI(TAG, "[SERVO] Robot done, servo returning to center");
        }
        break;

    case SERVO_RETURNING:
        /* Servo trả về center (có 2000ms safety timeout) */
        if (!servo_is_moving() || (now - servo_phase_start > 2000))
        {
            /* Xong! Quay về IDLE */
            servo_state = SERVO_IDLE;
            servo_stable_frames = 0;
            ESP_LOGI(TAG, "[SERVO] Complete sequence finished");
            mqtt_publish_alert("servo", "Servo tracking complete", 0, false);
        }
        break;
    }
}

static void start_servo_tracking(bool turn_left)
{
    /* Kiểm tra nếu servo đã busy (web tracking hoặc obstacle scan) */
    if (servo_state != SERVO_IDLE)
    {
        ESP_LOGW(TAG, "[SERVO] Already tracking, ignoring new command");
        return;
    }
    if (scan_state != SCAN_IDLE)
    {
        ESP_LOGW(TAG, "[SERVO] Obstacle scan in progress, ignoring web servo command");
        return;
    }

    servo_turn_left = turn_left;
    servo_target_angle = turn_left ? SERVO_ANGLE_LEFT : SERVO_ANGLE_RIGHT;
    servo_state = SERVO_MOVING_TO_TARGET;
    servo_phase_start = now_ms();
    servo_stable_frames = 0;

    ESP_LOGI(TAG, "[SERVO] Starting sequence: %s", turn_left ? "LEFT" : "RIGHT");
    servo_move_smooth(servo_target_angle, 10.0f);
}

/* ========================== Main Task ========================== */

static void robot_task(void *pvParam)
{
    ESP_LOGI(TAG, "Robot task started \u2014 MONITOR mode (default)");
    int log_counter = 0;
    mqtt_publish_status("MONITOR", "Boot default mode", 0, false);

    while (1)
    {
        /* 1. Check web commands (highest priority) */
        robot_command_t cmd = {0};
        if (mqtt_get_command(&cmd))
        {
            /* Servo commands (can run independently) */
            if (cmd.action == CMD_SERVO_LEFT)
            {
                start_servo_tracking(true);
            }
            else if (cmd.action == CMD_SERVO_RIGHT)
            {
                start_servo_tracking(false);
            }
            else if (cmd.action == CMD_SERVO_CENTER)
            {
                /* Reset cả 2 state machine trước khi về center */
                servo_state = SERVO_IDLE;
                scan_state = SCAN_IDLE;
                servo_reset_to_center();
            }
            else if (cmd.action == CMD_PATROL)
            {
                set_state(STATE_PATROL, "Web command", 0, false);
                patrol_turning = false;
                patrol_consecutive_turns = 0; /* Reset bo dem ket goc */
                scan_state = SCAN_IDLE;       /* Huy scan neu dang do */
                ESP_LOGI(TAG, ">>> PATROL MODE (web command)");
            }
            else if (cmd.action == CMD_CHASE)
            {
                set_state(STATE_CHASE, "Web command", 0, false);
                ESP_LOGI(TAG, ">>> CHASE MODE (web command)");
            }
            else if (cmd.action == CMD_MONITOR)
            {
                patrol_sweep_stop(); /* Dừng sweep khi chuyển về MONITOR */
                set_state(STATE_MONITOR, "Web command", 0, false);
                motor_stop();
                ESP_LOGI(TAG, ">>> MONITOR MODE (web command)");
            }
            else if (cmd.action == CMD_FORWARD || cmd.action == CMD_BACKWARD ||
                     cmd.action == CMD_LEFT || cmd.action == CMD_RIGHT || cmd.action == CMD_STOP)
            {
                /* Direct drive commands → MANUAL mode */
                set_state(STATE_MANUAL, "Manual drive command", 0, false);
                manual_last_cmd = now_ms();
                do_manual(&cmd);
            }
            else
            {
                /* Unknown/Invalid action? Step 1 ignores it. */
                ESP_LOGW(TAG, "Step 1: Ignoring unknown command action %d", cmd.action);
            }
        }

        /* 2. Read sensors - only sample distance when needed */
        bool pir = sensor_pir_detected(); /* PIR rất nhanh, luôn đọc */
        uint16_t distance = 0;
        sensor_distance_sample_t distance_sample = {
            .distance_mm = 0,
            .status = SENSOR_DISTANCE_STATUS_NOT_SAMPLED,
        };
        bool distance_sampled = false;
        bool is_scanning = (scan_state != SCAN_IDLE && scan_state != SCAN_DONE);
        /*
         * Only read the active distance sensor when the servo is still
         * (!servo_is_moving()).
         * Lý do: servo đang quay tạo nhiễu EMI + las1er trỏ vào vattời qua, tiết
         * kiệm CPU và tránh I2C timeout giả (sensor không có target phản xạ).
         * Servo đứng yên ~87% thời gian (789ms/900ms half-period) nên không làm chậm.
         */
        bool servo_stable = !servo_is_moving();
        if (!is_scanning && servo_stable &&
            (state == STATE_PATROL || state == STATE_CHASE || state == STATE_MONITOR))
        {
            distance = sensor_get_distance_mm();
            distance_sample = sensor_get_last_distance_sample();
            distance_sampled = true;
        }

        /* 3. Read MQTT person data */
        person_data_t person = {0};
        mqtt_get_person_data(&person);

        int64_t now = now_ms();
        bool person_active = person.detected &&
                             (now - person.received < CHASE_TIMEOUT_MS);

        /* 4. Auto state transitions */
        if (state == STATE_PATROL)
        {
            if (person_active)
            {
                /* Reset scan trước khi thoát PATROL — tránh scan zombie khi quay lại sau */
                patrol_sweep_stop(); /* Dừng sweep, trả servo về center trước khi chase */
                scan_state = SCAN_IDLE;
                patrol_consecutive_turns = 0;
                set_state(STATE_CHASE, "Auto: person detected", distance, pir);
                patrol_turning = false;
                ESP_LOGI(TAG, ">>> CHASE MODE \u2014 person detected");
            }
        }
        else if (state == STATE_MONITOR)
        {
            if (person_active)
            {
                scan_state = SCAN_IDLE; /* Cleanup phòng thủ khi thoát bất kỳ */
                set_state(STATE_CHASE, "Auto: person detected from monitor", distance, pir);
                ESP_LOGI(TAG, ">>> CHASE MODE \u2014 person detected from MONITOR");
            }
        }
        else if (state == STATE_CHASE)
        {
            if (!person_active)
            {
                /* Reset patrol state khi quay lai PATROL — tranh ket goc gia */
                patrol_consecutive_turns = 0;
                patrol_turning = false;
                scan_state = SCAN_IDLE;
                set_state(STATE_PATROL, "Auto: person lost", distance, pir);
                ESP_LOGI(TAG, ">>> PATROL MODE \u2014 person lost");
            }
        }
        else if (state == STATE_MANUAL)
        {
            /* MANUAL timeout → back to MONITOR if NO commands received for 2s.
               Critical safety fix: Stop the motor if it's currently running. */
            if (now - manual_last_cmd > MANUAL_TIMEOUT_MS)
            {
                if (!motor_is_stopped)
                {
                    motor_stop();
                    motor_is_stopped = true;
                }
                set_state(STATE_MONITOR, "Auto: manual timeout (safety)", distance, pir);
                ESP_LOGW(TAG, ">>> MONITOR MODE (Manual safety timeout — STOPPED)");
            }
        }
        /* STATE_MONITOR: no auto transitions, stays until user command */

        /* 5. Update servo tracking state machine (for web commands) */
        servo_tracking_update();

        /* 5b. Update obstacle scan state machine (for autonomous obstacle avoidance) */
        obstacle_scan_update();

        /* 5c. Update patrol sweep (dao động servo để phát hiện vật cản hẹp) */
        if (state == STATE_PATROL && !patrol_turning)
        {
            patrol_sweep_update();
        }

        /* 6. Execute state (skip if MANUAL — already handled above) */
        if (state == STATE_MONITOR)
        {
            do_monitor(distance, pir, person_active);
        }
        else if (state == STATE_PATROL)
        {
            do_patrol(distance);
        }
        else if (state == STATE_CHASE)
        {
            do_chase(&person, distance);
        }
        /* STATE_MANUAL: motor already set in do_manual() */

        /* 7. Periodic log — giảm tần suất log */
        /* [DEBUG_LOGS] - Xóa đoạn này nếu không muốn xem log cảm biến và servo nữa */
        static int64_t last_debug_print = 0;
        if (now - last_debug_print > 500)
        {
            last_debug_print = now;
            /* Servo: tính từ vị trí servo hiện tại (biến RAM, không phải I2C) */
            int16_t servo_deg = (int16_t)((servo_get_current_pos() - 1500) * 45 / 500);
            if (!distance_sampled)
            {
                ESP_LOGI("DEBUG_DATA", "Dist: N/A (%s) | Servo: %+d° | Motor: %s",
                         distance_status_name(SENSOR_DISTANCE_STATUS_NOT_SAMPLED),
                         servo_deg, motor_get_state_str());
            }
            else if (distance_sample.status == SENSOR_DISTANCE_STATUS_OK)
            {
                ESP_LOGI("DEBUG_DATA", "Dist: %d mm | Servo: %+d° | Motor: %s",
                         distance_sample.distance_mm, servo_deg, motor_get_state_str());
            }
            else
            {
                ESP_LOGI("DEBUG_DATA", "Dist: %s | Servo: %+d° | Motor: %s",
                         distance_status_name(distance_sample.status),
                         servo_deg, motor_get_state_str());
            }
        }
        /* [DEBUG_LOGS_END] */

        log_counter++;
        if (log_counter >= 100)
        { /* Mỗi 5s thay vì 2.5s */
            log_counter = 0;
            const char *names[] = {"MONITOR", "PATROL", "CHASE", "MANUAL"};
            ESP_LOGI(TAG, "[%s] dist=%dmm pir=%d person=%d pan=%.1f",
                     names[state], distance, pir, person.detected, person.pan);
        }

        /* MONITOR mode không cần poll nhanh → ngủ lâu hơn = tiết kiệm CPU */
        if (state == STATE_MONITOR)
        {
            vTaskDelay(pdMS_TO_TICKS(200)); /* 200ms — chỉ cần đọc sensor chậm */
        }
        else
        {
            vTaskDelay(pdMS_TO_TICKS(50)); /* 50ms — cần phản hồi nhanh khi chạy */
        }
    }
}

/* ========================== app_main ========================== */

void app_main(void)
{
    /*
     * Tắt Brownout Detector — tránh ESP32 reset khi nguồn USB/sạc dự phòng
     * bị sụt áp nhẹ (WiFi transmit spike ~300mA).
     * ESP32 vẫn hoạt động bình thường ở 2.3-3.3V.
     */
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);

    esp_reset_reason_t rr = esp_reset_reason();
    ESP_LOGI(TAG, "====== ESP32 Robot Controller ======");
    ESP_LOGW(TAG, "Reset reason: %d", rr);
    ESP_LOGI(TAG, "Brownout detector disabled");

    esp_err_t err = motor_init();
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "motor_init failed: %s", esp_err_to_name(err));
    }

    err = sensor_init();
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "sensor_init failed: %s", esp_err_to_name(err));
    }

    err = servo_init();
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "servo_init failed: %s", esp_err_to_name(err));
    }

    motor_stop();

    err = mqtt_app_start();
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "mqtt_app_start failed: %s", esp_err_to_name(err));
    }

    BaseType_t ok = xTaskCreatePinnedToCore(robot_task, "robot_task", 4096, NULL, 5, NULL, 1);
    if (ok != pdPASS)
    {
        ESP_LOGE(TAG, "Failed to create robot_task");
        return;
    }

    ESP_LOGI(TAG, "System ready!");
}
