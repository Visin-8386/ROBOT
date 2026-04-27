/**
 * MQTT Client — WiFi connect + MQTT subscribe + JSON parse
 */

#include "mqtt_client_app.h"
#include "config.h"

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "mqtt_client.h"
#include "nvs_flash.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "lwip/sockets.h"
#include "lwip/inet.h"
#include "cJSON.h"
#include <string.h>
#include <stdlib.h>

static const char *TAG = "mqtt_app";

/* WiFi */
static EventGroupHandle_t s_wifi_event_group;
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1
static int s_retry_num = 0;

/* MQTT data */
static person_data_t s_person = {0};
static portMUX_TYPE  s_data_lock = portMUX_INITIALIZER_UNLOCKED;

/* Command from web dashboard */
static robot_command_t s_command = {.action = CMD_NONE};
static portMUX_TYPE    s_cmd_lock = portMUX_INITIALIZER_UNLOCKED;

/* Global MQTT client handle for publishing */
static esp_mqtt_client_handle_t s_mqtt_client = NULL;

static void mqtt_tcp_preflight(void) {
    const char *uri = MQTT_BROKER_URI;
    const char *prefix = "mqtt://";
    size_t prefix_len = strlen(prefix);

    if (strncmp(uri, prefix, prefix_len) != 0) {
        ESP_LOGW(TAG, "Preflight skip: unsupported URI format: %s", uri);
        return;
    }

    const char *host_begin = uri + prefix_len;
    const char *host_end = host_begin;
    while (*host_end && *host_end != ':' && *host_end != '/') {
        host_end++;
    }

    if (host_end == host_begin) {
        ESP_LOGW(TAG, "Preflight skip: empty host in URI: %s", uri);
        return;
    }

    char host[64] = {0};
    size_t host_len = (size_t)(host_end - host_begin);
    if (host_len >= sizeof(host)) {
        ESP_LOGW(TAG, "Preflight skip: host too long in URI: %s", uri);
        return;
    }
    memcpy(host, host_begin, host_len);

    int port = 1883;
    if (*host_end == ':') {
        const char *port_begin = host_end + 1;
        char *port_end = NULL;
        long parsed = strtol(port_begin, &port_end, 10);
        if (parsed > 0 && parsed <= 65535) {
            port = (int)parsed;
        }
    }

    int sock = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGW(TAG, "MQTT preflight: socket create failed (errno=%d)", errno);
        return;
    }

    struct timeval tv = {
        .tv_sec = 3,
        .tv_usec = 0,
    };
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    struct sockaddr_in dest = {0};
    dest.sin_family = AF_INET;
    dest.sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, host, &dest.sin_addr) != 1) {
        ESP_LOGW(TAG, "MQTT preflight: host is not IPv4 literal (%s), skip direct TCP probe", host);
        close(sock);
        return;
    }

    int rc = connect(sock, (struct sockaddr *)&dest, sizeof(dest));
    if (rc == 0) {
        ESP_LOGI(TAG, "MQTT preflight OK: TCP %s:%d reachable", host, port);
    } else {
        ESP_LOGW(TAG, "MQTT preflight FAIL: TCP %s:%d unreachable (errno=%d: %s)",
                 host, port, errno, strerror(errno));
    }

    close(sock);
}

/* ========================== WiFi ========================== */

static void wifi_event_handler(void *arg, esp_event_base_t base,
                               int32_t id, void *data) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_retry_num++;
        if (s_retry_num > WIFI_MAX_RETRY) {
            /* Không block event loop task trong callback WiFi. */
            ESP_LOGW(TAG, "WiFi retry %d — reconnecting...", s_retry_num);
        } else {
            ESP_LOGI(TAG, "WiFi retry %d/%d", s_retry_num, WIFI_MAX_RETRY);
        }
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "WiFi connected — IP: " IPSTR, IP2STR(&event->ip_info.ip));
        s_retry_num = 0;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

static esp_err_t wifi_init(void) {
    /* NVS */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ret = nvs_flash_erase();
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "nvs_flash_erase failed: %s", esp_err_to_name(ret));
            return ret;
        }
        ret = nvs_flash_init();
    }
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "nvs_flash_init failed: %s", esp_err_to_name(ret));
        return ret;
    }

    s_wifi_event_group = xEventGroupCreate();
    if (!s_wifi_event_group) {
        ESP_LOGE(TAG, "xEventGroupCreate failed");
        return ESP_ERR_NO_MEM;
    }

    ret = esp_netif_init();
    if (ret != ESP_OK && ret != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "esp_netif_init failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = esp_event_loop_create_default();
    if (ret != ESP_OK && ret != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "esp_event_loop_create_default failed: %s", esp_err_to_name(ret));
        return ret;
    }

    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ret = esp_wifi_init(&cfg);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "esp_wifi_init failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "register WIFI_EVENT handler failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, NULL);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "register IP_EVENT handler failed: %s", esp_err_to_name(ret));
        return ret;
    }

    wifi_config_t wifi_config = {
        .sta = {
            .ssid     = WIFI_SSID,
            .password = WIFI_PASS,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
        },
    };
    ret = esp_wifi_set_mode(WIFI_MODE_STA);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "esp_wifi_set_mode failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = esp_wifi_set_config(WIFI_IF_STA, &wifi_config);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "esp_wifi_set_config failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = esp_wifi_start();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "esp_wifi_start failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = esp_wifi_set_ps(WIFI_PS_NONE);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "esp_wifi_set_ps failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ESP_LOGI(TAG, "Connecting to WiFi: %s ...", WIFI_SSID);

    /* Chờ cho đến khi WiFi kết nối thành công (không timeout) */
    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
        WIFI_CONNECTED_BIT, pdFALSE, pdFALSE, portMAX_DELAY);

    if (bits & WIFI_CONNECTED_BIT) return ESP_OK;
    return ESP_FAIL;  /* Không bao giờ đến đây */
}

