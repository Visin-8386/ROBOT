#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Start the camera HTTP streaming server
 *        Serves MJPEG stream on /stream and a simple HTML page on /
 * @return ESP_OK on success
 */
esp_err_t start_camera_stream_server(void);

#ifdef __cplusplus
}
#endif
