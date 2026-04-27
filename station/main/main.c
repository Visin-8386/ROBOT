/**
 * ESP32-CAM OV3660 — Main application
 * ------------------------------------
 * 1. Initialize NVS
 * 2. Connect to WiFi (SSID / Password hardcoded below)
 * 3. Initialize OV3660 camera
 * 4. Start MJPEG HTTP streaming server
 * 5. Start WebSocket sender to detection server
 */

#include "camera_stream_httpd.h"
#include "ws_sender.h"
#include "driver/gpio.h"
#include "esp_camera.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_psram.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include <string.h>
#include "esp_heap_caps.h"
#include "rom/gpio.h"

/* ========================== Config (sửa trong config.h) =================== */
#include "config.h"

static const char *TAG = "main";

/* ========================== RAM Monitor ==================================== */
static void log_memory_info(void) {
  size_t int_total = heap_caps_get_total_size(MALLOC_CAP_INTERNAL);
  size_t int_free  = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
  size_t int_min   = heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL);
  size_t spi_total = heap_caps_get_total_size(MALLOC_CAP_SPIRAM);
  size_t spi_free  = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
  size_t spi_min   = heap_caps_get_minimum_free_size(MALLOC_CAP_SPIRAM);

  ESP_LOGI(TAG, "========== BO NHO ESP32-CAM ==========");
  ESP_LOGI(TAG, "  Internal SRAM:");
  ESP_LOGI(TAG, "    Tong : %6zu bytes (%zu KB)", int_total, int_total / 1024);
  ESP_LOGI(TAG, "    Trong: %6zu bytes (%zu KB)", int_free,  int_free / 1024);
  ESP_LOGI(TAG, "    Min  : %6zu bytes (%zu KB)", int_min,   int_min / 1024);
  ESP_LOGI(TAG, "    Da dung: %zu KB / %zu KB (%.0f%%)",
           (int_total - int_free) / 1024, int_total / 1024,
           (float)(int_total - int_free) * 100.0f / int_total);
  ESP_LOGI(TAG, "  PSRAM:");
  ESP_LOGI(TAG, "    Tong : %7zu bytes (%zu KB)", spi_total, spi_total / 1024);
  ESP_LOGI(TAG, "    Trong: %7zu bytes (%zu KB)", spi_free,  spi_free / 1024);
  ESP_LOGI(TAG, "    Min  : %7zu bytes (%zu KB)", spi_min,   spi_min / 1024);
  ESP_LOGI(TAG, "    Da dung: %zu KB / %zu KB (%.0f%%)",
           (spi_total - spi_free) / 1024, spi_total / 1024,
           spi_total > 0 ? (float)(spi_total - spi_free) * 100.0f / spi_total : 0);
  ESP_LOGI(TAG, "=======================================");
}

static EventGroupHandle_t s_wifi_event_group;
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT BIT1
static int s_retry_num = 0;

/* ========================== Camera Pin Map (ESP32-CAM AI-Thinker) ========= */
/*
 * This is the standard AI-Thinker ESP32-CAM board pinout.
 * If you use a different board, adjust these pins accordingly.
 */
#define CAM_PIN_PWDN 32
#define CAM_PIN_RESET -1 // software reset
#define CAM_PIN_XCLK 0
#define CAM_PIN_SIOD 26
#define CAM_PIN_SIOC 27

#define CAM_PIN_D7 35
#define CAM_PIN_D6 34
#define CAM_PIN_D5 39
#define CAM_PIN_D4 36
#define CAM_PIN_D3 21
#define CAM_PIN_D2 19
#define CAM_PIN_D1 18
#define CAM_PIN_D0 5

#define CAM_PIN_VSYNC 25
#define CAM_PIN_HREF 23
#define CAM_PIN_PCLK 22

/* ========================== WiFi Event Handler ============================ */
static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data) {
  if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
    esp_wifi_connect();
  } else if (event_base == WIFI_EVENT &&
             event_id == WIFI_EVENT_STA_DISCONNECTED) {
    s_retry_num++;
    if (s_retry_num > WIFI_MAX_RETRY) {
      /* Đợi 5s rồi retry tiếp, không bao giờ bỏ cuộc */
      ESP_LOGW(TAG, "WiFi retry %d — waiting 5s before next attempt...", s_retry_num);
      vTaskDelay(pdMS_TO_TICKS(5000));
    } else {
      ESP_LOGI(TAG, "Retrying WiFi connection... (%d/%d)", s_retry_num,
               WIFI_MAX_RETRY);
    }
    esp_wifi_connect();
  } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
    ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
    ESP_LOGI(TAG, "  Open http://" IPSTR " in browser",
             IP2STR(&event->ip_info.ip));
    ESP_LOGI(TAG, "========================================");
    s_retry_num = 0;
    xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
  }
}

