# MotAPI Studio — AI Chat, Research & Coding

Website chat sử dụng MộtAPI, triển khai trên GitHub + Render **Web Service**.

## Tính năng
- Giao diện workspace mới, responsive cho điện thoại và máy tính.
- Chat, Research (nghiên cứu), Coding (lập trình/debug/review).
- Chọn 17 model theo yêu cầu; tự bổ sung model mà endpoint `/v1/models` trả về.
- Streaming câu trả lời theo thời gian thực.
- Tìm kiếm web không cần key riêng qua DuckDuckGo; nếu cấu hình `TAVILY_API_KEY`, Tavily được ưu tiên và DuckDuckGo là phương án dự phòng.
- Hiển thị bảng Tiến trình với trạng thái công việc và các bước xử lý tổng quát. Không hiển thị chuỗi suy nghĩ nội bộ riêng tư.
- Đính kèm nhiều tệp/ảnh; trích xuất text, code, PDF, DOCX; gửi ảnh qua image_url nếu model hỗ trợ vision.
- Xuất từng câu trả lời `.md`/`.txt`, xuất khối code, xuất cả hội thoại `.md`; sao chép, dừng, tạo chat mới.
- Lịch sử gần đây được lưu local trong trình duyệt; API key chỉ nằm trên backend.

## Cài đặt GitHub + Render
1. Giải nén ZIP và đưa các file ở thư mục gốc lên repository GitHub: `index.html`, `server.py`, `requirements.txt`, `render.yaml`, `.gitignore`, `README.md`.
2. Render Dashboard → **New → Web Service** → kết nối repository.
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180`
5. Render → Environment:
   - `MOTAPIS_API_KEY`: API key từ dashboard MộtAPI
   - `MOTAPIS_BASE_URL`: `https://motapis.com/v1`
   - `TAVILY_API_KEY`: API key Tavily (tùy chọn; DuckDuckGo vẫn dùng được nếu bỏ trống)
   - `MAX_UPLOAD_MB`: `25`
   - `AI_MAX_TOKENS`: `4096`
   - `AI_TEMPERATURE`: `0.7`
6. Deploy rồi mở `/api/health`; `configured` phải là `true`. Để tìm kiếm web hoạt động, `search_configured` phải là `true`.

## Tìm kiếm web
Không cần nhập API key tìm kiếm: DuckDuckGo được dùng mặc định. Có thể thêm `TAVILY_API_KEY` trong Render Environment để ưu tiên Tavily. Không đưa key vào HTML/GitHub. Các công cụ tìm kiếm công khai vẫn có thể giới hạn truy cập tạm thời.

## Giới hạn cần biết
- Chế độ Coding hỗ trợ phân tích yêu cầu, tạo code, debug từ mô tả/tệp, review và xuất code. Bản này **chưa** chạy lệnh terminal, tự sửa GitHub repo hay thực thi test tự động như một coding agent toàn quyền.
- Tiến trình hiển thị trạng thái/tóm tắt, không phải chuỗi suy nghĩ nội bộ.
- Lịch sử lưu trong localStorage của trình duyệt; chưa có tài khoản đăng nhập hoặc PostgreSQL.
- Upload mặc định 25 MB mỗi request; giới hạn thực tế còn phụ thuộc Render, RAM và nhà cung cấp.
- Model có thể không được cấp quyền dù xuất hiện trong danh sách; hãy kiểm tra `/api/models` và dashboard MộtAPI.
- Prompt và tệp gửi tới MộtAPI/Tavily để xử lý. Tránh gửi dữ liệu bí mật.


### UI and conversation saving

The interface uses a near-black space theme with a small, static star field (no canvas animation) to keep rendering lightweight. Conversations and partial streamed replies are saved in the current browser's localStorage during generation. This protects against refreshes and interrupted streams, but it is not cross-device backup; export important chats regularly. For cross-device persistence, add authentication and a database such as PostgreSQL.
