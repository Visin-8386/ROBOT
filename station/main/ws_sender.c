/**
 * Async TCP Frame Sender — sends JPEG frames to detection server
 * ----------------------------------------------------------------
 * Key optimization: ESP32 sends frames WITHOUT waiting for the server
 * response. It checks for responses using non-blocking recv between
 * sends. This decouples send FPS from YOLO detection latency.
 *
 * Protocol:
 *   ESP32 → Server:  [4-byte big-endian len][JPEG bytes]
 *   Server → ESP32:  [4-byte big-endian len][JSON bytes]  (async)
 */

#include "ws_sender.h"
#include "esp_camera.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/netdb.h"
#include "lwip/sockets.h"
#include <string.h>

static const char *TAG = "tcp_send";

/* Config */
static char s_host[64];
static uint16_t s_port;

/* Performance tracking */
static uint32_t frame_count = 0;
static uint64_t total_bytes = 0;
static int64_t perf_start = 0;
static uint32_t stat_socket_busy = 0;
static uint32_t stat_capture_fail = 0;
static uint32_t stat_invalid_frame = 0;
static uint32_t stat_send_fail = 0;
static uint32_t stat_resp_count = 0;
static uint64_t stat_capture_us_sum = 0;
static uint64_t stat_send_us_sum = 0;
static uint32_t stat_send_us_max = 0;
static uint32_t stat_busy_streak = 0;

/* Busy handling tuning:
 * - Keep short backoff to avoid hogging CPU.
 * - Reconnect only after a long continuous stall.
 */
#define BUSY_BACKOFF_MS 10
#define BUSY_RECONNECT_STREAK 3000  /* ~30s at 10ms backoff */

/* ---------- Helpers ------------------------------------------------------- */

/** Send exactly `len` bytes. Returns 0 on success, -1 on error. */
static int send_all(int sock, const void *buf, size_t len) {
  const uint8_t *p = (const uint8_t *)buf;
  while (len > 0) {
    int n = send(sock, p, len, 0);
    if (n <= 0) return -1;
    p += n;
    len -= n;
  }
  return 0;
}

/** Try to read any pending server responses (non-blocking). */
static uint32_t drain_responses(int sock) {
  uint32_t responses = 0;
  /* Use select() with zero timeout → non-blocking check */
  fd_set rfds;
  struct timeval tv = {0, 0}; /* zero timeout = poll */

  while (true) {
    FD_ZERO(&rfds);
    FD_SET(sock, &rfds);
    int ready = select(sock + 1, &rfds, NULL, NULL, &tv);
    if (ready <= 0) break; /* nothing to read */

    /* Read 4-byte header */
    uint32_t resp_len_net;
    int n = recv(sock, &resp_len_net, 4, 0);
    if (n <= 0) break;
    if (n < 4) break; /* partial header — unlikely with TCP */

    uint32_t resp_len = ntohl(resp_len_net);
    if (resp_len > 1024) break;

    /* Read JSON body */
    char buf[1025];
    uint32_t got = 0;
    while (got < resp_len) {
      n = recv(sock, buf + got, resp_len - got, 0);
      if (n <= 0) break;
      got += n;
    }
    if (got < resp_len) break;

    buf[resp_len] = '\0';
    responses++;
    ESP_LOGI(TAG, "Det: %s", buf);
  }

  return responses;
}

