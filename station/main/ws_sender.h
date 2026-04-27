#pragma once

#include "esp_err.h"

/**
 * Start WebSocket sender task.
 * Captures JPEG frames and sends them to the Python detection server.
 *
 * @param server_uri  WebSocket URI, e.g. "ws://192.168.1.64:8765"
 * @return ESP_OK on success
 */
esp_err_t ws_sender_start(const char *server_uri);
