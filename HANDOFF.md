# HANDOFF (mới nhất: 2026-10-19)

**Đọc trước:** `PROJECT_STATUS.md`, rồi `store.py`, khối `/api/chat` trong `server.py`, khối `History`/`Dự án` trong `index.html`.

**Vừa làm:** thêm `store.py` (SQLite + API v2), nối vào `/api/chat` (`conv_id`, `client_id`, `project_id`, `regen`, `saved`, `title`), thêm UI dự án/ghim/lưu trữ/xóa/tìm kiếm, tự chuyển hội thoại cũ từ localStorage (`/api/v2/import`), thêm `test_app.py`.
**Quyết định:** giữ Flask + 1 file HTML (repo gốc không có framework/DB); chọn SQLite (stdlib, không thêm hạ tầng; schema dùng SQL chuẩn để chuyển PostgreSQL sau). Server là nguồn sự thật của lịch sử.
**Migration:** `CREATE TABLE IF NOT EXISTS` chạy khi import `store.py`; không xóa dữ liệu. Chưa có hệ phiên bản schema.
**Test đã chạy:** `python -m unittest -v test_app` → 11/11 OK (provider MOCK). Kiểm tra cú pháp JS bằng `node --check`. **Chưa** chạy: trình duyệt thật, MộtAPI thật, Render thật.
**Chưa xác minh:** hành vi thật của MộtAPI (SSE, `/models`, `reasoning_content`); giao diện trên trình duyệt; hiệu năng với dữ liệu lớn.
**Việc tiếp theo chính xác:** (1) đặt `MOTAPIS_API_KEY`, deploy, bấm "Kiểm tra API", chat thử, mở lại để xác nhận lưu; (2) làm đăng nhập thật; (3) thay `prompt()` bằng dialog.
**Đừng làm lại:** giải nén/xuất file (`files_routes.py`, `export_routes.py`), schema và test trong `store.py`/`test_app.py`.
**Cần người dùng cung cấp:** API key MộtAPI (đặt trong biến môi trường, không ghi vào repo), quyết định có cần nhiều người dùng không, ổ đĩa bền (`DATABASE_PATH`, `WORKSPACE_DIR`).
