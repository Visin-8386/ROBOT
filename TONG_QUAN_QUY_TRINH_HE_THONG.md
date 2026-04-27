# TONG QUAN QUY TRINH HOAT DONG HE THONG ROBOT (DAY DU)

Tai lieu nay mo ta chi tiet toan bo luong hoat dong cua he thong gom 3 khoi:
- station (ESP32-CAM): chup va gui anh
- server (Python): AI detection + FaceID + API + DB + MQTT
- SIN (ESP32 motor): dieu khien robot + doc cam bien

Muc tieu: giup ban nhin thay ro he thong chay tu dau den cuoi, tat ca tuong tac voi nhau nhu the nao.

---

## 1. Kien truc tong the

### 1.1 Thanh phan chinh
1. station (ESP32-CAM)
- Ket noi WiFi.
- Khoi tao camera OV3660.
- Chup frame JPEG lien tuc.
- Gui frame len server qua TCP cang 8765 theo giao thuc:
  - [4-byte big-endian length] + [JPEG bytes]

2. server (Python)
- Nhan frame TCP tu station.
- Chay YOLO de phat hien target (person/pet).
- Chay FaceID thread de nhan dien khuon mat (known/unknown).
- Tinh pan/tilt va publish vi tri muc tieu qua MQTT.
- Nhan alert tu SIN qua MQTT va luu DB.
- Cung cap FastAPI + stream + dashboard.
- Luu lich su event/alert vao PostgreSQL.

3. SIN (ESP32 robot)
- Ket noi WiFi + MQTT broker.
- Dieu khien motor TB6612.
- Doc cam bien PIR + VL53L0X.
- Nhan lenh tu web (robot/command).
- Nhan du lieu vi tri muc tieu tu server (robot/position).
- Gui canh bao cam bien ve server (robot/alert).

### 1.2 Duong truyen du lieu
1. station -> server (TCP 8765): anh JPEG thoi gian thuc.
2. server -> SIN (MQTT robot/position): detected, x, y, pan, tilt.
3. web/API -> SIN (MQTT robot/command): lenh dieu khien va chuyen mode.
4. SIN -> server (MQTT robot/alert): PIR, distance, status.
5. server <-> PostgreSQL: luu lich su detection/alert.
6. web/mobile app -> FastAPI (port 8000): status, stream, control, faces.

---

## 2. Thu tu khoi dong toan he thong

## 2.1 Buoc A - Chuan bi cau hinh chung
1. Sua shared_config.h:
- WIFI_SSID, WIFI_PASS
- SERVER_IP
- WS_SERVER_URI
- MQTT_BROKER_URI

2. Build/flash 2 firmware:
- station (ESP32-CAM)
- SIN (ESP32 robot)

3. Khoi dong backend server:
- MQTT broker
- PostgreSQL
- server Python (TCP + YOLO + API + MQTT)

## 2.2 Buoc B - station khoi dong
1. Init NVS.
2. Khoi tao camera truoc WiFi de tranh sut nguon.
3. Ket noi WiFi.
4. Tao task gui frame len server (tcp sender).
5. Chay vong lap chup/gui frame lien tuc.

## 2.3 Buoc C - SIN khoi dong
1. Init motor.
2. Init sensor (PIR, ToF).
3. Ket noi WiFi.
4. Ket noi MQTT.
5. Subscribe:
- robot/position
- robot/command
6. Vao state mac dinh: MONITOR.

## 2.4 Buoc D - server khoi dong
1. Init DB.
2. Load YOLO model.
3. Khoi tao servo controller (gia lap goc pan/tilt).
4. Neu bat FaceID:
- load embeddings
- tao FaceRecognitionEngine
5. Khoi tao MQTT client.
6. Khoi tao Telegram notifier (neu cau hinh).
7. Start cac thread:
- TCP receiver
- YOLO inference
- Processing/Draw/Publish
- Face recognition (neu bat)
- Command publisher
- FastAPI

---

## 3. Luong chay frame-to-action (mot vong day du)

Day la chuoi tuong tac quan trong nhat trong he thong.

1. station chup duoc 1 frame JPEG.
2. station gui frame len server qua TCP.
3. server nhan frame, dua vao frame_queue.
4. YOLO thread lay frame moi nhat, decode JPEG, chay detect.
5. Ket qua detection duoc track theo ID (SORT), loc muc tieu.
6. Neu target_type la person va FaceID bat:
- day mot so detection sang face_queue theo chu ky
- FaceID thread crop mat va so khop embeddings
- luu ket qua known/unknown vao cache
7. Processing thread:
- chon main target (lock ID neu co)
- tinh pan/tilt
- publish robot/position qua MQTT
- ve box + face label + thong so len frame
- encode JPEG de stream dashboard
- luu su kien vao DB (theo interval)
8. SIN nhan robot/position:
- neu detected=true thi bam huong pan
- neu pan lech phai -> quay phai
- neu pan lech trai -> quay trai
- neu trong deadzone -> tien
- neu distance < nguong dung -> dung
9. SIN gui robot/alert neu co su kien PIR/khoang cach.
10. server nhan alert, luu DB, dashboard hien thi real-time.

