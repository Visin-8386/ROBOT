idf_component_register(
    SRCS "main.c"
         "distance_sensor_hcsr04.c"
         "distance_sensor_vl53l0x.c"
         "motor.c"
         "sensor.c"
         "servo.c"
         "mqtt_client_app.c"
    PRIV_REQUIRES driver
                  esp_wifi
                  esp_netif
                  esp_event
                  nvs_flash
                  mqtt
                  json
                  esp_timer
    INCLUDE_DIRS "."
)
