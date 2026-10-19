# IMPLEMENTATION_ROADMAP

**Đã xong (có test mock):** chat streaming qua backend; lưu/khôi phục hội thoại; retry không nhân đôi tin (`client_id`); regenerate thay lượt cuối; cô lập dữ liệu theo `X-Session`; dự án (instructions + tệp) nạp đúng phạm vi; tìm kiếm có escape wildcard; artifact có phiên bản (API); giới hạn tốc độ; giải nén an toàn; xuất docx/xlsx/pptx/rtf.
**Chỉ có API, chưa nối UI:** feedback tin nhắn, phiên bản artifact, danh sách lưu trữ.
**Chưa xây:** đăng nhập thật, trang chi tiết dự án, coding workspace, phân trang tin nhắn, e2e test.
**Nút/luồng dùng `prompt()` tạm:** tạo/sửa dự án, đổi tên hội thoại, hướng dẫn tùy chỉnh.
**Rủi ro khi sửa tiếp:** `index.html` là một file lớn (khối `History` và `UI wiring` phụ thuộc nhau); `/api/chat` giờ tin lịch sử trong DB, không tin `history` client.

| Phase | Việc | Tiêu chí xong | Trạng thái |
|---|---|---|---|
| 1 | Chạy thật với MộtAPI: `/api/diagnostics`, `/api/models`, stream | Có key, 1 chat thật lưu được | NEXT (cần người dùng) |
| 2 | Đăng nhập (đăng ký/đăng nhập, session cookie, CSRF) thay `X-Session` | Test quyền theo user | TODO |
| 3 | UI chuẩn: dialog/menu thay `prompt()`, trang dự án, sidebar thu gọn, feedback | Kiểm thử trình duyệt | TODO |
| 4 | Artifact UI: sửa, lưu phiên bản, khôi phục | Mở lại đúng phiên bản | TODO |
| 5 | Coding workspace thật (task + diff + sandbox + allowlist) | Trạng thái phản ánh việc thật | TODO |
| 6 | e2e + build/migration check + audit log | Tất cả test pass | TODO |
