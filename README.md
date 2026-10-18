# MộtAPI AI Chat — GitHub + Render Web Service

Website chat AI dùng MộtAPI qua giao thức tương thích OpenAI. Frontend `index.html`, backend Flask `server.py`; API key chỉ đặt ở biến môi trường Render.

## Chức năng
- Chọn 17 model: `DeepSeek-V4-Flash-0731`, `claude-sonnet-4-6`, `claude-sonnet-5`, `claude-sonnet-5-5`, `deepseek-v4-flash`, `glm-5.3-flash`, `gpt-5.6-sol`, `gpt-6-astra`, `gpt-6-luna`, `gpt-6-sol`, `grok-4.5`, `grok-4.6`, `hy3`, `hy4-preview`, `minimax-m2.7`, `minimax-m3`, `qwen3.8-max`.
- Streaming: câu trả lời hiện dần; nút dừng yêu cầu.
- Lịch sử chat trong phiên trình duyệt; nút Chat mới.
- Đính kèm nhiều tệp/ảnh; trích xuất TXT/MD/CSV/JSON/code, PDF, DOCX; ảnh gửi theo định dạng vision nếu model hỗ trợ.
- `/api/health` và `/api/models`; thông báo lỗi xác thực, số dư, quyền model, quota.

## Cài đặt
1. Giải nén ZIP, tải 6 file ở thư mục gốc lên repository GitHub: `index.html`, `server.py`, `requirements.txt`, `render.yaml`, `.gitignore`, `README.md`.
2. Trên Render chọn **New → Web Service**, kết nối repository. Build command: `pip install -r requirements.txt`; Start command: `gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180`.
3. Trong Environment đặt `MOTAPIS_API_KEY` = API key MộtAPI; `MOTAPIS_BASE_URL` = `https://motapis.com/v1`; `MAX_UPLOAD_MB` = `25`; `AI_MAX_TOKENS` = `4096`; `AI_TEMPERATURE` = `0.7`.
4. Deploy, mở trang Render. Mở `/api/health` và xác nhận `configured: true`.

Có thể dùng `render.yaml` tham khảo, nhưng lựa chọn dịch vụ là **Web Service**, không cần Blueprint. Không bao giờ đưa API key vào HTML hoặc commit lên GitHub.

## Lưu ý quan trọng
- Danh sách model trong giao diện là theo yêu cầu; không đảm bảo mọi model ID còn tồn tại hoặc được cấp quyền cho API key. Nếu model lỗi, kiểm tra dashboard hoặc `/api/models`.
- Nếu nhận 402 hoặc `NOT_ENOUGH_BALANCE`, cần kiểm tra/nạp credit MộtAPI; code không thể vượt giới hạn thanh toán.
- Giới hạn upload mặc định 25 MB mỗi request. Có thể đổi `MAX_UPLOAD_MB`, nhưng Render, RAM và giới hạn upstream vẫn áp dụng; không có upload vô hạn thực sự.
- Tệp được gửi đến nhà cung cấp AI để xử lý. Tránh tải dữ liệu nhạy cảm lên nếu không muốn chia sẻ với nhà cung cấp.
- Bản này chưa có đăng nhập, Google Login hoặc lưu hội thoại PostgreSQL; lịch sử chat chỉ nằm trong bộ nhớ của trình duyệt.