/** Connect TCP to server. Returns socket fd or -1. */
static int tcp_connect(void) {
  struct sockaddr_in dest;
  memset(&dest, 0, sizeof(dest));
  dest.sin_family = AF_INET;
  dest.sin_port = htons(s_port);
  inet_aton(s_host, &dest.sin_addr);

  int sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (sock < 0) {
    ESP_LOGE(TAG, "socket() failed: errno %d", errno);
    return -1;
  }

  /* TCP_NODELAY for low latency */
  int yes = 1;
  setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes));

  /* Large send buffer — 128KB for smoother streaming */
  int sndbuf = 131072;
  setsockopt(sock, SOL_SOCKET, SO_SNDBUF, &sndbuf, sizeof(sndbuf));

  /* Send timeout 10s (for blocking send) */
  struct timeval tv = {.tv_sec = 10, .tv_usec = 0};
  setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

  /* Keepalive helps detect dead/stalled links sooner. */
  int keepalive = 1;
  setsockopt(sock, SOL_SOCKET, SO_KEEPALIVE, &keepalive, sizeof(keepalive));

  /* Connect with a timeout (use default blocking connect) */
  if (connect(sock, (struct sockaddr *)&dest, sizeof(dest)) != 0) {
    ESP_LOGE(TAG, "connect() to %s:%d failed: errno %d", s_host, s_port, errno);
    close(sock);
    return -1;
  }

  ESP_LOGI(TAG, "=== Connected to %s:%d ===", s_host, s_port);
  return sock;
}

