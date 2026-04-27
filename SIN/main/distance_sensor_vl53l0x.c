#include "distance_sensor_driver.h"

#include "config.h"
#include "driver/i2c.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "dist_vl53l0x";

static bool s_vl53l0x_ok = false;
static int s_i2c_sda = PIN_SDA;
static int s_i2c_scl = PIN_SCL;
static bool s_i2c_driver_installed = false;
static uint32_t s_range_timeout_count = 0;
static uint32_t s_range_error_count = 0;
static uint8_t s_stop_variable = 0;

#define I2C_PORT       I2C_NUM_0
#define I2C_FREQ_HZ    100000
#define I2C_TIMEOUT_MS 20

#define VL53L0X_REG_IDENTIFICATION_MODEL_ID 0xC0
#define VL53L0X_REG_SYSRANGE_START 0x00
#define VL53L0X_REG_RESULT_INTERRUPT_STATUS 0x13
#define VL53L0X_REG_SYSTEM_INTERRUPT_CLEAR 0x0B

static sensor_distance_sample_t make_sample(sensor_distance_status_t status, uint16_t distance_mm)
{
    sensor_distance_sample_t sample = {
        .distance_mm = distance_mm,
        .status = status,
    };
    return sample;
}

static esp_err_t i2c_reconfigure_pins(int sda, int scl)
{
    i2c_config_t i2c_conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = sda,
        .scl_io_num = scl,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = I2C_FREQ_HZ,
    };

    if (s_i2c_driver_installed) {
        i2c_driver_delete(I2C_PORT);
        s_i2c_driver_installed = false;
    }

    esp_err_t err = i2c_param_config(I2C_PORT, &i2c_conf);
    if (err != ESP_OK) {
        return err;
    }

    err = i2c_driver_install(I2C_PORT, I2C_MODE_MASTER, 0, 0, 0);
    if (err == ESP_OK) {
        s_i2c_driver_installed = true;
        s_i2c_sda = sda;
        s_i2c_scl = scl;
    }
    return err;
}

static esp_err_t i2c_probe_addr(uint8_t addr)
{
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (addr << 1) | I2C_MASTER_WRITE, true);
    i2c_master_stop(cmd);
    esp_err_t err = i2c_master_cmd_begin(I2C_PORT, cmd, pdMS_TO_TICKS(20));
    i2c_cmd_link_delete(cmd);
    return err;
}

static int i2c_scan_bus(void)
{
    int found = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        if (i2c_probe_addr(addr) == ESP_OK) {
            ESP_LOGI(TAG, "I2C device found at address 0x%02X", addr);
            found++;
        }
    }
    return found;
}

static esp_err_t vl53l0x_write_byte(uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = {reg, val};
    return i2c_master_write_to_device(I2C_PORT, VL53L0X_ADDR, buf, 2,
                                      I2C_TIMEOUT_MS / portTICK_PERIOD_MS);
}

static esp_err_t vl53l0x_read_bytes(uint8_t reg, uint8_t *data, size_t len)
{
    return i2c_master_write_read_device(I2C_PORT, VL53L0X_ADDR,
                                        &reg, 1, data, len,
                                        I2C_TIMEOUT_MS / portTICK_PERIOD_MS);
}

static esp_err_t vl53_read_reg16_u8(uint16_t reg16, uint8_t *val)
{
    uint8_t reg_buf[2] = {(uint8_t)(reg16 >> 8), (uint8_t)(reg16 & 0xFF)};
    return i2c_master_write_read_device(I2C_PORT, VL53L0X_ADDR,
                                        reg_buf, 2, val, 1,
                                        I2C_TIMEOUT_MS / portTICK_PERIOD_MS);
}

