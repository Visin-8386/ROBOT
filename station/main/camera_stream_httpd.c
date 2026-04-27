/**
 * ESP32-CAM OV3660 MJPEG Streaming Server + Performance Monitor
 * ---------------------------------------------------------------
 * GET /        -> HTML page with embedded <img> pointing to /stream
 * GET /stream  -> multipart/x-mixed-replace MJPEG stream
 *
 * Uses blocking socket mode for reliable high-FPS streaming.
 */

#include "camera_stream_httpd.h"
#include "esp_camera.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <fcntl.h>
#include <string.h>
#include <sys/socket.h>

static const char *TAG = "cam_httpd";

/* ---------- MJPEG boundary ------------------------------------------------ */
#define PART_BOUNDARY "123456789000000000000987654321"
static const char *_STREAM_CONTENT_TYPE =
    "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char *_STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char *_STREAM_PART =
    "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

/* ---------- HTML page ----------------------------------------------------- */
static const char index_html[] =
    "<!DOCTYPE html>"
    "<html><head>"
    "<meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>ESP32-CAM OV3660 Stream</title>"
    "<style>"
    "*{margin:0;padding:0;box-sizing:border-box}"
    "body{background:#0f0f0f;color:#e0e0e0;font-family:'Segoe UI',sans-serif;"
    "display:flex;flex-direction:column;align-items:center;min-height:100vh;"
    "padding:20px}"
    "h1{margin:18px 0 "
    "6px;font-size:1.6rem;background:linear-gradient(90deg,#00d2ff,#3a7bd5);"
    "-webkit-background-clip:text;-webkit-text-fill-color:transparent}"
    "p.sub{font-size:.85rem;color:#888;margin-bottom:16px}"
    ".card{background:#1a1a2e;border-radius:16px;padding:8px;box-shadow:0 8px "
    "32px rgba(0,0,0,.45);"
    "max-width:820px;width:100%}"
    "img{width:100%;border-radius:12px;display:block}"
    ".info{display:flex;justify-content:space-between;padding:10px 6px "
    "4px;font-size:.78rem;color:#666}"
    "</style></head><body>"
    "<h1>&#128247; ESP32-CAM Live</h1>"
    "<p class='sub'>OV3660 &bull; XGA 1024x768 &bull; MJPEG</p>"
    "<div class='card'>"
    "<img id='stream' src='/stream' alt='Camera Stream'>"
    "<div class='info'><span>XGA 1024&times;768</span>"
    "<span id='fps'></span></div>"
    "</div>"
    "<script>"
    "let t=Date.now(),n=0;"
    "const "
    "img=document.getElementById('stream'),fps=document.getElementById('fps');"
    "img.onload=()=>{n++;const "
    "d=Date.now()-t;if(d>1000){fps.textContent=Math.round(n*1000/d)+' "
    "FPS';n=0;t=Date.now()}};"
    "</script>"
    "</body></html>";

/* ---------- / handler (serve HTML page) ----------------------------------- */
static esp_err_t index_handler(httpd_req_t *req) {
  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, index_html, sizeof(index_html) - 1);
}

/* ---------- /stream handler (MJPEG) --------------------------------------- */
static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t *fb = NULL;
  esp_err_t res = ESP_OK;
  char part_buf[64];

  /*
   * KEY FIX: Switch socket to BLOCKING mode.
   * ESP-IDF httpd sets O_NONBLOCK, causing send() to return EAGAIN
   * instantly instead of waiting for the TCP buffer to drain.
   * This was the root cause of both disconnects and 0.1 FPS.
   */
  int fd = httpd_req_to_sockfd(req);
  if (fd >= 0) {
    int flags = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, flags & ~O_NONBLOCK);

    /* 5s send timeout — prevents blocking forever if client dies */
    struct timeval tv = {.tv_sec = 5, .tv_usec = 0};
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    /* Disable Nagle for lower latency */
    int yes = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes));
  }

  /* Use httpd framework to send proper HTTP headers */
  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if (res != ESP_OK)
    return res;
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(req, "Cache-Control", "no-cache");

  ESP_LOGI(TAG, "=== Stream started (fd=%d) ===", fd);

  /* Performance tracking */
  int64_t perf_start = esp_timer_get_time();
  uint32_t frame_count = 0;
  uint64_t total_bytes = 0;
  uint32_t min_size = UINT32_MAX, max_size = 0;

  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      ESP_LOGE(TAG, "Camera capture failed");
      res = ESP_FAIL;
      break;
    }

    /* Skip corrupted frames */
    if (fb->format != PIXFORMAT_JPEG || fb->len < 100) {
      esp_camera_fb_return(fb);
      continue;
    }

    size_t hlen = snprintf(part_buf, sizeof(part_buf), _STREAM_PART, fb->len);

    /* Send via httpd framework (now works because socket is blocking) */
    res =
        httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    if (res == ESP_OK)
      res = httpd_resp_send_chunk(req, part_buf, hlen);
    if (res == ESP_OK)
      res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);

    /* Track stats */
    frame_count++;
    total_bytes += fb->len;
    if (fb->len < min_size)
      min_size = fb->len;
    if (fb->len > max_size)
      max_size = fb->len;

    esp_camera_fb_return(fb);

    if (res != ESP_OK) {
      ESP_LOGI(TAG, "Client disconnected (sent %lu frames)",
               (unsigned long)frame_count);
      break;
    }

    /* Log performance every 3 seconds */
    int64_t elapsed = esp_timer_get_time() - perf_start;
    if (elapsed >= 3000000) {
      float fps = (float)frame_count / ((float)elapsed / 1000000.0f);
      float avg_kb = (float)total_bytes / frame_count / 1024.0f;
      float throughput =
          (float)total_bytes * 8.0f / ((float)elapsed / 1000000.0f) / 1024.0f;

      ESP_LOGI(TAG,
               "FPS: %.1f | Avg: %.1fKB | Min: %.1fKB | Max: %.1fKB | "
               "Speed: %.0f kbps",
               fps, avg_kb, (float)min_size / 1024.0f,
               (float)max_size / 1024.0f, throughput);

      perf_start = esp_timer_get_time();
      frame_count = 0;
      total_bytes = 0;
      min_size = UINT32_MAX;
      max_size = 0;
    }

    /* Small yield */
    vTaskDelay(1);
  }

  return res;
}

/* ---------- Start HTTP server --------------------------------------------- */
esp_err_t start_camera_stream_server(void) {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  config.ctrl_port = 32768;
  config.max_open_sockets = 2;
  config.stack_size = 16384;
  config.lru_purge_enable = true;
  config.recv_wait_timeout = 30;
  config.send_wait_timeout = 30;

  httpd_handle_t server = NULL;
  esp_err_t ret = httpd_start(&server, &config);
  if (ret != ESP_OK) {
    ESP_LOGE(TAG, "Failed to start HTTP server: %s", esp_err_to_name(ret));
    return ret;
  }

  httpd_uri_t index_uri = {.uri = "/",
                           .method = HTTP_GET,
                           .handler = index_handler,
                           .user_ctx = NULL};
  httpd_register_uri_handler(server, &index_uri);

  httpd_uri_t stream_uri = {.uri = "/stream",
                            .method = HTTP_GET,
                            .handler = stream_handler,
                            .user_ctx = NULL};
  httpd_register_uri_handler(server, &stream_uri);

  ESP_LOGI(TAG, "HTTP server started on port %d", config.server_port);
  return ESP_OK;
}
