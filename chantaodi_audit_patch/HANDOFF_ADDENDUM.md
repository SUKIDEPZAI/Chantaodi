## Audit addendum — 2026-10-19

- **Kết quả đối chiếu:** repository dùng Flask + một `index.html` thuần JS/CSS + SQLite; không có frontend build step trong manifest hiện có. Source liên quan: `server.py`, `store.py`, `files_routes.py`, `export_routes.py`, `test_app.py`, `index.html`.
- **Thay đổi được chuẩn bị:** sửa catalog model để chỉ hiển thị model trả về từ MộtAPI và thêm regression tests. Script mặc định chạy dry-run; cần xem diff trước khi commit.
- **Chưa áp dụng từ phiên này:** GitHub integration từ chối tạo branch với 403 `Resource not accessible by integration`; không có commit nào được tạo từ phiên audit.
- **Kiểm thử:** không chạy được trên checkout remote từ container do môi trường không phân giải được `github.com`. Số test lịch sử trong handoff trước là 11/11 với provider mock; kết quả đó chưa được chạy lại trong phiên này.
- **Bước tiếp theo:** tải repo xuống môi trường có quyền ghi, chạy script này ở chế độ dry-run; xem `git diff`; chạy `python -m unittest -v test_app`; sau đó kiểm thử API thật khi có key. Tiếp theo triển khai authentication thực trước khi chia sẻ app cho nhiều người.
- **Không làm lại:** không đổi stack; không xóa hoặc viết lại schema SQLite; không thay nhà cung cấp AI.