static void vl53l0x_run_calibration(uint8_t sequence_config, uint8_t sysrange_start, const char *label)
{
    uint8_t cal_intr = 0;

    vl53l0x_write_byte(0x01, sequence_config);
    vl53l0x_write_byte(0x00, sysrange_start);
    for (int i = 0; i < 60; i++) {
        vTaskDelay(pdMS_TO_TICKS(5));
        vl53l0x_read_bytes(0x13, &cal_intr, 1);
        if ((cal_intr & 0x07) != 0) {
            break;
        }
    }
    vl53l0x_write_byte(0x0B, 0x01);
    vl53l0x_write_byte(0x00, 0x00);
    ESP_LOGI(TAG, "VL53L0X %s calibration done (intr=0x%02X)", label, cal_intr);
}

static esp_err_t vl53l0x_init(void)
{
    s_vl53l0x_ok = false;

    esp_err_t err = i2c_reconfigure_pins(PIN_SDA, PIN_SCL);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C init failed on SDA=%d SCL=%d: %s",
                 PIN_SDA, PIN_SCL, esp_err_to_name(err));
        return err;
    }

    ESP_LOGI(TAG, "Starting I2C scan (SDA=%d SCL=%d)...", s_i2c_sda, s_i2c_scl);
    int i2c_devices_found = i2c_scan_bus();
    if (i2c_devices_found == 0) {
        ESP_LOGW(TAG, "No I2C device found on SDA=%d SCL=%d", s_i2c_sda, s_i2c_scl);
    }
    ESP_LOGI(TAG, "I2C scan complete. Found %d devices.", i2c_devices_found);

    uint8_t model_id = 0;
    err = vl53l0x_read_bytes(VL53L0X_REG_IDENTIFICATION_MODEL_ID, &model_id, 1);
    if (err == ESP_OK && model_id == 0xEE) {
        ESP_LOGI(TAG, "VL53L0X detected successfully (id=0x%02X, SDA=%d, SCL=%d)",
                 model_id, s_i2c_sda, s_i2c_scl);
        s_vl53l0x_ok = true;

        vl53l0x_write_byte(0x80, 0x01);
        vl53l0x_write_byte(0xFF, 0x01);
        vl53l0x_write_byte(0x00, 0x00);
        vl53l0x_read_bytes(0x91, &s_stop_variable, 1);
        vl53l0x_write_byte(0x00, 0x01);
        vl53l0x_write_byte(0xFF, 0x00);
        vl53l0x_write_byte(0x80, 0x00);
        ESP_LOGI(TAG, "VL53L0X stop_variable=0x%02X", s_stop_variable);

        vl53l0x_write_byte(0xFF, 0x01);
        vl53l0x_write_byte(0x00, 0x00);
        vl53l0x_write_byte(0xFF, 0x00);
        vl53l0x_write_byte(0x09, 0x00);
        vl53l0x_write_byte(0x10, 0x00);
        vl53l0x_write_byte(0x11, 0x00);
        vl53l0x_write_byte(0x24, 0x01);
        vl53l0x_write_byte(0x25, 0xFF);
        vl53l0x_write_byte(0x75, 0x00);
        vl53l0x_write_byte(0xFF, 0x01);
        vl53l0x_write_byte(0x4E, 0x2C);
        vl53l0x_write_byte(0x48, 0x00);
        vl53l0x_write_byte(0x30, 0x20);
        vl53l0x_write_byte(0xFF, 0x00);
        vl53l0x_write_byte(0x30, 0x09);
        vl53l0x_write_byte(0x54, 0x00);
        vl53l0x_write_byte(0x31, 0x04);
        vl53l0x_write_byte(0x32, 0x03);
        vl53l0x_write_byte(0x40, 0x83);
        vl53l0x_write_byte(0x46, 0x25);
        vl53l0x_write_byte(0x60, 0x00);
        vl53l0x_write_byte(0x27, 0x00);
        vl53l0x_write_byte(0x50, 0x06);
        vl53l0x_write_byte(0x51, 0x00);
        vl53l0x_write_byte(0x52, 0x96);
        vl53l0x_write_byte(0x56, 0x08);
        vl53l0x_write_byte(0x57, 0x30);
        vl53l0x_write_byte(0x61, 0x00);
        vl53l0x_write_byte(0x62, 0x00);
        vl53l0x_write_byte(0x64, 0x00);
        vl53l0x_write_byte(0x65, 0x00);
        vl53l0x_write_byte(0x66, 0xA0);
        vl53l0x_write_byte(0xFF, 0x01);
        vl53l0x_write_byte(0x22, 0x32);
        vl53l0x_write_byte(0x47, 0x14);
        vl53l0x_write_byte(0x49, 0xFF);
        vl53l0x_write_byte(0x4A, 0x00);
        vl53l0x_write_byte(0xFF, 0x00);
        vl53l0x_write_byte(0x7A, 0x0A);
        vl53l0x_write_byte(0x7B, 0x00);
        vl53l0x_write_byte(0x78, 0x21);
        vl53l0x_write_byte(0xFF, 0x01);
        vl53l0x_write_byte(0x23, 0x34);
        vl53l0x_write_byte(0x42, 0x00);
        vl53l0x_write_byte(0x44, 0xFF);
        vl53l0x_write_byte(0x45, 0x26);
        vl53l0x_write_byte(0x46, 0x05);
        vl53l0x_write_byte(0x40, 0x40);
        vl53l0x_write_byte(0x0E, 0x06);
        vl53l0x_write_byte(0x20, 0x1A);
        vl53l0x_write_byte(0x43, 0x40);
        vl53l0x_write_byte(0xFF, 0x00);
        vl53l0x_write_byte(0x34, 0x03);
        vl53l0x_write_byte(0x35, 0x44);
        vl53l0x_write_byte(0xFF, 0x01);
        vl53l0x_write_byte(0x31, 0x04);
        vl53l0x_write_byte(0x4B, 0x09);
        vl53l0x_write_byte(0x4C, 0x05);
        vl53l0x_write_byte(0x4D, 0x04);
        vl53l0x_write_byte(0xFF, 0x00);
        vl53l0x_write_byte(0x44, 0x00);
        vl53l0x_write_byte(0x45, 0x20);
        vl53l0x_write_byte(0x47, 0x08);
        vl53l0x_write_byte(0x48, 0x28);
        vl53l0x_write_byte(0x67, 0x00);
        vl53l0x_write_byte(0x70, 0x04);
        vl53l0x_write_byte(0x71, 0x01);
        vl53l0x_write_byte(0x72, 0xFE);
        vl53l0x_write_byte(0x76, 0x00);
        vl53l0x_write_byte(0x77, 0x00);
        vl53l0x_write_byte(0xFF, 0x01);
        vl53l0x_write_byte(0x0D, 0x01);
        vl53l0x_write_byte(0xFF, 0x00);
        vl53l0x_write_byte(0x80, 0x01);
        vl53l0x_write_byte(0x01, 0xF8);
        vl53l0x_write_byte(0xFF, 0x01);
        vl53l0x_write_byte(0x8E, 0x01);
        vl53l0x_write_byte(0x00, 0x01);
        vl53l0x_write_byte(0xFF, 0x00);
        vl53l0x_write_byte(0x80, 0x00);
        ESP_LOGI(TAG, "VL53L0X tuning settings loaded");

        vl53l0x_write_byte(0x0A, 0x04);
        uint8_t gpio_hv = 0;
        vl53l0x_read_bytes(0x84, &gpio_hv, 1);
        vl53l0x_write_byte(0x84, gpio_hv & (uint8_t)~0x10);
        vl53l0x_write_byte(0x0B, 0x01);
        vl53l0x_write_byte(0x01, 0xE8);

        vl53l0x_run_calibration(0x01, 0x41, "VHV");
        vl53l0x_run_calibration(0x02, 0x01, "Phase");
        vl53l0x_write_byte(0x01, 0xE8);
        vTaskDelay(pdMS_TO_TICKS(10));
        ESP_LOGI(TAG, "VL53L0X interrupt configured (mode=new-sample-ready)");
        return ESP_OK;
    }

    if (i2c_probe_addr(VL53L0X_ADDR) == ESP_OK) {
        uint8_t reg_c1 = 0;
        uint8_t reg_c2 = 0;
        uint8_t l1x_model = 0;
        uint8_t l1x_type = 0;
        esp_err_t e_c1 = vl53l0x_read_bytes(0xC1, &reg_c1, 1);
        esp_err_t e_c2 = vl53l0x_read_bytes(0xC2, &reg_c2, 1);
        esp_err_t e_l1x_m = vl53_read_reg16_u8(0x010F, &l1x_model);
        esp_err_t e_l1x_t = vl53_read_reg16_u8(0x0110, &l1x_type);

        ESP_LOGW(TAG, "ToF ACK at 0x%02X but unexpected ID (C0=0x%02X, err=%d)",
                 VL53L0X_ADDR, model_id, err);
        ESP_LOGW(TAG, "Diag regs: C1=0x%02X(err=%d) C2=0x%02X(err=%d) 010F=0x%02X(err=%d) 0110=0x%02X(err=%d)",
                 reg_c1, e_c1, reg_c2, e_c2, l1x_model, e_l1x_m, l1x_type, e_l1x_t);
        ESP_LOGE(TAG, "Unsupported ToF register profile. Disable ranging until correct sensor driver is used.");
        return ESP_ERR_NOT_SUPPORTED;
    }

    ESP_LOGE(TAG, "VL53L0X init failed on SDA=%d SCL=%d. Expected model_id 0xEE, got 0x%02X (err=%d)",
             s_i2c_sda, s_i2c_scl, model_id, err);
    return (err == ESP_OK) ? ESP_ERR_NOT_FOUND : err;
}

