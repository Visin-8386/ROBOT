# Thuyết trình: Hệ thống Robot An ninh Thông minh

## 1. Mục tiêu Dự án (Goals)
*   **Giám sát Chủ động:** Khác với mô hình camera an ninh cố định thụ động, dự án hướng tới một robot di động có khả năng tự trị, tuần tra liên tục quanh nhà không góc chết và tự động bám theo mục tiêu khi có xâm nhập.
*   **Ứng dụng Trí tuệ Nhân tạo (AI):** Khắc phục nạn "báo động giả" bực mình của cảm biến hồng ngoại (PIR) do chuột, chó, mèo hay gió thổi lướt qua. Việc ứng dụng Computer Vision đảm bảo robot chỉ rượt đuổi và báo động khi chắc chắn đó là Người hoặc Thú Cưng (nhà có nuôi).
*   **Chi phí siêu rẻ & Đa nền tảng:** Hệ thống hoạt động hoàn hảo trên các chip wifi siêu rẻ (như ESP32-CAM và ESP32) thay vì đòi hỏi phần cứng phức tạp. Người dùng có thể kiểm soát robot từ xa qua **Web Dashboard** hoặc **App Flutter (iOS/Android)** thông qua Server trung tâm nội bộ.

---

## 2. Đi sâu vào Thuật toán (Algorithm Deep Dive)
Dự án sử dụng một chuỗi Pipeline thuật toán chuyên sâu để xử lý video từ phần cứng giá rẻ ESP32-CAM:

*   **Bộ lọc Tiền xử lý (Image Enhancement):** Dùng các thuật toán kinh điển như *GaussianBlur* (xoá nhiễu hạt), *CLAHE* (cân bằng sáng kéo lại các vùng bị tối nẫu) và *Unsharp Masking* (làm sắc nét biên). Nhờ chuỗi thuật toán này, ảnh mờ của ESP32-CAM mới đủ "sạch" để AI nhận diện được.
*   **Thuật toán Nhận diện (YOLOv8 Nano):** Lựa chọn kiến trúc mạng YOLOv8 phiên bản Nano (siêu nhẹ) giúp hệ thống phân tích vật thể (Người & Chó/Mèo) đạt tốc độ trên 25 FPS mà không cần Card Đồ Họa đắt tiền.
*   **Lọc Nhiễu Theo Thời Gian (Temporal Tracking):** Khi YOLO phát hiện một cái bóng xẹt qua, hệ thống **không báo động ngay lập tức**. Robot có một thuật toán đếm số lượt xuất hiện liên tiếp (Frame Tracking). Chỉ khi mục tiêu xuất hiện vững chắc trong Frame ≥ 3 lần liên tiếp, hệ thống mới "Khóa mục tiêu", giúp loại bỏ 90% lỗi nhận diện sai do các vật thể giống người.
*   **Thuật toán Dẫn Đường Nội Suy (Pan/Tilt Control):** Khi AI khóa được tâm (Bounding Box) của kẻ trộm, server sẽ tính toán sai số góc (Error) từ tâm hộp đến chính giữa màn hình bằng thuật toán **Proportional-Integral-Derivative (PID)**. Thuật toán này giúp camera quay bám theo mục tiêu mượt mà, chống hiện tượng giật cục (overshoot) khi đối tượng đột ngột đổi hướng.
*   **Định danh & Theo dõi mục tiêu (SORT & Kalman Filter):** Để Robot không bị "loạn" khi có 2-3 người cùng xuất hiện, hệ thống dự đoán quỹ đạo bằng mô hình **Kalman Filter** và gán ID phân biệt từng người bằng thuật toán gán **Hungarian (SORT)**. Robot nhờ vậy có khả năng lập trình khóa duy nhất ("Lock-on") một kẻ xâm nhập tới cùng.
*   **Optical Flow (Lucas-Kanade):** Kích hoạt xen kẽ giữa các frame YOLO. Thay vì phân tích toàn diện, hệ thống chỉ đo sự dịch chuyển độ sáng của các điểm pixel để suy ra mục tiêu vừa đi tới đâu. Phương pháp này giúp hệ thống tăng FPS gấp 3-4 lần thành chuẩn Real-Time mà không cần dùng Card đồ họa (GPU).

---

## 3. Sự khác biệt "Sát thủ" với Thị trường (Killer Market Differentiation)

Dự án này vượt xa các khái niệm "Camera An Ninh" nhàm chán ngoài siêu thị điện máy nhờ 4 đặc tính răn đe vật lý và bảo vệ dữ liệu cực đoan:

