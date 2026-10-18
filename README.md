# MotAPI Studio — Space Edition (Audit & Reliability Upgrade)

Bản nâng cấp cho GitHub + **Render Web Service**, sử dụng MộtAPI theo giao diện OpenAI-compatible.

## Nâng cấp trong bản này

- Giao diện không gian đen, sao tĩnh nhẹ, responsive cho điện thoại; không dùng canvas hoặc vòng lặp animation nền.
- Streaming SSE với `Cache-Control: no-cache, no-transform` và tắt proxy buffering.
- Lưu câu hỏi ngay khi gửi, lưu từng phần trả lời theo nhịp 250 ms, lưu phần cuối khi stream kết thúc/dừng/lỗi; không render lại danh sách lịch sử ở mỗi token.
- Nút **Kiểm tra API** gửi một yêu cầu nhỏ đến model đang chọn, để phân biệt lỗi cấu hình API/model với lỗi giao diện.
- `/api/health` báo trạng thái cấu hình; `/api/diagnostics` thử kết nối thật; `/api/models` lấy danh sách model từ provider nếu endpoint hỗ trợ.
- Tìm kiếm song song qua DuckDuckGo, Bing, Wikipedia và Google News RSS mà không yêu cầu API key tìm kiếm. Tavily là tùy chọn và được hợp nhất nếu đã cấu hình. Kết quả được gộp, lọc URL trùng và giới hạn số nguồn.
- Xử lý lỗi provider dễ hiểu hơn (401, 402, 403, 404, 429, 5xx), thử lại một lần nếu provider báo rõ rằng `temperature` hoặc `max_tokens` không được hỗ trợ.
- Upload nhiều tệp, trích xuất văn bản/code, PDF, DOCX và gửi ảnh qua `image_url` cho model có hỗ trợ vision.
- Chế độ Chat / Research / Coding, xuất hội thoại, xuất câu trả lời, xuất code, sao chép nội dung.
- Giữ khóa API ở backend; không đưa khóa vào HTML hoặc repository.

## Cài đặt bằng Render Web Service

1. Giải nén ZIP và đưa các tệp trong thư mục gốc lên repository GitHub.
2. Render Dashboard → **New → Web Service** → kết nối repository.
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180`
5. Trong Environment, cấu hình:
   - `MOTAPIS_API_KEY`: API key hợp lệ từ MộtAPI (**bắt buộc để gọi model**).
   - `MOTAPIS_BASE_URL`: `https://motapis.com/v1`
   - `MAX_UPLOAD_MB`: `25`
   - `AI_MAX_TOKENS`: `4096`
   - `AI_TEMPERATURE`: `0.7`
   - `API_TIMEOUT_SECONDS`: `180` (tùy chọn)
   - `TAVILY_API_KEY`: tùy chọn, không cần nếu dùng các công cụ tìm kiếm công khai.
6. Deploy. Mở `https://TEN-DICH-VU.onrender.com/api/health`. `configured` phải là `true`.
7. Mở trang web, chọn đúng model, bấm **Kiểm tra API**. Nút này thực sự gọi model; thông báo sẽ giúp xác định lỗi key, credit, quyền model hoặc endpoint.
8. Thử tìm kiếm bằng cách bật **Tìm kiếm web** hoặc chọn **Research**. Nếu không có nguồn, thử lại sau và xem log Render; các công cụ tìm kiếm miễn phí có thể chặn truy cập từ datacenter.

## Nếu API không kết nối

- **401**: API key sai/hết hiệu lực; cập nhật `MOTAPIS_API_KEY` trong Render, không đặt trong GitHub.
- **402 / NOT_ENOUGH_BALANCE**: kiểm tra số dư/credit ở MộtAPI.
- **403**: kiểm tra quyền model, tài khoản, hạn mức hoặc chính sách của gateway.
- **404**: kiểm tra `MOTAPIS_BASE_URL` và tên model; không phải mọi tên model gợi ý đều chắc chắn tồn tại trên tài khoản.
- **429**: rate limit/quota; giảm tần suất hoặc kiểm tra hạn mức.
- **5xx / timeout**: lỗi upstream hoặc provider chậm; thử model khác và xem log.
- Nếu `/api/health` trả về HTML thay vì JSON, Render có thể chưa deploy đúng `server.py`, start command sai, hoặc ứng dụng đang crash.

## Giới hạn và riêng tư

- Tìm kiếm công khai không cần key nhưng không được bảo đảm luôn khả dụng; mạng Render hoặc các công cụ tìm kiếm có thể giới hạn truy cập. Tìm kiếm không phải API của model và không thể sửa lỗi key/credit của MộtAPI.
- Chỉ lưu lịch sử trên trình duyệt hiện tại (`localStorage`), chưa có đăng nhập hoặc PostgreSQL. Dữ liệu trong trình duyệt có thể bị xóa nếu xóa dữ liệu trang hoặc hết dung lượng; hãy xuất chat quan trọng.
- Bản Coding chưa tự chạy terminal, chưa tự sửa repository GitHub và chưa chạy test trong sandbox. Không nên coi đây là agent toàn quyền như Codex.
- Panel tiến trình hiển thị trạng thái công việc tổng quát, không hiển thị suy nghĩ nội bộ riêng tư của model.
- Các tệp và nội dung chat được gửi đến nhà cung cấp model khi bạn sử dụng tính năng AI. Tránh tải lên bí mật, mật khẩu hoặc dữ liệu nhạy cảm.

## Kiểm tra đã thực hiện với gói nguồn

- `python -m py_compile server.py`: đạt.
- `node --check` trên JavaScript nhúng trong `index.html`: đạt.
- ZIP integrity: kiểm tra bằng `zipfile.testzip()`.

Các kiểm tra tĩnh này không thay thế kiểm thử trực tiếp trên tài khoản MộtAPI/Render; để xác nhận kết nối thật, dùng nút **Kiểm tra API** sau khi deploy.