/* ========================== MQTT ========================== */

static void parse_person_json(const char *json_str, int len) {
    cJSON *root = cJSON_ParseWithLength(json_str, len);
    if (!root) return;

    person_data_t p = {0};

    cJSON *det = cJSON_GetObjectItem(root, "detected");
    if (det) p.detected = cJSON_IsTrue(det);

    cJSON *x = cJSON_GetObjectItem(root, "x");
    if (x) p.x = x->valueint;

    cJSON *y = cJSON_GetObjectItem(root, "y");
    if (y) p.y = y->valueint;

    cJSON *pan = cJSON_GetObjectItem(root, "pan");
    if (pan) p.pan = (float)pan->valuedouble;

    cJSON *tilt = cJSON_GetObjectItem(root, "tilt");
    if (tilt) p.tilt = (float)tilt->valuedouble;

    cJSON *area_pct = cJSON_GetObjectItem(root, "area_pct");
    if (area_pct) p.area_pct = (float)area_pct->valuedouble;

    cJSON *cam_off = cJSON_GetObjectItem(root, "camera_offline");
    if (cam_off) p.camera_offline = cJSON_IsTrue(cam_off);

    cJSON *ts = cJSON_GetObjectItem(root, "ts");
    if (ts) p.timestamp = (int64_t)ts->valuedouble;

    p.received = esp_timer_get_time() / 1000;  /* ms */

    /* Thread-safe update */
    portENTER_CRITICAL(&s_data_lock);
    s_person = p;
    portEXIT_CRITICAL(&s_data_lock);

    cJSON_Delete(root);
}

static void parse_command_json(const char *json_str, int len) {
    cJSON *root = cJSON_ParseWithLength(json_str, len);
    if (!root) return;

    robot_command_t cmd = {.action = CMD_NONE};

    cJSON *action = cJSON_GetObjectItem(root, "action");
    if (action && cJSON_IsString(action)) {
        const char *a = action->valuestring;
        if      (strcmp(a, "forward")  == 0) cmd.action = CMD_FORWARD;
        else if (strcmp(a, "backward") == 0) cmd.action = CMD_BACKWARD;
        else if (strcmp(a, "left")     == 0) cmd.action = CMD_LEFT;
        else if (strcmp(a, "right")    == 0) cmd.action = CMD_RIGHT;
        else if (strcmp(a, "stop")     == 0) cmd.action = CMD_STOP;
        else if (strcmp(a, "patrol")   == 0) cmd.action = CMD_PATROL;
        else if (strcmp(a, "chase")    == 0) cmd.action = CMD_CHASE;
        else if (strcmp(a, "monitor")  == 0) cmd.action = CMD_MONITOR;
        else if (strcmp(a, "servo_left") == 0) cmd.action = CMD_SERVO_LEFT;
        else if (strcmp(a, "servo_right") == 0) cmd.action = CMD_SERVO_RIGHT;
        else if (strcmp(a, "servo_center") == 0) cmd.action = CMD_SERVO_CENTER;

        ESP_LOGI(TAG, "MQTT Action parsed: '%s' -> action_id: %d", a, cmd.action);
    } else {
        ESP_LOGW(TAG, "MQTT Command missing 'action' field or not a string");
    }

    cmd.received = esp_timer_get_time() / 1000;

    portENTER_CRITICAL(&s_cmd_lock);
    s_command = cmd;
    portEXIT_CRITICAL(&s_cmd_lock);
    cJSON_Delete(root);
}

