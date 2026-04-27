#include "sensor.h"

#include "config.h"
#include "distance_sensor_driver.h"
#include "driver/gpio.h"
#include "esp_log.h"

static const char *TAG = "sensor";

static const distance_sensor_driver_t *s_distance_driver = NULL;
static sensor_distance_sample_t s_last_distance_sample = {
    .distance_mm = 0,
    .status = SENSOR_DISTANCE_STATUS_NOT_SAMPLED,
};
static bool s_distance_driver_ready = false;

static const distance_sensor_driver_t *select_distance_driver(void)
{
#if DIST_SENSOR_BACKEND == DIST_SENSOR_BACKEND_VL53L0X
    return &g_distance_sensor_vl53l0x_driver;
#elif DIST_SENSOR_BACKEND == DIST_SENSOR_BACKEND_HCSR04
    return &g_distance_sensor_hcsr04_driver;
#else
#error Unsupported DIST_SENSOR_BACKEND value
#endif
}

static esp_err_t sensor_init_pir(void)
{
    gpio_config_t pir_conf = {
        .pin_bit_mask = (1ULL << PIN_PIR),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
    };

    esp_err_t err = gpio_config(&pir_conf);
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "PIR sensor on GPIO %d", PIN_PIR);
    } else {
        ESP_LOGE(TAG, "PIR init failed on GPIO %d: %s", PIN_PIR, esp_err_to_name(err));
    }
    return err;
}

esp_err_t sensor_init(void)
{
    esp_err_t pir_err = sensor_init_pir();

    s_distance_driver = select_distance_driver();
    s_distance_driver_ready = false;
    s_last_distance_sample.distance_mm = 0;
    s_last_distance_sample.status = SENSOR_DISTANCE_STATUS_NOT_READY;

    ESP_LOGI(TAG, "Distance sensor backend: %s", s_distance_driver->name);
    esp_err_t distance_err = s_distance_driver->init();
    if (distance_err == ESP_OK) {
        s_distance_driver_ready = true;
        s_last_distance_sample.status = SENSOR_DISTANCE_STATUS_NOT_SAMPLED;
    } else {
        ESP_LOGE(TAG, "Distance sensor init failed for %s: %s",
                 s_distance_driver->name, esp_err_to_name(distance_err));
    }

    if (pir_err != ESP_OK) {
        return pir_err;
    }
    return distance_err;
}

uint16_t sensor_get_distance_mm(void)
{
    if (!s_distance_driver_ready || s_distance_driver == NULL) {
        s_last_distance_sample.distance_mm = 0;
        s_last_distance_sample.status = SENSOR_DISTANCE_STATUS_NOT_READY;
        return 0;
    }

    s_last_distance_sample = s_distance_driver->read();
    if (s_last_distance_sample.status != SENSOR_DISTANCE_STATUS_OK) {
        return 0;
    }
    return s_last_distance_sample.distance_mm;
}

sensor_distance_sample_t sensor_get_last_distance_sample(void)
{
    return s_last_distance_sample;
}

bool sensor_pir_detected(void)
{
    return gpio_get_level(PIN_PIR) == 1;
}
