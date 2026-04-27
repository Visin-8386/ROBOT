/**
 * Sensor facade: distance backend + PIR.
 */

#ifndef SENSOR_H
#define SENSOR_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

typedef enum {
    SENSOR_DISTANCE_STATUS_NOT_SAMPLED = 0,
    SENSOR_DISTANCE_STATUS_OK,
    SENSOR_DISTANCE_STATUS_NO_TARGET,
    SENSOR_DISTANCE_STATUS_TIMEOUT,
    SENSOR_DISTANCE_STATUS_ERROR,
    SENSOR_DISTANCE_STATUS_NOT_READY,
} sensor_distance_status_t;

typedef struct {
    uint16_t distance_mm;
    sensor_distance_status_t status;
} sensor_distance_sample_t;

esp_err_t sensor_init(void);

/**
 * Returns a normalized distance in mm.
 * Returns 0 for NO_TARGET, TIMEOUT, ERROR, and NOT_READY.
 */
uint16_t sensor_get_distance_mm(void);

sensor_distance_sample_t sensor_get_last_distance_sample(void);

bool sensor_pir_detected(void);

#endif /* SENSOR_H */
