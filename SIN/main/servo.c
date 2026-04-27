/**
 * Servo Control Implementation — ESP32 PWM LEDC
 */

#include "servo.h"
#include "config.h"

#include "esp_err.h"
#include "esp_log.h"
#include "driver/ledc.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "servo";

/* Servo state — volatile used to ensure thread safety between robot_task and servo_task */
static volatile uint16_t current_pos_us = SERVO_ANGLE_CENTER;
static volatile uint16_t target_pos_us = SERVO_ANGLE_CENTER;
static float current_speed_us_per_ms = 0.0f;
static volatile bool is_moving = false;
static int64_t move_start_time_ms = 0;
static servo_callback_t reached_callback = NULL;

/* PWM config */
#define SERVO_PWM_FREQ 50        /* 50 Hz (20ms period) */
#define SERVO_PWM_DURATION 20000 /* 20ms period in us */
#define SERVO_LEDC_MODE SERVO_LEDC_SPEED_MODE

static void servo_task(void *pvParam);
static uint32_t us_to_duty(uint16_t us);

/* Apply PWM duty without changing motion state flags. */
static void servo_apply_pwm_raw(uint16_t target_us)
{
    if (target_us < 1000)
        target_us = 1000;
    if (target_us > 2000)
        target_us = 2000;

    uint32_t duty = us_to_duty(target_us);
    ledc_set_duty(SERVO_LEDC_MODE, SERVO_LEDC_CHANNEL, duty);
    ledc_update_duty(SERVO_LEDC_MODE, SERVO_LEDC_CHANNEL);
    current_pos_us = target_us;
}

/**
 * Khởi tạo Servo — setup LEDC PWM trên PIN_SERVO_PAN
 */
esp_err_t servo_init(void)
{
    /* Timer config (50 Hz) */
    ledc_timer_config_t timer_config = {
        .speed_mode = SERVO_LEDC_MODE,
        .timer_num = SERVO_LEDC_TIMER,
        .clk_cfg = LEDC_AUTO_CLK,
        .freq_hz = SERVO_PWM_FREQ,
        .duty_resolution = LEDC_TIMER_13_BIT, /* 13-bit = 0-8191 (large enough for servo) */
    };
    esp_err_t ret = ledc_timer_config(&timer_config);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "LEDC timer config failed: %s", esp_err_to_name(ret));
        return ret;
    }

    /* Channel config */
    ledc_channel_config_t channel_config = {
        .gpio_num = PIN_SERVO_PAN,
        .speed_mode = SERVO_LEDC_MODE,
        .channel = SERVO_LEDC_CHANNEL,
        .timer_sel = SERVO_LEDC_TIMER,
        .duty = 0,
        .intr_type = LEDC_INTR_DISABLE,
        .flags.output_invert = 0,
    };
    ret = ledc_channel_config(&channel_config);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "LEDC channel config failed: %s", esp_err_to_name(ret));
        return ret;
    }

    /* Set servo về center (1500 us = 1.5ms out of 20ms) */
    servo_set_pwm(SERVO_ANGLE_CENTER);
    ESP_LOGI(TAG, "Servo initialized on GPIO %d (center=1500us)", PIN_SERVO_PAN);

    /* Create background task để handle smooth movement */
    xTaskCreate(servo_task, "servo_task", 2048, NULL, 5, NULL);

    return ESP_OK;
}

/**
 * Tính duty cycle từ microsecond
 * PWM: 20ms period, 13-bit resolution (0-8191)
 *   1000 us = 5%   duty = 0.05 * 8191 = 409
 *   1500 us = 7.5% duty = 0.075 * 8191 = 614
 *   2000 us = 10%  duty = 0.10 * 8191 = 819
 */
static uint32_t us_to_duty(uint16_t us)
{
    /* duty = (us / 20000) * 8191 */
    uint32_t duty = (uint32_t)((uint64_t)us * 8191 / SERVO_PWM_DURATION);
    return duty;
}

/**
 * Set PWM immediately
 */
void servo_set_pwm(uint16_t target_us)
{
    servo_apply_pwm_raw(target_us);
    target_pos_us = current_pos_us;
    is_moving = false;
}

/**
 * Move servo smoothly (ramp)
 */
void servo_move_smooth(uint16_t target_us, float speed_us_per_ms)
{
    if (target_us < 1000)
        target_us = 1000;
    if (target_us > 2000)
        target_us = 2000;

    target_pos_us = target_us;
    current_speed_us_per_ms = speed_us_per_ms;
    is_moving = true;
    move_start_time_ms = esp_timer_get_time() / 1000;
}

/**
 * Background task để smooth servo movement
 */
static void servo_task(void *pvParam)
{
    while (1)
    {
        if (is_moving)
        {
            /* Run fixed-step motion every 20ms for stable behavior. */
            uint16_t step = (uint16_t)(current_speed_us_per_ms * 20.0f);
            if (step < 1)
                step = 1;

            if (target_pos_us > current_pos_us)
            {
                uint16_t diff = (uint16_t)(target_pos_us - current_pos_us);
                uint16_t next = (step >= diff) ? target_pos_us : (uint16_t)(current_pos_us + step);
                servo_apply_pwm_raw(next);
            }
            else if (target_pos_us < current_pos_us)
            {
                uint16_t diff = (uint16_t)(current_pos_us - target_pos_us);
                uint16_t next = (step >= diff) ? target_pos_us : (uint16_t)(current_pos_us - step);
                servo_apply_pwm_raw(next);
            }

            if (current_pos_us == target_pos_us)
            {
                is_moving = false;
                if (reached_callback)
                {
                    reached_callback();
                }
            }
        }

        vTaskDelay(pdMS_TO_TICKS(20)); /* Update mỗi 20ms */
    }
}

/**
 * Lấy vị trí servo hiện tại
 */
uint16_t servo_get_current_pos(void)
{
    return current_pos_us;
}

/**
 * Check nếu servo đang di chuyển
 */
bool servo_is_moving(void)
{
    return is_moving;
}

/**
 * Reset servo về center
 */
void servo_reset_to_center(void)
{
    /* Non-blocking: just start the move. Main loop shouldn't freeze. */
    servo_move_smooth(SERVO_ANGLE_CENTER, 2.0f);
}

/**
 * Set callback khi servo tới đích
 */
void servo_set_reached_callback(servo_callback_t cb)
{
    reached_callback = cb;
}
