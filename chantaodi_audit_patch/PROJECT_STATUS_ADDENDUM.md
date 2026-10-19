## Audit addendum — verified model catalog (2026-10-19)

- **Xác minh từ source:** Flask backend ở `server.py`; UI/CSS/JS nằm trong `index.html`; SQLite và API v2 ở `store.py`; workspace ở `files_routes.py`; xuất file ở `export_routes.py`; test tích hợp ở `test_app.py`.
- **Sửa trong patch này:** `/api/models` chỉ trả về các `id` nhận được trực tiếp từ `GET {MOTAPIS_BASE_URL}/models`, đánh dấu `available: true` cho các ID trong phản hồi đó, và trả lỗi rõ ràng khi thiếu key / không đọc được catalog. UI không còn dùng danh sách model hard-code làm fallback và khóa thao tác gửi khi không có model đã xác minh.
- **Bằng chứng hiện có:** MộtAPI docs mô tả `GET /v1/models` với Bearer API key; tests hiện tại mock provider. Thử nghiệm với MộtAPI thật vẫn cần `MOTAPIS_API_KEY` trong môi trường triển khai.
- **Chưa được xác minh trong phiên audit:** test suite đầy đủ, trình duyệt thật, tích hợp MộtAPI thật, deploy Render. Không coi patch là đã kiểm thử cho đến khi chạy lệnh ở README.
- **Rủi ro P0 còn lại:** `APP_PASSWORD` là cổng mật khẩu dùng chung và tùy chọn; `X-Session` do trình duyệt tự tạo và gửi về server, chưa phải đăng nhập/phiên xác thực có danh tính. Không coi cơ chế này là bảo vệ dữ liệu đủ dùng cho triển khai nhiều người dùng.
