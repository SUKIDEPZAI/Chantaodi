# Báo cáo tiếp quản — Chantaodi / MotAPI Studio v3

Ngày audit: 2026-10-19  
Repository: https://github.com/SUKIDEPZAI/Chantaodi  
Phạm vi kiểm tra: cấu trúc file, source backend, giao diện, DB, cấu hình deploy, tests và tài liệu hiện có.

## 1. Bản đồ kiến trúc thực tế

| Thành phần | Vị trí | Xác minh |
|---|---|---|
| Tên sản phẩm | `README.md`, `index.html` | MotAPI Studio v3 / title MotAPI Studio |
| Backend + API | `server.py` | Flask, routes `/api/chat`, `/api/models`, `/api/diagnostics`, `/api/search`, `/api/health` |
| UI | `index.html` | HTML/CSS/JS thuần, dark theme, sidebar, chat, model selector, workspace file, context preview |
| Persistence | `store.py` | SQLite; schema tự khởi tạo khi import; API v2 cho conversations/projects/artifacts |
| Workspace files | `files_routes.py` | upload/list/read/download/save/delete/zip và giải nén có giới hạn |
| Export | `export_routes.py` | endpoint `/api/export`, hỗ trợ docx/xlsx/pptx/rtf |
| Tests | `test_app.py` | unittest; provider được mock; test persistence, owner scoping, projects, files, artifacts, rate limit/import |
| Dependencies | `requirements.txt` | Flask, Gunicorn, OpenAI SDK, xử lý PDF/DOCX/XLSX/PPTX/7z |
| Deploy | `render.yaml` | Render Python web service, Gunicorn một worker/bốn threads |
| Cấu hình mẫu | `.env.example` | `MOTAPIS_API_KEY`, `MOTAPIS_BASE_URL`, `APP_PASSWORD`, đường dẫn DB/workspace |

## 2. Trạng thái tính năng

| Hạng mục | Trạng thái | Bằng chứng/vị trí | Việc còn thiếu | Ưu tiên |
|---|---|---|---|---|
| UI shell/sidebar | PARTIAL | `index.html` | Chưa có xác minh browser; sidebar desktop chưa thu gọn chuẩn | P1 |
| Chat/stream/stop | PARTIAL | `server.py` `/api/chat`, `index.html` `send()` | Mock tests có; chưa kiểm tra browser hoặc provider thật | P1 |
| MộtAPI | PARTIAL / BLOCKED live test | `server.py` `client()`, `/api/chat`, `/api/models` | Thiếu key trong môi trường audit; catalog từng trộn ID hard-code | P0/P1 |
| Persistence | DONE theo tests hiện có (mock) | `store.py`, `test_app.py` | Chưa rerun tests; SQLite cần persistent disk khi deploy | P1 |
| Conversation management | PARTIAL UI / API có | `store.py` `/api/v2/conversations*`, `index.html` | Dùng `prompt()`/confirm; archive UI còn thiếu | P1/P2 |
| Projects | PARTIAL | `store.py` project routes, `index.html` | Chưa có project detail page; UI form tạm thời | P1 |
| Files/workspace | PARTIAL (có API) | `files_routes.py`, `index.html` | Workspace theo `X-Session`, không gắn vào identity/login | P1 |
| Artifacts | PARTIAL | `store.py` artifact/version API, preview iframe trong `index.html` | UI chưa hoàn chỉnh cho version/edit/restore | P1 |
| Coding agent/workspace | MISSING | Chưa thấy backend task orchestration trong file được kiểm tra | Task state, allowlist, sandbox và diff apply | P2 |
| Authentication | MISSING | `server.py` `gate()`, `index.html` `X-Session` | `APP_PASSWORD` dùng chung và tùy chọn; chưa có identity/session server-side | P0 khi triển khai công khai/nhiều người dùng |
| Security | PARTIAL | `server.py`, `files_routes.py`, `store.py` | Cần threat-model auth/CSRF, SSRF redirect validation, CSP, audit logging | P0/P1 |
| Tests | PARTIAL | `test_app.py` | Mock-only; chưa có browser E2E, provider thật hoặc deploy smoke test | P1 |

## 3. Lỗi đã xác minh trong source

`server.py` khai báo danh sách `MODELS` hard-code. `/api/models` ghép các model đó với `GET /models` của provider; kể cả khi response provider tồn tại, UI chỉ lấy `id` và không lọc `available: false`. Do đó model không có trong catalog MộtAPI vẫn có thể xuất hiện trong selector. Patch đi kèm sửa hành vi này theo hướng fail-closed và bổ sung regression tests.

## 4. Bảo mật và giới hạn

- `MOTAPIS_API_KEY` dùng phía server qua OpenAI SDK với base URL mặc định `https://motapis.com/v1`; không phát hiện key trong mã UI được xem. Key thật vẫn phải được đặt trong secret manager/Render env, không commit.
- `APP_PASSWORD` là cổng bảo vệ tùy chọn với mật khẩu chung, không thay thế đăng nhập có danh tính.
- Data owner hiện dựa trên `X-Session` do client gửi. Đây là phân vùng theo bearer token do trình duyệt tự sinh, không phải xác thực người dùng; không coi là đủ cho hệ thống nhiều người dùng hoặc dữ liệu nhạy cảm.
- `fetch_links()` có kiểm tra IP ban đầu, nhưng chuyển hướng HTTP cần được kiểm tra lại đích để giảm nguy cơ SSRF qua redirect.
- Cần dùng persistent disk cho `DATABASE_PATH`/`WORKSPACE_DIR` nếu muốn dữ liệu sống sót qua restart trên môi trường có filesystem tạm thời.

## 5. Kiểm tra và giới hạn của audit

- Tài liệu repo nêu lệnh test: `python -m unittest -v test_app`.
- `test_app.py` mock `server.client`; tests lịch sử ghi trong `HANDOFF.md` là 11/11 pass. Phiên audit này không chạy lại được do không thể clone checkout trong môi trường hiện tại.
- Tài liệu MộtAPI hiện mô tả `GET /v1/models` với Bearer auth và `POST /v1/chat/completions` hỗ trợ `stream: true` SSE. Điều đó xác minh giao thức tài liệu, không xác minh credentials hoặc quyền model cụ thể của tài khoản.
- GitHub write operation bị từ chối (403); vì vậy không có thay đổi nào được commit trực tiếp lên repository trong phiên này.

## 6. Lệnh xác minh sau khi áp dụng patch

```bash
python -m unittest -v test_app
python -m py_compile server.py store.py files_routes.py export_routes.py test_app.py
```

Sau khi cấu hình key ở môi trường riêng: kiểm tra `/api/health`, `/api/models`, nút “Kiểm tra API”, một chat thật và mở lại conversation. Không đưa API key vào source, Issue, log công khai hay handoff.
