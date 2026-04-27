#include "distance_sensor_driver.h"

#include "config.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "rom/ets_sys.h"

static const char *TAG = "dist_hcsr04";

static bool s_hcsr04_initialized = false;
static uint32_t s_timeout_count = 0;

static sensor_distance_sample_t make_sample(sensor_distance_status_t status, uint16_t distance_mm)
{
    sensor_distance_sample_t sample = {
        .distance_mm = distance_mm,
        .status = status,
    };
    return sample;
}

static bool wait_for_level(int expected_level, int64_t timeout_us, int64_t *matched_at_us)
{
    int64_t start_us = esp_timer_get_time();
    while ((esp_timer_get_time() - start_us) < timeout_us) {
        if (gpio_get_level(PIN_HCSR04_ECHO) == expected_level) {
            if (matched_at_us != NULL) {
                *matched_at_us = esp_timer_get_time();
            }
            return true;
        }
    }
    return false;
}

static esp_err_t hcsr04_init(void)
{
    gpio_config_t trig_conf = {
        .pin_bit_mask = (1ULL << PIN_HCSR04_TRIG),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t err = gpio_config(&trig_conf);
    if (err != ESP_OK) {
        return err;
    }

    gpio_config_t echo_conf = {
        .pin_bit_mask = (1ULL << PIN_HCSR04_ECHO),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    err = gpio_config(&echo_conf);
    if (err != ESP_OK) {
        return err;
    }

    gpio_set_level(PIN_HCSR04_TRIG, 0);
    s_hcsr04_initialized = true;
    ESP_LOGI(TAG, "HC-SR04 configured (TRIG=%d, ECHO=%d)",
             PIN_HCSR04_TRIG, PIN_HCSR04_ECHO);
    return ESP_OK;
}

static sensor_distance_sample_t hcsr04_read(void)
{
    if (!s_hcsr04_initialized) {
        return make_sample(SENSOR_DISTANCE_STATUS_NOT_READY, 0);
    }

    if (!wait_for_level(0, HCSR04_ECHO_TIMEOUT_US, NULL)) {
        s_timeout_count++;
        if ((s_timeout_count % 20) == 1) {
            ESP_LOGW(TAG, "HC-SR04 ECHO line stayed high before trigger (count=%lu)",
                     (unsigned long)s_timeout_count);
        }
        return make_sample(SENSOR_DISTANCE_STATUS_TIMEOUT, 0);
    }

    gpio_set_level(PIN_HCSR04_TRIG, 0);
    ets_delay_us(2);
    gpio_set_level(PIN_HCSR04_TRIG, 1);
    ets_delay_us(10);
    gpio_set_level(PIN_HCSR04_TRIG, 0);

    int64_t pulse_start_us = 0;
    int64_t pulse_end_us = 0;
    if (!wait_for_level(1, HCSR04_ECHO_TIMEOUT_US, &pulse_start_us)) {
        s_timeout_count++;
        if ((s_timeout_count % 20) == 1) {
            ESP_LOGW(TAG, "HC-SR04 wait-for-rise timeout (count=%lu)",
                     (unsigned long)s_timeout_count);
        }
        return make_sample(SENSOR_DISTANCE_STATUS_TIMEOUT, 0);
    }

    if (!wait_for_level(0, HCSR04_ECHO_TIMEOUT_US, &pulse_end_us)) {
        s_timeout_count++;
        if ((s_timeout_count % 20) == 1) {
            ESP_LOGW(TAG, "HC-SR04 wait-for-fall timeout (count=%lu)",
                     (unsigned long)s_timeout_count);
        }
        return make_sample(SENSOR_DISTANCE_STATUS_TIMEOUT, 0);
    }

    int64_t pulse_us = pulse_end_us - pulse_start_us;
    if (pulse_us <= 0) {
        return make_sample(SENSOR_DISTANCE_STATUS_ERROR, 0);
    }

    uint32_t distance_mm = (uint32_t)(((uint64_t)pulse_us * 343U) / 2000U);
    if (distance_mm < HCSR04_MIN_DISTANCE_MM || distance_mm > HCSR04_MAX_DISTANCE_MM) {
        return make_sample(SENSOR_DISTANCE_STATUS_NO_TARGET, 0);
    }

    s_timeout_count = 0;
    return make_sample(SENSOR_DISTANCE_STATUS_OK, (uint16_t)distance_mm);
}

const distance_sensor_driver_t g_distance_sensor_hcsr04_driver = {
    .name = "HC-SR04",
    .init = hcsr04_init,
    .read = hcsr04_read,
};
