## Audit addendum — next verified work (2026-10-19)

### Gói hiện tại: catalog model chỉ từ provider
- [x] Loại bỏ các model ID hard-code khỏi kết quả `/api/models`.
- [x] Không hiển thị model không được MộtAPI xác nhận trong `index.html`.
- [x] Thêm test mock xác minh chỉ hiển thị ID từ catalog provider và fail-closed khi thiếu key.
- [ ] Chạy `python -m unittest -v test_app` trên checkout thật.
- [ ] Khi đã có key: kiểm tra `GET /api/models`, gửi chat end-to-end và xác nhận model ID thật.

### Ưu tiên sau đó
1. **P0 — Authentication:** thiết kế đăng nhập và session cookie server-side; không coi `X-Session` là danh tính. Thêm CSRF protection nếu dùng cookie, rate limit phù hợp và test cô lập người dùng.
2. **P1 — Chat reliability:** kiểm tra retry/idempotency ở cấp request và lưu message khi stream bị hủy/lỗi; thêm test không phát sinh phản hồi trùng.
3. **P1 — UI regression:** kiểm tra trình duyệt cho chat, đổi tên/ghim/lưu trữ/xóa, projects, file workspace, panel preview và trạng thái thiếu API key/model.
4. **P1 — Deploy/data:** xác minh `DATABASE_PATH` và `WORKSPACE_DIR` trỏ đến persistent disk trên Render trước khi dùng dữ liệu quan trọng.
5. **P2 — Product scope:** project detail UI, artifact version controls, coding task orchestration chỉ sau khi các luồng P0/P1 ổn định.