---

## 4. Chi tiet phat hien va nhan dien khuon mat

## 4.1 Hai tang khac nhau
1. Detection (YOLO)
- Tra loi cau hoi: co nguoi hay khong? o dau trong khung hinh?
- Output: bbox, center, track ID.

2. Face Recognition (FaceID)
- Tra loi cau hoi: nguoi do la ai?
- Dua tren embeddings da hoc truoc.
- Output: name + similarity + known/unknown.

## 4.2 Cach FaceID duoc kich hoat
1. Chi chay khi FACE_RECOGNITION_ENABLED = true.
2. FaceID uu tien chay bat dong bo de khong lam cham YOLO.
3. Khong quet tat ca doi tuong moi frame:
- gioi han so nguoi quet moi dot
- co cooldown cho unknown
- co TTL de xoa cache unknown cu
4. Khi ket qua du tin cay (>= threshold):
- danh dau confirmed
- luu cache theo track_id
- hien thi ten tren frame

## 4.3 Du lieu khuon mat
1. Thu muc known_faces/<ten_nguoi>/...
2. API upload anh:
- /api/faces/upload
3. Sau khi upload:
- rebuild embeddings.npz
- reload runtime face engine
4. API liet ke:
- /api/faces

---

## 5. State machine cua SIN (robot)

## 5.1 MONITOR (mac dinh)
1. Robot dung yen.
2. Theo doi PIR va khoang cach.
3. Gui alert theo cooldown.
4. Neu phat hien person_active co the chuyen CHASE (theo logic hien tai).

## 5.2 PATROL
1. Robot tu chay tuan tra.
2. Gap vat can -> re tranh.
3. Neu bi ket goc nhieu lan -> lui + doi huong.
4. Neu co nguoi -> chuyen CHASE.

## 5.3 CHASE
1. Nhan pan/tilt tu server.
2. Dieu huong theo pan.
3. Dung khi qua gan (STOP_DIST).
4. Mat muc tieu qua timeout -> ve PATROL.
5. Neu server bao camera_offline -> ep ve MONITOR (an toan).

## 5.4 MANUAL
1. Nhan lenh truc tiep tu web.
2. Uu tien lenh tay.
3. Timeout va da dung thi tra ve MONITOR.

---

## 6. Vai tro API/FastAPI trong he thong

1. /api/status
- Tra trang thai tong hop: state, mqtt_connected, camera_connected, target_type.

2. /api/control?action=...
- Nhan lenh web, dua vao command_queue, publish MQTT den SIN.

3. /api/target?type=person|pet
- Chuyen muc tieu detect giua nguoi va thu cung.

4. /api/stream
- Phat MJPEG frame da duoc ve AI/Face label.

5. /api/events, /api/alerts
- Doc lich su su kien va canh bao.

6. /api/faces, /api/faces/upload
- Quan ly du lieu nhan dien khuon mat.

---

## 7. MQTT topics (thuc te van hanh)

1. robot/position (Server -> SIN)
- detected
- x, y
- pan, tilt
- ts
- co truong camera_offline khi mat stream lau

2. robot/command (Server/API -> SIN)
- action: forward/backward/left/right/stop/patrol/chase/monitor
- ts

3. robot/alert (SIN -> Server)
- type: pir/distance/status/...
- detail
- distance_mm
- pir
- ts

---

## 8. Co che an toan va fallback

1. station
- Neu mat WiFi: retry lien tuc.
- Neu camera loi: restart chip.

2. server
- Queue co gioi han de tranh nghen bo nho.
- Neu processing timeout frame: publish target_lost/camera_offline.
- Chi giu 1 ket noi ESP32-CAM active, thay stale client neu can.

3. SIN
- Neu camera_offline khi dang chase/patrol: ve MONITOR.
- Khoang cach qua gan: dung.
- Mode manual co timeout de tranh chay vo han do mat lenh.

---

## 9. Trinh tu van hanh de test end-to-end

1. Khoi dong server va xac nhan:
- API /api/health ok
- MQTT broker online
- DB ket noi ok

2. Bat station:
- Thay TCP connected tren server
- Co stream anh tren /api/stream

3. Bat SIN:
- Thay MQTT connected
- Co status/alert di ve server

4. Tren dashboard:
- Thu lenh manual forward/left/stop
- Thu chuyen mode monitor/patrol/chase

5. Test detection + face:
- Dua mat nguoi vao camera
- Xac nhan co bbox va track
- Neu da co du lieu face: thay ten known
- Neu chua co: upload anh qua /api/faces/upload roi test lai

6. Test fallback:
- Tat station tam thoi -> SIN phai fallback an toan
- Bat lai station -> he thong tiep tuc chase/patrol binh thuong

---

## 10. Ket luan ngan gon

He thong nay hoat dong theo mo hinh:
- station la mat (capture)
- server la nao (AI + FaceID + dieu phoi)
- SIN la co the (motor + sensor + hanh dong)

FaceID da duoc tich hop thanh mot lop rieng, chay bat dong bo trong server, bo sung danh tinh (ai) tren nen detection (co ai) de he thong vua duoi muc tieu vua biet nguoi quen/nguoi la.
