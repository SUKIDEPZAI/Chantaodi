# MotAPI Studio — gói nâng cấp tìm kiếm + giao diện phong cách Codex

Gói này được chuẩn bị cho repository `SUKIDEPZAI/Chantaodi`. Tôi không thể ghi trực tiếp vào GitHub trong phiên này vì GitHub trả về lỗi `403 Resource not accessible by integration`, vì vậy gói này không thay đổi nhánh `main` của bạn.

## Điểm nâng cấp

- Giao diện nền tối trung tính theo phong cách công cụ lập trình Codex: sidebar gọn, thẻ tác vụ tinh giản, vùng chat/code sạch hơn, composer nổi bật và bố cục responsive cho điện thoại.
- Research mode tự mở rộng thành các nhánh truy vấn: truy vấn chính, tài liệu chính thức và cập nhật gần đây; chạy song song trên nguồn phù hợp, gom URL trùng và xếp thứ tự theo mức liên quan.
- Gửi trạng thái tìm kiếm qua SSE trước khi chờ nguồn trả kết quả, tránh cảm giác ứng dụng bị treo.
- Không đẩy `reasoning_content`/`reasoning` thô đến trình duyệt hoặc lưu vào lịch sử. UI chỉ nên hiển thị trạng thái làm việc và câu trả lời cuối.
- Giữ nguyên Flask, SQLite, routes dự án, workspace, xuất tệp và cấu trúc hiện tại.
- Kiểm tra lại đích URL sau chuyển hướng khi đọc liên kết; thêm kiểm tra giới hạn tổng workspace sau giải nén.
- Gỡ hướng dẫn mâu thuẫn yêu cầu model sinh khối `<think>` và giữ reasoning nội bộ ngoài giao diện/lịch sử.
- Thêm một bài kiểm thử hồi quy bảo đảm suy luận ẩn không bị truyền/lưu.

## Cài đặt

1. Tải ZIP repository hiện tại từ GitHub và giải nén trên máy tính, hoặc clone repo vào môi trường có Python.
2. Giải nén gói nâng cấp này.
3. Chạy script, truyền đường dẫn thư mục gốc repository:

   ```bash
   python apply_upgrade.py /path/to/Chantaodi
   ```

   Nếu đã chép `apply_upgrade.py` vào chính thư mục dự án, chạy `python apply_upgrade.py .`.
4. Kiểm tra mã và test:

   ```bash
   cd /path/to/Chantaodi
   python -m py_compile server.py store.py files_routes.py export_routes.py
   python -m unittest -v test_app
   git diff --check
   ```

5. Xem `git diff`, commit thay đổi lên một branch mới, push và mở Pull Request. Không nên ghi đè thẳng `main` khi chưa chạy test.
6. Xem `CODE_REVIEW.md` để biết các rủi ro còn lại theo mức ưu tiên.
7. Trên Render Web Service, giữ nguyên Start Command hiện tại. Có thể thêm `SEARCH_TIMEOUT_SECONDS=9`; `TAVILY_API_KEY` vẫn là tùy chọn. Nếu cần lịch sử và workspace tồn tại sau khi service khởi động lại, cấu hình `DATABASE_PATH` và `WORKSPACE_DIR` trên Render Disk.

## Lưu ý trung thực về kiểm thử

Đã kiểm tra cú pháp của script áp dụng và xác nhận các điểm chèn khớp với source được đọc qua GitHub connector. Tuy nhiên, gói nâng cấp chưa được áp dụng trực tiếp lên một checkout đầy đủ trong container; chưa được chạy cùng API key MộtAPI thật, chưa được kiểm thử bằng trình duyệt thật và chưa được triển khai Render. Script kiểm tra các điểm chèn trước khi ghi file, nhưng vẫn cần chạy `py_compile`, `unittest` và thử tìm kiếm trên deployment của bạn sau khi áp dụng.

## Những phần chưa tự động giải quyết

- Đăng nhập Google/đăng nhập người dùng thực sự: kiến trúc hiện tại chỉ có `APP_PASSWORD` và `X-Session`.
- Xác minh model ID và hành vi SSE trên MộtAPI: cần API key hợp lệ và model có quyền truy cập.
- Thực thi code sandbox/agent tự sửa repo: chưa có sandbox hoặc quyền chạy lệnh nên gói này không giả lập đã xây dựng agent Codex đầy đủ.
