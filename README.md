# MotAPI Studio v3
Deploy: đẩy toàn bộ tệp lên GitHub, tạo Render Web Service (hoặc dùng render.yaml).
Biến môi trường: MOTAPIS_API_KEY (bắt buộc), APP_PASSWORD (khuyến nghị, chặn người lạ dùng credit), TAVILY_API_KEY (tùy chọn).
Kiểm tra: /api/health, rồi bấm "Kiểm tra API" trong giao diện.

Tệp workspace: tải lên/giải nén zip, tar, tgz, gz, bz2, xz, 7z (rar cần rarfile + unrar). Giới hạn: WORKSPACE_MAX_MB (300), MAX_EXTRACT_MB (200).
Ô đĩa Render miễn phí là tạm thời; muốn giữ tệp lâu dài hãy gắn Render Disk và đặt WORKSPACE_DIR.

Dữ liệu: hội thoại/dự án lưu trong SQLite (`DATABASE_PATH`). Trên Render hãy gắn Disk (ví dụ /var/data) và đặt DATABASE_PATH, WORKSPACE_DIR. Xem PROJECT_STATUS.md, IMPLEMENTATION_ROADMAP.md, HANDOFF.md. Test: `python -m unittest -v test_app`.