static sensor_distance_sample_t vl53l0x_read(void)
{
    static uint32_t s_diag_count = 0;
    static uint8_t s_consecutive_timeouts = 0;

    if (!s_vl53l0x_ok) {
        return make_sample(SENSOR_DISTANCE_STATUS_NOT_READY, 0);
    }

    s_diag_count++;
    bool diag = (s_diag_count % 30 == 1);

    esp_err_t pre_err = ESP_OK;
    pre_err |= vl53l0x_write_byte(0x80, 0x01);
    pre_err |= vl53l0x_write_byte(0xFF, 0x01);
    pre_err |= vl53l0x_write_byte(0x00, 0x00);
    pre_err |= vl53l0x_write_byte(0x91, s_stop_variable);
    pre_err |= vl53l0x_write_byte(0x00, 0x01);
    pre_err |= vl53l0x_write_byte(0xFF, 0x00);
    pre_err |= vl53l0x_write_byte(0x80, 0x00);
    if (pre_err != ESP_OK) {
        ESP_LOGW(TAG, "[DIAG] Preamble write failed (err=%d) stop_var=0x%02X", pre_err, s_stop_variable);
        return make_sample(SENSOR_DISTANCE_STATUS_ERROR, 0);
    }

    esp_err_t err = vl53l0x_write_byte(VL53L0X_REG_SYSRANGE_START, 0x01);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "[DIAG] SYSRANGE_START write failed");
        return make_sample(SENSOR_DISTANCE_STATUS_ERROR, 0);
    }

    uint8_t start_byte = 0x01;
    int step1_polls = 0;
    for (int i = 0; i < 20; i++) {
        vTaskDelay(pdMS_TO_TICKS(5));
        err = vl53l0x_read_bytes(VL53L0X_REG_SYSRANGE_START, &start_byte, 1);
        step1_polls++;
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "[DIAG] Step1 I2C read failed at poll %d", i);
            return make_sample(SENSOR_DISTANCE_STATUS_ERROR, 0);
        }
        if ((start_byte & 0x01) == 0) {
            break;
        }
    }
    if (diag) {
        ESP_LOGI(TAG, "[DIAG #%lu] Step1 done: start_byte=0x%02X polls=%d",
                 (unsigned long)s_diag_count, start_byte, step1_polls);
    }
    if (start_byte & 0x01) {
        ESP_LOGW(TAG, "[DIAG] Step1 timeout: SYSRANGE_START bit never cleared (start_byte=0x%02X)", start_byte);
        return make_sample(SENSOR_DISTANCE_STATUS_TIMEOUT, 0);
    }

    uint8_t intr = 0;
    bool ready = false;
    int step2_polls = 0;
    for (int i = 0; i < 50; i++) {
        vTaskDelay(pdMS_TO_TICKS(5));
        err = vl53l0x_read_bytes(VL53L0X_REG_RESULT_INTERRUPT_STATUS, &intr, 1);
        step2_polls++;
        if (err != ESP_OK) {
            vl53l0x_write_byte(VL53L0X_REG_SYSTEM_INTERRUPT_CLEAR, 0x01);
            ESP_LOGW(TAG, "[DIAG] Step2 I2C read failed at poll %d", i);
            return make_sample(SENSOR_DISTANCE_STATUS_ERROR, 0);
        }
        if (intr & 0x07) {
            ready = true;
            break;
        }
    }
    if (diag) {
        ESP_LOGI(TAG, "[DIAG #%lu] Step2 done: intr=0x%02X ready=%d polls=%d",
                 (unsigned long)s_diag_count, intr, ready, step2_polls);
    }

    if (!ready) {
        s_range_timeout_count++;
        vl53l0x_write_byte(VL53L0X_REG_SYSTEM_INTERRUPT_CLEAR, 0x01);
        vl53l0x_write_byte(VL53L0X_REG_SYSRANGE_START, 0x00);
        vTaskDelay(pdMS_TO_TICKS(5));

        if ((s_range_timeout_count % 10) == 1) {
            ESP_LOGW(TAG, "[DIAG] Step2 timeout (count=%lu, intr=0x%02X, stop_var=0x%02X) - measurement aborted",
                     (unsigned long)s_range_timeout_count, intr, s_stop_variable);
        }

        s_consecutive_timeouts++;
        if (s_consecutive_timeouts >= 5) {
            s_consecutive_timeouts = 0;
            ESP_LOGW(TAG, "[SENSOR] 5 consecutive timeouts - running re-calibration");
            vl53l0x_run_calibration(0x01, 0x41, "VHV");
            vl53l0x_run_calibration(0x02, 0x01, "Phase");
            vl53l0x_write_byte(0x01, 0xE8);
            vl53l0x_write_byte(0x0B, 0x01);
            ESP_LOGI(TAG, "[SENSOR] Re-calibration done");
        }

        return make_sample(SENSOR_DISTANCE_STATUS_TIMEOUT, 0);
    }

    s_consecutive_timeouts = 0;

    uint8_t data[2];
    err = vl53l0x_read_bytes(0x1E, data, 2);
    vl53l0x_write_byte(VL53L0X_REG_SYSTEM_INTERRUPT_CLEAR, 0x01);

    if (err != ESP_OK) {
        s_range_error_count++;
        if ((s_range_error_count % 20) == 1) {
            ESP_LOGW(TAG, "VL53L0X read error (count=%lu, err=%s)",
                     (unsigned long)s_range_error_count, esp_err_to_name(err));
        }
        return make_sample(SENSOR_DISTANCE_STATUS_ERROR, 0);
    }

    uint16_t distance = ((uint16_t)data[0] << 8) | data[1];
    if (diag) {
        ESP_LOGI(TAG, "[DIAG #%lu] raw distance=%u mm (data=0x%02X 0x%02X)%s",
                 (unsigned long)s_diag_count, distance, data[0], data[1],
                 distance >= 8190 ? " [NO_TARGET]" : "");
    }

    if (distance == 0) {
        return make_sample(SENSOR_DISTANCE_STATUS_ERROR, 0);
    }
    if (distance >= 8190) {
        return make_sample(SENSOR_DISTANCE_STATUS_NO_TARGET, 0);
    }
    return make_sample(SENSOR_DISTANCE_STATUS_OK, distance);
}

const distance_sensor_driver_t g_distance_sensor_vl53l0x_driver = {
    .name = "VL53L0X",
    .init = vl53l0x_init,
    .read = vl53l0x_read,
};
