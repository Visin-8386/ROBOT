/**
 * MQTT Client — WiFi + MQTT subscribe person position + web commands
 */

#ifndef MQTT_CLIENT_APP_H
#define MQTT_CLIENT_APP_H

#include "esp_err.h"
#include <stdbool.h>

/* Data received from detection server */
typedef struct {
    bool  detected;
    int   x;
    int   y;
    float pan;
    float tilt;
    float area_pct;       /* % diện tích bbox / frame (0-100), dùng phân biệt người vs vật cản */
    bool  camera_offline;
    int64_t timestamp;
    int64_t received;
} person_data_t;

/* Commands from web dashboard */
typedef enum {
    CMD_NONE = 0,
    CMD_FORWARD,
    CMD_BACKWARD,
    CMD_LEFT,
    CMD_RIGHT,
    CMD_STOP,
    CMD_PATROL,
    CMD_CHASE,
    CMD_MONITOR,
    CMD_SERVO_LEFT,
    CMD_SERVO_RIGHT,
    CMD_SERVO_CENTER,
} command_action_t;

typedef struct {
    command_action_t action;
    int64_t received;
} robot_command_t;

esp_err_t mqtt_app_start(void);
bool mqtt_get_person_data(person_data_t *out);
bool mqtt_get_command(robot_command_t *out);

/**
 * Publish sensor alert to MQTT topic "robot/alert".
 * @param type   "pir", "distance", "camera", "status"
 * @param detail free-form detail string (JSON-safe)
 * @param distance_mm ToF reading (0 if N/A)
 * @param pir        PIR state
 */
void mqtt_publish_alert(const char *type, const char *detail,
                        uint16_t distance_mm, bool pir);

/**
 * Publish robot mode/status to MQTT topic "robot/alert".
 * @param state  "MONITOR", "PATROL", "CHASE", "MANUAL"
 * @param detail free-form detail string
 * @param distance_mm ToF reading (0 if N/A)
 * @param pir        PIR state
 */
void mqtt_publish_status(const char *state, const char *detail,
                         uint16_t distance_mm, bool pir);

#endif /* MQTT_CLIENT_APP_H */