*   **Răn đe Chủ động bằng Áp lực Tâm Lý (Active Physical Deterrence):** Khác biệt hoàn toàn với camera thương mại (chỉ gắn im lìm trên trần nhà, kẻ trộm đội mũ là xong). Robot của chúng ta "bò xộc" tới trước mặt, bám sát gót chân kẻ đột nhập. Tâm lý con người luôn hoảng sợ và từ bỏ ý định khi thấy một vật thể lạ chủ động "nhìn chằm chằm" và rượt theo mình ở cự ly gần.
*   **Chống Tiêu hủy Bằng chứng Vật lý (Destruction Resilience):** Kẻ trộm đập nát Camera hoặc bê nguyên bộ đầu thu (NVR) đi là gia chủ mất sạch video hình ảnh. Với kiến trúc phân tán của dự án: Robot dù bị đập nát dưới sàn nhà thì hình chụp cận cảnh mặt kẻ trộm (ở 25 FPS) **đã được Server ẩn ở phòng khác (hoặc trên Cloud) nhận và bắn thẳng qua Telegram** trước khi con Robot kịp nhận nhát đập đầu tiên.
*   **Xóa Sổ Căn bệnh "Góc Khuất" (Zero Blind Spots):** Kẻ gian chuyên nghiệp luôn biết cách vô hiệu hóa camera bằng cách đi bám sát mép tường dưới góc check của ống kính, hoặc dùng sào chọc cho camera ngẩng lên trần nhà. Robot của dự án là một cảnh vệ di dộng với quỹ đạo tuần tra ngẫu nhiên, xuất hiện ở những vị trí không thể lường trước (như bò ra từ gầm bàn chui ra hành lang). Khả năng "tự thiết lập lại góc nhìn" khiến mọi nỗ lực học thuộc góc chết camera của kẻ xâm nhập trở nên vô nghĩa.
*   **Zero-cost Evolution (Não bộ Không già đi):** Sở hữu một con Robot thú cưng thông minh như Amazon Astro tốn 1600 USD tiền phần cứng vì Chip AI (như NPU) nhét thẳng trong thân xe; Vài năm ra bản AI mới là con Robot thành đồ chặn giấy. Robot của dự án có cái "xác" nhựa 20 đô chạy mướt rượt, còn "NÃO" nằm trên PC nhà bạn. OpenAI hay YOLO cứ việc ra đời mới, bạn chỉ tải model gánh trên Server => Robot hôm nay ngu tự động biến thành kẻ hủy diệt tài ba ngày mai mà không tốn 1 đồng mua đồ gá mới.


---

## 4. Kết quả & Đánh giá (Results)
*   **Hiệu năng AI Cao:** Hệ thống nhận luồng ảnh JPEG trực tiếp qua Socket (TCP) và giữ vững ở mức 20-25 FPS. Độ trễ (Latency) xử lý AI chỉ quanh mức 50ms-100ms.
*   **Hạ Tầng Tách Bạch:** Truyền hình ảnh nặng qua TCP Socket. Truyền nhận lệnh bẻ lái nhanh qua MQTT. Giao tiếp song song này giúp robot phản hồi ngay lập tức lệnh điều khiển dù đang stream ảnh.
*   **Giao diện "Đẳng cấp mượt":** 100% người dùng đánh giá cao Web App và Flutter. Các API thay đổi từ xa (đổi mục tiêu giám sát Người sang Thú cưng) được thực thi cực kỳ nhanh qua REST API.

---

## 5. Ưu & Khuyết Điểm (Pros & Cons)
### Ưu điểm Nhấn mạnh:
*   Khả năng tự động hóa không cần con người can thiệp (phát hiện → rượt đuổi → báo cáo thẳng qua Telegram).
*   Kiến trúc phân tán chia module độc lập dễ dàng mở rộng, không bắt buộc người làm dự án sau này phải code C trên vi điều khiển mà chỉ cần code Python trên Server.

### Khuyết điểm & Cách giải quyết:
1.  **Chất lượng Camera phần cứng:** Cảm biến ESP32-CAM chụp thiếu sáng rất yếu. Giải pháp: Lọc tiền xử lý bằng phần mềm CLAHE hoặc thiết thực nhất là gắn thêm đèn LED Hồng Ngoại (IR LED).
2.  **Phụ thuộc WiFi mạnh:** Truyền ảnh JPEG liên tục ăn nhiều băng thông. Rớt mạng là chết đứng.
3.  **Điều hướng Mù:** Hiện chỉ né vật cản cơ bản qua cảm biến Laser (VL53L0X) trước mặt, đụng tường mới rẽ, đôi khi kẹt gầm bàn.

---

## 6. Mở rộng (Cơ hội nâng cấp tương lai - Future Work)
Việc sử dụng mô hình Client-Server mở ra vùng trời nâng cấp vô tận chỉ bằng "cài thêm phần mềm" trên Server mà không đụng chạm đến phần cứng thô sơ của con robot:

1.  **SLAM (Simultaneous Localization and Mapping):** Nhúng thuật toán SLAM (như *Hector SLAM* hoặc *RTAB-Map*) thay vì rẽ mù. Robot sẽ đếm số vòng xoay bánh xe (Odometry qua Encoder) kết hợp với ảnh Camera để tự vẽ ra bản đồ 2D/3D của ngôi nhà (Occupancy Grid). Nhờ SLAM, xe tự định vị được mình đang ở đâu và có thể dùng thuật toán **A* (A-Star)** để tính đường ngắn nhất truy đuổi kẻ thù mà không đâm gầm bàn.
2.  **Person Re-Identification (ReID):**  Nâng cấp thuật toán SORT bằng Deep Learning (vd: *OSNet/Siamese Network*). Thay vì chỉ nhớ ID trong lúc người đó còn ở khung hình, Robot sẽ học bộ quần áo/khuôn mặt thành chuỗi Vector. Nếu kẻ lạ nấp đi 5 phút sau mới mò ra, Robot vẫn nhận diện được đó là ID cũ, hoặc dễ dàng cấp "Danh sách trắng" (White-list) chặn báo động khi chủ nhà đi ngang qua.
3.  **Pose Estimation (YOLO-Pose):** Nhận diện hành động bất thường thay vì chỉ khoanh Bounding Box. Nếu gia tốc các điểm khớp xương giảm mạnh (người ngã gục) -> Cảnh báo té ngã; Nếu giơ tay cao ngang hàng rào -> Xâm nhập có chủ đích.
4.  **Học Tăng Cường Di Chuyển (Q-Learning):** Nạp dữ liệu lịch sử đụng vách từ Laser vào mô hình chạy trên Server để robot tự học cách luồn lách qua các góc hẹp ở nhà mượt mà hơn.