/* ---------- Sender task --------------------------------------------------- */
static void tcp_sender_task(void *arg) {
  ESP_LOGI(TAG, "Sender task started (async mode)");

  while (true) {
    /* Connect (retry every 3s) */
    int sock = tcp_connect();
    if (sock < 0) {
      vTaskDelay(pdMS_TO_TICKS(3000));
      continue;
    }

    /* Reset perf counters */
    frame_count = 0;
    total_bytes = 0;
    perf_start = esp_timer_get_time();
    stat_socket_busy = 0;
    stat_capture_fail = 0;
    stat_invalid_frame = 0;
    stat_send_fail = 0;
    stat_resp_count = 0;
    stat_capture_us_sum = 0;
    stat_send_us_sum = 0;
    stat_send_us_max = 0;
    stat_busy_streak = 0;
    uint32_t sent_since_connect = 0;
    /* Stream loop — send as fast as possible */
    while (true) {
      /* Check for any pending detection results (non-blocking) */
      stat_resp_count += drain_responses(sock);

      /* 
       * BUFFER BLOAT PREVENTION (Drop Frame / UDP-like behavior):
       * Check if TCP socket buffer is full BEFORE grabbing a frame.
       * If it's full, we skip capturing a frame and sleep a bit.
       * This ensures the next frame we send is absolutely fresh!
       */
      fd_set wfds;
      struct timeval tv_write = {0, 0}; /* no block, just check if writable */
      FD_ZERO(&wfds);
      FD_SET(sock, &wfds);

      int wf_ready = select(sock + 1, NULL, &wfds, NULL, &tv_write);
      if (wf_ready <= 0) {
        stat_socket_busy++;
        stat_busy_streak++;
        /* Socket buffer is full -> Network is slow -> Back off!
         * Keep a short backoff to reduce burst-pause jitter in FPS logs. */
        if (sent_since_connect > 0 && stat_busy_streak >= BUSY_RECONNECT_STREAK) {
          ESP_LOGW(TAG, "Socket blocked too long after active traffic (busy_streak=%lu) — reconnecting", (unsigned long)stat_busy_streak);
          break;
        }
        vTaskDelay(pdMS_TO_TICKS(BUSY_BACKOFF_MS));
        continue;
      }
      stat_busy_streak = 0;

      /* Capability is granted, capture a fresh frame */
      int64_t t_cap0 = esp_timer_get_time();
      camera_fb_t *fb = esp_camera_fb_get();
      uint32_t cap_us = (uint32_t)(esp_timer_get_time() - t_cap0);
      if (!fb) {
        stat_capture_fail++;
        ESP_LOGE(TAG, "Camera capture failed");
        vTaskDelay(pdMS_TO_TICKS(50));
        continue;
      }

      if (fb->format != PIXFORMAT_JPEG || fb->len < 100) {
        stat_invalid_frame++;
        esp_camera_fb_return(fb);
        continue;
      }

      /* Send: [4-byte len][JPEG data] — don't wait for response! */
      int64_t t_send0 = esp_timer_get_time();
      uint32_t net_len = htonl((uint32_t)fb->len);
      int err = send_all(sock, &net_len, 4);
      if (err == 0)
        err = send_all(sock, fb->buf, fb->len);
      uint32_t send_us = (uint32_t)(esp_timer_get_time() - t_send0);

      size_t flen = fb->len;
      esp_camera_fb_return(fb);

      if (err != 0) {
        stat_send_fail++;
        ESP_LOGW(TAG, "Send failed — reconnecting");
        break;
      }

      frame_count++;
      sent_since_connect++;
      total_bytes += flen;
      stat_capture_us_sum += cap_us;
      stat_send_us_sum += send_us;
      if (send_us > stat_send_us_max) stat_send_us_max = send_us;

      /* Log performance every 5 seconds */
      int64_t elapsed = esp_timer_get_time() - perf_start;
      if (elapsed >= 5000000 && frame_count > 0) {
        float fps = (float)frame_count / ((float)elapsed / 1e6f);
        float avg_kb = (float)total_bytes / frame_count / 1024.0f;
        float kbps = (float)total_bytes * 8.0f / ((float)elapsed / 1e6f) / 1024.0f;
        float avg_cap_ms = (float)stat_capture_us_sum / frame_count / 1000.0f;
        float avg_send_ms = (float)stat_send_us_sum / frame_count / 1000.0f;
        float max_send_ms = (float)stat_send_us_max / 1000.0f;

        ESP_LOGI(TAG,
                 "TX | FPS: %.1f | Avg: %.1fKB | Speed: %.0f kbps | Frames: %lu | cap:%.2fms | send:%.2f/%.2fms | busy:%lu streak:%lu fail(c/s/i):%lu/%lu/%lu | resp:%lu",
                 fps, avg_kb, kbps, (unsigned long)frame_count,
                 avg_cap_ms, avg_send_ms, max_send_ms,
                 (unsigned long)stat_socket_busy,
                 (unsigned long)stat_busy_streak,
                 (unsigned long)stat_capture_fail,
                 (unsigned long)stat_send_fail,
                 (unsigned long)stat_invalid_frame,
                 (unsigned long)stat_resp_count);

        frame_count = 0;
        total_bytes = 0;
        perf_start = esp_timer_get_time();
        stat_socket_busy = 0;
        stat_capture_fail = 0;
        stat_invalid_frame = 0;
        stat_send_fail = 0;
        stat_resp_count = 0;
        stat_capture_us_sum = 0;
        stat_send_us_sum = 0;
        stat_send_us_max = 0;
        stat_busy_streak = 0;
      }

      /* Yield to let WiFi task run and avoid brownout */
      vTaskDelay(pdMS_TO_TICKS(1));
    }

    close(sock);
    ESP_LOGW(TAG, "Disconnected, retrying in 2s...");
    vTaskDelay(pdMS_TO_TICKS(2000));
  }
}

/* ---------- Public API ---------------------------------------------------- */
esp_err_t ws_sender_start(const char *server_uri) {
  const char *p = server_uri;
  if (strncmp(p, "ws://", 5) == 0) p += 5;
  else if (strncmp(p, "tcp://", 6) == 0) p += 6;

  const char *colon = strchr(p, ':');
  if (colon) {
    size_t hlen = colon - p;
    if (hlen >= sizeof(s_host)) hlen = sizeof(s_host) - 1;
    memcpy(s_host, p, hlen);
    s_host[hlen] = '\0';
    s_port = (uint16_t)atoi(colon + 1);
  } else {
    strncpy(s_host, p, sizeof(s_host) - 1);
    s_port = 8765;
  }

  ESP_LOGI(TAG, "Will connect to %s:%d (async mode)", s_host, s_port);
  xTaskCreatePinnedToCore(tcp_sender_task, "tcp_send", 8192, NULL, 5, NULL, 1);
  return ESP_OK;
}
