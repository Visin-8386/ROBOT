/**
 * Servo Control — Pan servo tại chân 46 (camera servo)
 * 
 * Điều khiển servo xoay qua PWM LEDC.
 * - Servo center: 1500 us (90°)
 * - Servo left:   2000 us (~135°)
 * - Servo right:  1000 us (~45°)
 */

#ifndef ROBOT_SERVO_H
#define ROBOT_SERVO_H

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

/**
 * Khởi tạo servo — setup GPIO + PWM LEDC
 * @return ESP_OK nếu thành công
 */
esp_err_t servo_init(void);

/**
 * Di chuyển servo đến góc cụ thể (smooth ramp)
 * @param target_us: microsecond (1000~2000 range)
 * @param speed_us_per_ms: tốc độ movement (mặc định 10 us/ms)
 */
void servo_move_smooth(uint16_t target_us, float speed_us_per_ms);

/**
 * Di chuyển servo ngay lập tức (jump)
 * @param target_us: microsecond
 */
void servo_set_pwm(uint16_t target_us);

/**
 * Lấy vị trí servo hiện tại (us)
 * @return microsecond hiện tại
 */
uint16_t servo_get_current_pos(void);

/**
 * Kiểm tra xem servo có đang di chuyển không
 * @return true nếu còn di chuyển, false nếu tới đích
 */
bool servo_is_moving(void);

/**
 * Reset servo về center (90°) — đợi tới khi ổn định
 */
void servo_reset_to_center(void);

/**
 * Set callback para khi servo tới đích
 * @param callback: function pointer hoặc NULL
 */
typedef void (*servo_callback_t)(void);
void servo_set_reached_callback(servo_callback_t cb);

#endif /* ROBOT_SERVO_H */
