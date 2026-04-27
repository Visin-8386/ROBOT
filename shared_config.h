/**
 * ================================================================
 *  CONFIG CHUNG — SỬA TẠI ĐÂY TRƯỚC KHI BUILD
 * ================================================================
 *
 *  File này chứa TẤT CẢ thông tin thay đổi mỗi lần chạy.
 *  Cả 2 project (station + SIN) đều include file này.
 *
 *  Sau khi sửa → build lại cả 2 project:
 *    cd D:\ROBOT\station && idf.py build flash -p COM3
 *    cd D:\ROBOT\SIN     && idf.py build flash -p COM4
 * ================================================================
 */

#ifndef SHARED_CONFIG_H
#define SHARED_CONFIG_H

/* ============ WiFi ============ */
#define WIFI_SSID "cam"
#define WIFI_PASS "33333333"
#define WIFI_MAX_RETRY 10

/* ============ Server IP (máy PC chạy Docker) ============ */
#define SERVER_IP "192.168.137.1"

/* ============ Các URI tự tạo từ SERVER_IP ============ */
#define WS_SERVER_URI "ws://" SERVER_IP ":8765"
#define MQTT_BROKER_URI "mqtt://" SERVER_IP ":1883"

#endif /* SHARED_CONFIG_H */
