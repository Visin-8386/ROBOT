idf_component_register(
    SRCS "main.c" "camera_stream_httpd.c" "ws_sender.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES esp_wifi nvs_flash esp_http_server esp_psram esp_timer
)