/* ========================== WiFi Init ===================================== */
static esp_err_t wifi_init_sta(void) {
  s_wifi_event_group = xEventGroupCreate();

  ESP_ERROR_CHECK(esp_netif_init());
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();

  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_wifi_init(&cfg));

  esp_event_handler_instance_t instance_any_id;
  esp_event_handler_instance_t instance_got_ip;
  ESP_ERROR_CHECK(esp_event_handler_instance_register(
      WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL,
      &instance_any_id));
  ESP_ERROR_CHECK(esp_event_handler_instance_register(
      IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL,
      &instance_got_ip));

  wifi_config_t wifi_config = {
      .sta =
          {
              .ssid = WIFI_SSID,
              .password = WIFI_PASS,
              .threshold.authmode = WIFI_AUTH_WPA2_PSK,
          },
  };

  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
  ESP_ERROR_CHECK(esp_wifi_start());

  /* Maximize TX Power (19.5dBm) to fix weak signal */
  ESP_ERROR_CHECK(esp_wifi_set_max_tx_power(78));

  /* Disable WiFi power save — critical for throughput! */
  ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));

  ESP_LOGI(TAG, "Connecting to WiFi SSID: %s ...", WIFI_SSID);

  /* Chờ cho đến khi WiFi kết nối thành công (không timeout) */
  EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
                                         WIFI_CONNECTED_BIT,
                                         pdFALSE, pdFALSE, portMAX_DELAY);

  if (bits & WIFI_CONNECTED_BIT) {
    ESP_LOGI(TAG, "WiFi connected to %s", WIFI_SSID);
    return ESP_OK;
  }
  return ESP_FAIL;  /* Không bao giờ đến đây */
}

/* ========================== I2C Bus Recovery ============================== */
/*
 * Sau khi WDT reset, bus I2C có thể bị kẹt (SDA held low bởi slave).
 * Toggle SCL 9 lần để slave nhả SDA, rồi tạo STOP condition.
 */
static void i2c_bus_recovery(void) {
  const int scl_pin = CAM_PIN_SIOC; /* GPIO 27 */
  const int sda_pin = CAM_PIN_SIOD; /* GPIO 26 */

  gpio_config_t io_conf = {
      .pin_bit_mask = (1ULL << scl_pin) | (1ULL << sda_pin),
      .mode = GPIO_MODE_INPUT_OUTPUT_OD,
      .pull_up_en = GPIO_PULLUP_ENABLE,
  };
  gpio_config(&io_conf);

  /* Toggle SCL 9 lần để slave nhả SDA */
  for (int i = 0; i < 9; i++) {
    gpio_set_level(scl_pin, 0);
    esp_rom_delay_us(5);
    gpio_set_level(scl_pin, 1);
    esp_rom_delay_us(5);
  }

  /* Tạo STOP condition: SDA low -> SCL high -> SDA high */
  gpio_set_level(sda_pin, 0);
  esp_rom_delay_us(5);
  gpio_set_level(scl_pin, 1);
  esp_rom_delay_us(5);
  gpio_set_level(sda_pin, 1);
  esp_rom_delay_us(5);

  /* Trả GPIO về input (esp_camera_init sẽ config lại) */
  gpio_config_t reset_conf = {
      .pin_bit_mask = (1ULL << scl_pin) | (1ULL << sda_pin),
      .mode = GPIO_MODE_INPUT,
      .pull_up_en = GPIO_PULLUP_ENABLE,
  };
  gpio_config(&reset_conf);

  ESP_LOGI(TAG, "I2C bus recovery done (SCL=%d, SDA=%d)", scl_pin, sda_pin);
}

