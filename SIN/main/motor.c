/**
 * Motor driver — L298N dual motor (left + right)
 */

#include "motor.h"
#include "config.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "motor";

#define CH_A MOTOR_LEDC_CH_A /* Motor A (left) */
#define CH_B MOTOR_LEDC_CH_B /* Motor B (right) */
#define SPEED_MODE MOTOR_LEDC_SPEED_MODE

/* Cache tốc độ hiện tại — tránh ghi PWM thừa */
static int s_last_left = 0;
static int s_last_right = 0;

/* Soft-start: tăng speed từ từ dễ tránh sụt áp đột ngột */
#define RAMP_STEP 40     /* Mỗi bước tăng tối đa 40 */
#define RAMP_DELAY_MS 15 /* Delay giữa các bước */

/* ---------- internal helpers ---------- */

static void set_motor_a(int speed)
{
    /* ĐẢO CHIỀU MOTOR A (TRÁI): Bánh đang quay ngược ra sau -> Đảo lại để tiến lên */
    if (speed > 0)
    {
        gpio_set_level(PIN_AIN1, 0); // 1->0
        gpio_set_level(PIN_AIN2, 1); // 0->1
    }
    else if (speed < 0)
    {
        gpio_set_level(PIN_AIN1, 1); // 0->1
        gpio_set_level(PIN_AIN2, 0); // 1->0
        speed = -speed;
    }
    else
    {
        gpio_set_level(PIN_AIN1, 0);
        gpio_set_level(PIN_AIN2, 0);
    }
    if (speed > 255)
        speed = 255;
    ledc_set_duty(SPEED_MODE, CH_A, speed);
    ledc_update_duty(SPEED_MODE, CH_A);
}

static void set_motor_b(int speed)
{
    /* ĐẢO CHIỀU MOTOR B (PHẢI): Bánh đang quay ngược vô trong -> Đảo lại để tiến lên */
    if (speed > 0)
    {
        gpio_set_level(PIN_BIN1, 0); // 1->0
        gpio_set_level(PIN_BIN2, 1); // 0->1
    }
    else if (speed < 0)
    {
        gpio_set_level(PIN_BIN1, 1); // 0->1
        gpio_set_level(PIN_BIN2, 0); // 1->0
        speed = -speed;
    }
    else
    {
        gpio_set_level(PIN_BIN1, 0);
        gpio_set_level(PIN_BIN2, 0);
    }
    if (speed > 255)
        speed = 255;
    ledc_set_duty(SPEED_MODE, CH_B, speed);
    ledc_update_duty(SPEED_MODE, CH_B);
}

/* ---------- public API ---------- */

esp_err_t motor_init(void)
{
    /* GPIO: direction pins */
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << PIN_AIN1) | (1ULL << PIN_AIN2) |
                        (1ULL << PIN_BIN1) | (1ULL << PIN_BIN2),
        .mode = GPIO_MODE_OUTPUT,
    };
    gpio_config(&io);

    /* PWM timer (shared by both channels) */
    ledc_timer_config_t timer = {
        .duty_resolution = PWM_RESOLUTION,
        .freq_hz = PWM_FREQ,
        .speed_mode = SPEED_MODE,
        .timer_num = MOTOR_LEDC_TIMER,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ledc_timer_config(&timer);

    /* Channel A — Motor left */
    ledc_channel_config_t ch_a = {
        .channel = CH_A,
        .duty = 0,
        .gpio_num = PIN_PWMA,
        .speed_mode = SPEED_MODE,
        .timer_sel = MOTOR_LEDC_TIMER,
    };
    ledc_channel_config(&ch_a);

    /* Channel B — Motor right */
    ledc_channel_config_t ch_b = {
        .channel = CH_B,
        .duty = 0,
        .gpio_num = PIN_PWMB,
        .speed_mode = SPEED_MODE,
        .timer_sel = MOTOR_LEDC_TIMER,
    };
    ledc_channel_config(&ch_b);

    ESP_LOGI(TAG, "Motor A(L) + B(R) initialized");
    return ESP_OK;
}

void motor_set(int left_speed, int right_speed)
{
    /* Skip nếu speed không đổi — tránh ghi PWM thừa */
    if (left_speed == s_last_left && right_speed == s_last_right)
        return;
    s_last_left = left_speed;
    s_last_right = right_speed;
    set_motor_a(left_speed);
    set_motor_b(right_speed);
}

/**
 * Soft-start: tăng tốc từ từ thay vì nhảy đột ngột.
 * Giúp giảm dòng đỉnh (peak current) → ít sụt áp.
 *
 * VD: speed=100, hiện tại=0 → tăng: 0→40→80→100 (3 bước)
 */
void motor_forward_ramp(int target_speed)
{
    int current = (s_last_left > 0) ? s_last_left : 0;
    while (current < target_speed)
    {
        current += RAMP_STEP;
        if (current > target_speed)
            current = target_speed;
        motor_set(current, current);
        vTaskDelay(pdMS_TO_TICKS(RAMP_DELAY_MS));
    }
}

void motor_forward(int speed)
{
    if (s_last_left < 0 || s_last_right < 0)
    {
        /* Đang chạy lùi, muốn tiến -> Bắt buộc Stop 50ms cắt dòng ngược */
        motor_stop();
        vTaskDelay(pdMS_TO_TICKS(50));
    }
    motor_set(speed, speed);
}

void motor_backward(int speed)
{
    if (s_last_left > 0 || s_last_right > 0)
    {
        /* Đang chạy tiến, muốn lùi -> Bắt buộc Stop 50ms cắt dòng ngược */
        motor_stop();
        vTaskDelay(pdMS_TO_TICKS(50));
    }
    motor_set(-speed, -speed);
}

void motor_turn_left(int speed)
{
    speed = speed + 30;              /* Tăng speed để quay nhanh hơn, tránh bị lệch do bánh phải có lực kéo lớn hơn (do quay ngược) */
    motor_set(speed, -speed); /* map thực tế: lùi trái, tới phải -> quay trái */
}

void motor_turn_right(int speed)
{
    speed = speed + 30; /* Tăng speed để quay nhanh hơn, tránh bị lệch do bánh trái có lực kéo lớn hơn (do quay ngược) */

    motor_set(-speed, speed); /* map thực tế: tới trái, lùi phải -> quay phải */
}

void motor_stop(void)
{
    motor_set(0, 0);
}

const char *motor_get_state_str(void)
{
    if (s_last_left == 0 && s_last_right == 0)
        return "STOP";
    if (s_last_left > 0 && s_last_right > 0)
        return "FORWARD";
    if (s_last_left < 0 && s_last_right < 0)
        return "BACKWARD";
    if (s_last_left < 0 && s_last_right > 0)
        return "TURN LEFT";
    if (s_last_left > 0 && s_last_right < 0)
        return "TURN RIGHT";
    return "UNKNOWN";
}
