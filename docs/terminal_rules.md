# Lưu ý quan trọng khi gọi lệnh Terminal (CMD Windows)

Tài liệu này ghi chú lại các lỗi và cách khắc phục khi AI Assistant tương tác với Terminal (cmd.exe) trên máy của User để tránh lặp lại lỗi tương tự trong tương lai.

## 1. Nguyên nhân lỗi trước đó:
- **Hoàn toàn là do cách AI truyền lệnh (syntax & formatting), KHÔNG PHẢI do máy hay setup của User.**
- Môi trường: Windows `cmd.exe`.
- Khi dùng công cụ `run_command` chạy ngầm, lệnh bị kẹt do AI không gửi kèm phím `Enter` (ký tự `\n`) ở cuối.
- Khi lồng lệnh bằng `cmd /c "..."`, hệ thống parse chuỗi ngoặc kép của AI bị sai cú pháp, dẫn đến lỗi không nhận diện được syntax.

## 2. Quy tắc bắt buộc khi dùng Terminal cho AI:
1. **Không lồng ngoặc kép bừa bãi**: Tránh dùng cú pháp kiểu Unix/Bash (`cmd /c "echo ... > file"`) nếu không quản lý được escape character của Windows. Dùng thẳng chuỗi không bọc ngặc nếu không có khoảng trắng phức tạp.
2. **Gửi phím Enter**: Nếu mở một tiến trình CMD ngầm (`run_command`), phải nhớ dùng công cụ `send_command_input` và truyền chính xác ký tự `\n` vào chuỗi lệnh để ép Terminal thực thi.
3. **Ưu tiên Native Tools (Công cụ gốc)**: Chỉ ép Terminal gõ lệnh khi cấu hình hệ thống, chạy server, build code. Nếu chỉ là *Tạo file, Ghi file, Đọc file, Liệt kê danh mục*, bắt buộc **PHẢI DÙNG** các công cụ có sẵn cực kỳ an toàn như `write_to_file`, `list_dir`, `view_file`. Không mượn Terminal làm các việc này.

*Ghi chú này được lưu lại để AI luôn tự nhắc mình trong các lần thao tác tiếp theo.*