/* ========================== Camera Init =================================== */
static esp_err_t camera_init(void) {
  /*
   * Power-cycle the camera module BEFORE esp_camera_init().
   * This stops VSYNC from toggling during GPIO ISR setup,
   * preventing the xQueueGenericSendFromISR assert crash.
   */
  gpio_config_t pwdn_conf = {
      .pin_bit_mask = 1ULL << CAM_PIN_PWDN,
      .mode = GPIO_MODE_OUTPUT,
  };
  gpio_config(&pwdn_conf);
  gpio_set_level(CAM_PIN_PWDN, 1); /* power DOWN */
  vTaskDelay(pdMS_TO_TICKS(200));   /* Giữ OFF lâu hơn để discharge hoàn toàn */
  gpio_set_level(CAM_PIN_PWDN, 0); /* power UP */
  vTaskDelay(pdMS_TO_TICKS(1000));  /* ĐỢI 1 GIÂY cho LDO + PLL + I2C slave ổn định */

  /* Giải phóng I2C bus bị kẹt (thường xảy ra sau WDT reset) */
  i2c_bus_recovery();

  camera_config_t config = {
      .pin_pwdn = CAM_PIN_PWDN,
      .pin_reset = CAM_PIN_RESET,
      .pin_xclk = CAM_PIN_XCLK,
      .pin_sccb_sda = CAM_PIN_SIOD,
      .pin_sccb_scl = CAM_PIN_SIOC,

      .pin_d7 = CAM_PIN_D7,
      .pin_d6 = CAM_PIN_D6,
      .pin_d5 = CAM_PIN_D5,
      .pin_d4 = CAM_PIN_D4,
      .pin_d3 = CAM_PIN_D3,
      .pin_d2 = CAM_PIN_D2,
      .pin_d1 = CAM_PIN_D1,
      .pin_d0 = CAM_PIN_D0,

      .pin_vsync = CAM_PIN_VSYNC,
      .pin_href = CAM_PIN_HREF,
      .pin_pclk = CAM_PIN_PCLK,

      /* BUỘC PHẢI KHÔI PHỤC LẠI 20MHz: 
       * Nếu để 10MHz, vi xử lý ảnh (ISP) của OV3660 sẽ bị sai lệch hệ số nhân xung nhịp (PLL),
       * dẫn đến hiện tượng cảm biến không thu được ánh sáng -> XẢ RA MÀN HÌNH ĐEN THUI (6KB)! */
      .xclk_freq_hz = 20000000,
      .ledc_timer = LEDC_TIMER_0,
      .ledc_channel = LEDC_CHANNEL_0,

      /* JPEG output for streaming */
      .pixel_format = PIXFORMAT_JPEG,

      /* VGA 640x480 — standard input size for YOLOv8 */
      .frame_size = FRAMESIZE_VGA, 
      .jpeg_quality = 12, // Giảm nén để tránh bệt màu/ám xanh khi thiếu sáng
      .fb_count = 3,
      .fb_location = CAMERA_FB_IN_PSRAM,
      .grab_mode = CAMERA_GRAB_LATEST,
  };

  /* If no PSRAM, fall back to smaller resolution */
  if (esp_psram_get_size() == 0) {
    ESP_LOGW(TAG, "No PSRAM detected — using VGA resolution");
    config.frame_size = FRAMESIZE_VGA;
    config.fb_count = 1;
    config.fb_location = CAMERA_FB_IN_DRAM;
  }

  /* ⚠️ OV3660 I2C slave cần thời gian ổn định sau power-up.
     Retry tối đa 5 lần, mỗi lần power-cycle lại camera. */
  ESP_LOGI(TAG, "Initializing camera...");
  
  vTaskDelay(pdMS_TO_TICKS(1500)); /* Chờ cho dòng điện ổn định */

  esp_err_t err = ESP_FAIL;
  const int MAX_CAM_RETRIES = 5;

  for (int attempt = 0; attempt < MAX_CAM_RETRIES; attempt++) {
    if (attempt > 0) {
      ESP_LOGW(TAG, "Camera init attempt %d/%d — power-cycling...", attempt + 1, MAX_CAM_RETRIES);

      /* Power-cycle camera hoàn toàn giữa mỗi lần retry */
      gpio_set_level(CAM_PIN_PWDN, 1);  /* OFF */
      vTaskDelay(pdMS_TO_TICKS(500));    /* Đợi discharge */
      gpio_set_level(CAM_PIN_PWDN, 0);  /* ON */
      vTaskDelay(pdMS_TO_TICKS(1000));   /* Đợi PLL + I2C slave sẵn sàng */

      /* Recovery I2C bus trước khi retry */
      i2c_bus_recovery();
      vTaskDelay(pdMS_TO_TICKS(500));
    }

    err = esp_camera_init(&config);
    if (err == ESP_OK) {
      if (attempt > 0) {
        ESP_LOGI(TAG, "Camera init succeeded on attempt %d", attempt + 1);
      }
      break;
    }

    ESP_LOGE(TAG, "Camera init attempt %d failed: 0x%x", attempt + 1, err);
  }

  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Camera init failed after %d attempts", MAX_CAM_RETRIES);
    return err;
  }

  /* Sensor tuning — tối ưu cho nhận diện người */
  sensor_t *s = esp_camera_sensor_get();
  if (s) {
    if (s->id.PID == OV3660_PID) {
      ESP_LOGI(TAG, "OV3660 detected — applying detection-optimized tuning");
      s->set_vflip(s, 1);

      /* === Chất lượng ảnh === */
      s->set_brightness(s, 0);    /* Trung tính để tránh lệch màu tổng thể */
      s->set_contrast(s, 0);      /* Tránh đẩy contrast quá tay gây ám màu */
      s->set_saturation(s, 1);    /* Tăng nhẹ màu để da/người tự nhiên hơn */
      s->set_sharpness(s, 1);     /* Giữ nét cho detection */

      /* === Auto Exposure (AEC) — tự động chỉnh sáng theo môi trường === */
      s->set_exposure_ctrl(s, 1); /* Bật AEC */
      s->set_aec2(s, 1);          /* Bật AEC DSP (advanced) */
      s->set_ae_level(s, 0);      /* AE level trung bình */

      /* === Auto White Balance (AWB) — màu chính xác mọi điều kiện === */
      s->set_whitebal(s, 1);      /* Bật AWB */
      s->set_awb_gain(s, 1);      /* Bật AWB gain */
      s->set_wb_mode(s, 0);       /* Auto WB mode */
      s->set_special_effect(s, 0);/* Không dùng hiệu ứng màu */

      /* === Auto Gain Control (AGC) — tự tăng gain khi thiếu sáng === */
      s->set_gain_ctrl(s, 1);     /* Bật AGC */
      s->set_agc_gain(s, 0);      /* AGC gain ceiling = thấp (giảm noise ban đêm) */

      /* === Khử nhiễu === */
      s->set_denoise(s, 1);       /* Bật denoise trên sensor (hardware) */
      s->set_bpc(s, 1);           /* Bật Bad Pixel Correction */
      s->set_wpc(s, 1);           /* Bật White Pixel Correction */

    } else {
      ESP_LOGW(TAG, "Camera PID=0x%04X (not OV3660), using defaults",
               s->id.PID);
    }
  }

  /* Warm up: discard first few potentially corrupted frames */
  ESP_LOGI(TAG, "Warming up camera (discarding initial frames)...");
  for (int i = 0; i < 5; i++) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb) {
      esp_camera_fb_return(fb);
    }
    vTaskDelay(pdMS_TO_TICKS(100));
  }

  ESP_LOGI(TAG, "Camera initialized successfully");
  return ESP_OK;
}

