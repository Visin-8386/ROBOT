#ifndef DISTANCE_SENSOR_DRIVER_H
#define DISTANCE_SENSOR_DRIVER_H

#include "sensor.h"

typedef struct {
    const char *name;
    esp_err_t (*init)(void);
    sensor_distance_sample_t (*read)(void);
} distance_sensor_driver_t;

extern const distance_sensor_driver_t g_distance_sensor_vl53l0x_driver;
extern const distance_sensor_driver_t g_distance_sensor_hcsr04_driver;

#endif /* DISTANCE_SENSOR_DRIVER_H */
