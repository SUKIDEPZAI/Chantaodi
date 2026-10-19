# PROJECT_STATUS — MotAPI Studio (cập nhật 2026-10-19)

Stack thực tế: Flask 3 (`server.py`) + một file giao diện thuần JS (`index.html`) + SQLite (`store.py`). Không có build step. Chạy: `pip install -r requirements.txt && python server.py` (hoặc gunicorn như `render.yaml`). Test: `python -m unittest -v test_app`.

| Hạng mục | Trạng thái | Vị trí code | Còn thiếu | Ưu tiên |
|---|---|---|---|---|
| UI shell / Sidebar | PARTIAL | `index.html` (sidebar, `.side`) | Chưa mở trên trình duyệt thật; chưa thu gọn sidebar desktop; menu dự án/hội thoại dùng `prompt()`/`confirm()` thay vì dialog/menu chuẩn | P1 |
| Chat UI (stream, stop, regen, copy) | PARTIAL | `index.html` (`send`, `paint`, `regen`) | Chưa kiểm thử trình duyệt; chưa sửa câu hỏi rồi gửi lại; chưa feedback 👍/👎 ở UI (API có) | P1 |
| AI integration (MộtAPI) | BLOCKED (kiểm thử thật) | `server.py` (`client`, `/api/chat`, `/api/models`, `/api/diagnostics`) | Chưa có API key để gọi thật; chưa đối chiếu tài liệu MộtAPI về SSE/usage/tool calling; luồng đã kiểm chứng bằng MOCK | P0 |
| Persistence | DONE (mock) | `store.py`, `server.py` (`generate` lưu cả trả lời dở dang) | Chưa phân trang tin nhắn; SQLite trên đĩa tạm Render sẽ mất khi restart nếu không gắn Disk | P1 |
| Hội thoại (đổi tên, ghim, lưu trữ, xóa, tìm kiếm) | DONE (API) / PARTIAL (UI) | `store.py` `/api/v2/conversations*`; `index.html` `drawHist` | Chưa có màn hình xem mục đã lưu trữ | P2 |
| Projects | PARTIAL | `store.py` `/api/v2/projects*`; `index.html` `projSel` | Chưa có trang chi tiết dự án; instructions + tệp gắn dự án được nạp vào prompt (có test) | P1 |
| Files / giải nén | DONE (mock) | `files_routes.py` | Workspace theo phiên trình duyệt, chưa theo tài khoản | P1 |
| Artifacts | PARTIAL | `index.html` (panel, iframe sandbox không `allow-same-origin`); `store.py` `/api/v2/artifacts*` | UI chưa gọi API phiên bản; chưa chỉnh sửa/khôi phục phiên bản trong giao diện | P1 |
| Coding workspace / agent | MISSING | — | Task, diff, sandbox thực thi, tool allowlist, repo integration. Không giả lập | P2 |
| Authentication | MISSING | — | Hiện chỉ có `APP_PASSWORD` (tùy chọn) + `X-Session` ngẫu nhiên theo trình duyệt (bearer, ai biết giá trị này truy cập được dữ liệu) | P0 nếu nhiều người dùng |
| Security | PARTIAL | `server.py` (`gate`, `_public_url`), `files_routes.py` (zip-slip/bomb), `store.py` (`allow`) | Chưa CSRF; rate limit trong bộ nhớ (1 worker); chưa audit log; chưa CSP header | P0/P1 |
| Testing | PARTIAL | `test_app.py` (11 test, provider MOCK) | Chưa e2e trình duyệt; chưa test với provider thật | P1 |