/* ========================== app_main ====================================== */
void app_main(void) {
  /* Tắt các Log rác (I-INFO) cực kỳ cồng kềnh của thư viện Camera để tăng tốc CPU và thông thoáng đường chuyền xả I2C */
  esp_log_level_set("sccb-ng", ESP_LOG_ERROR);
  esp_log_level_set("ov3660", ESP_LOG_WARN);
  esp_log_level_set("camera", ESP_LOG_INFO);

  ESP_LOGI(TAG, "====== ESP32-CAM OV3660 Stream ======");

  /* 1. NVS — required for WiFi */
  esp_err_t ret = nvs_flash_init();
  if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
      ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_ERROR_CHECK(nvs_flash_erase());
    ret = nvs_flash_init();
  }
  ESP_ERROR_CHECK(ret);

  /* 2. Khởi động Camera TRƯỚC TIÊN (Lúc này chip WiFi đang tắt hoàn toàn)
     Đây là giải pháp tuyệt vời để tránh sụt nguồn do 2 linh kiện cùng kéo Peak Current! */
  if (camera_init() != ESP_OK) {
    ESP_LOGE(TAG, "Camera failed — restarting in 5s");
    vTaskDelay(pdMS_TO_TICKS(5000));
    esp_restart();
  }

  /* 3. Khởi động WiFi SAU KHI Camera đã ổn định dòng điện */
  if (wifi_init_sta() != ESP_OK) {
    ESP_LOGE(TAG, "WiFi failed — restarting in 5s");
    vTaskDelay(pdMS_TO_TICKS(5000));
    esp_restart();
  }

  /* 4. HTTP streaming server (browser view) */
  // ESP_ERROR_CHECK(start_camera_stream_server()); // ĐÃ VÔ HIỆU HOÁ ĐỂ NHƯỜNG 100% CÔNG SUẤT ESP32 CHO PYTHON SERVER

  /* 5. WebSocket sender (person detection server) */
  ESP_LOGI(TAG, "Connecting to detection server: %s", WS_SERVER_URI);
  ws_sender_start(WS_SERVER_URI);

  /* 6. Log RAM usage */
  log_memory_info();

  ESP_LOGI(TAG, "System ready — streaming + detection active!");
}
