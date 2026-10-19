# CHANGELOG — bản Codex-inspired rebuild

- Chuyển từ một `index.html` lớn sang `app.py`, `database.py`, `search_engine.py`, `static/app.css`, `static/app.js`.
- Cải tiến multi-provider search, ba nhánh query, dedupe/ranking, timeout và báo cáo từng nguồn.
- Thêm Research page độc lập và nối search vào chat streaming.
- Bổ sung trạng thái thử kết nối API và hiển thị rõ trạng thái thiếu API key.
- Thêm/giữ persistence cho chat, project instructions, rename/pin/archive/delete/search history và lọc hội thoại theo project.
- Workspace hỗ trợ upload, đọc, tải, xóa, xem code và attach tệp đã lưu vào prompt; giải nén ZIP/TAR/TGZ/TAR.GZ có guard chống traversal/bomb cơ bản.
- Inspector xem trước HTML/SVG/Markdown trong sandbox.
- Xuất DOCX/XLSX/PPTX/text, JSON, CSV, HTML; in tài liệu thành PDF từ trình duyệt.
- Bỏ stream/persist reasoning thô; thêm rate limit và quota upload/workspace.
- Thêm schema migration cho `messages.conv_id` của bản MotAPI Studio trước.