static void mqtt_event_handler(void *arg, esp_event_base_t base,
                               int32_t event_id, void *event_data) {
    esp_mqtt_event_handle_t event = event_data;

    switch ((esp_mqtt_event_id_t)event_id) {
    case MQTT_EVENT_CONNECTED:
        ESP_LOGI(TAG, "MQTT connected — subscribing topics");
        /* Dùng QoS 0 cho cà 2 topic để tránh bị Broker xếp hàng (Queue) gây lag lệnh */
        esp_mqtt_client_subscribe(event->client, MQTT_TOPIC, 0);
        esp_mqtt_client_subscribe(event->client, MQTT_COMMAND_TOPIC, 0);
        break;

    case MQTT_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "MQTT disconnected, reconnecting...");
        break;

    case MQTT_EVENT_DATA:
        if (event->data_len > 0 && event->topic_len > 0) {
            if (strncmp(event->topic, MQTT_COMMAND_TOPIC, event->topic_len) == 0) {
                parse_command_json(event->data, event->data_len);
            } else {
                parse_person_json(event->data, event->data_len);
            }
        }
        break;

    case MQTT_EVENT_ERROR:
        ESP_LOGE(TAG, "MQTT error event");
        if (event->error_handle) {
            ESP_LOGE(TAG, "error_type=%d, connect_return_code=0x%x",
                     event->error_handle->error_type,
                     event->error_handle->connect_return_code);
            ESP_LOGE(TAG, "esp_tls_last_esp_err=0x%x, tls_stack_err=0x%x, sock_errno=%d (%s)",
                     event->error_handle->esp_tls_last_esp_err,
                     event->error_handle->esp_tls_stack_err,
                     event->error_handle->esp_transport_sock_errno,
                     strerror(event->error_handle->esp_transport_sock_errno));
        }
        break;

    default:
        break;
    }
}

/* ========================== Public API ========================== */

esp_err_t mqtt_app_start(void) {
    /* 1. WiFi */
    esp_err_t err = wifi_init();
    if (err != ESP_OK) return err;

    /* Check raw TCP reachability before MQTT connect loop. */
    mqtt_tcp_preflight();

    /* 2. MQTT */
    esp_mqtt_client_config_t mqtt_cfg = {
        .broker = { .address = { .uri = MQTT_BROKER_URI } },
        .session = { .keepalive = 30 },           /* 30s keepalive (default 10s) */
        .network = {
            .timeout_ms = 10000,
            .reconnect_timeout_ms = 3000,
        },
    };

    if (strlen(MQTT_USERNAME) > 0) {
        mqtt_cfg.credentials.username = MQTT_USERNAME;
        mqtt_cfg.credentials.authentication.password = MQTT_PASSWORD;
        ESP_LOGI(TAG, "MQTT auth enabled for user '%s'", MQTT_USERNAME);
    } else {
        ESP_LOGW(TAG, "MQTT auth disabled (empty username)");
    }

    esp_mqtt_client_handle_t client = esp_mqtt_client_init(&mqtt_cfg);
    if (!client) {
        ESP_LOGE(TAG, "esp_mqtt_client_init failed");
        return ESP_FAIL;
    }

    s_mqtt_client = client;  /* store globally for publishing */
    esp_mqtt_client_register_event(client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL);
    err = esp_mqtt_client_start(client);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_mqtt_client_start failed: %s", esp_err_to_name(err));
        return err;
    }

    ESP_LOGI(TAG, "MQTT client started → broker: %s", MQTT_BROKER_URI);
    return ESP_OK;
}

bool mqtt_get_person_data(person_data_t *out) {
    portENTER_CRITICAL(&s_data_lock);
    *out = s_person;
    portEXIT_CRITICAL(&s_data_lock);
    return out->received > 0;
}

bool mqtt_get_command(robot_command_t *out) {
    portENTER_CRITICAL(&s_cmd_lock);
    *out = s_command;
    s_command.action = CMD_NONE;  /* Clear after read (one-shot) */
    portEXIT_CRITICAL(&s_cmd_lock);
    return out->action != CMD_NONE;
}

void mqtt_publish_alert(const char *type, const char *detail,
                        uint16_t distance_mm, bool pir) {
    if (!s_mqtt_client) return;

    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", type);
    cJSON_AddStringToObject(root, "detail", detail);
    cJSON_AddNumberToObject(root, "distance_mm", distance_mm);
    cJSON_AddBoolToObject(root, "pir", pir);
    cJSON_AddNumberToObject(root, "ts", (double)(esp_timer_get_time() / 1000));

    char *json_str = cJSON_PrintUnformatted(root);
    if (json_str) {
        esp_mqtt_client_publish(s_mqtt_client, MQTT_ALERT_TOPIC, json_str, 0, 1, 0);
        free(json_str);
    }
    cJSON_Delete(root);
}

void mqtt_publish_status(const char *state, const char *detail,
                        uint16_t distance_mm, bool pir) {
    if (!s_mqtt_client) return;

    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", "status");
    cJSON_AddStringToObject(root, "state", state ? state : "UNKNOWN");
    cJSON_AddStringToObject(root, "detail", detail ? detail : "");
    cJSON_AddNumberToObject(root, "distance_mm", distance_mm);
    cJSON_AddBoolToObject(root, "pir", pir);
    cJSON_AddNumberToObject(root, "ts", (double)(esp_timer_get_time() / 1000));

    char *json_str = cJSON_PrintUnformatted(root);
    if (json_str) {
        esp_mqtt_client_publish(s_mqtt_client, MQTT_ALERT_TOPIC, json_str, 0, 1, 0);
        free(json_str);
    }
    cJSON_Delete(root);
}
