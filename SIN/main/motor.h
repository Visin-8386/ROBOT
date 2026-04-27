/**
 * Motor driver — TB6612 dual motor control
 */

#ifndef MOTOR_H
#define MOTOR_H

#include "esp_err.h"

esp_err_t motor_init(void);

void motor_forward(int speed);
void motor_forward_ramp(int target_speed);  /* Soft-start: tăng tốc từ từ */
void motor_backward(int speed);
void motor_turn_left(int speed);
void motor_turn_right(int speed);
void motor_stop(void);

/* Individual motor control */
void motor_set(int left_speed, int right_speed);

/* Get current state for logging */
const char* motor_get_state_str(void);

#endif /* MOTOR_H */
