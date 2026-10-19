# Phân tích mã nguồn và các quyết định của bản dựng lại

## 1. Vấn đề đã thấy ở bản MotAPI Studio trước đó

1. **Tìm web dựa nhiều vào HTML scraping.** `server.py` cũ parse kết quả DuckDuckGo/Bing bằng regex HTML. Markup thay đổi hoặc trang trả challenge/rate-limit là parser có thể trả mảng rỗng mà không giải thích rõ nguồn nào hỏng.
2. **Lỗi nguồn tìm kiếm bị gom chung.** Frontend chủ yếu nhận lỗi HTTP 503 hoặc thông báo tổng quát. `/api/health` báo tìm kiếm đã cấu hình ngay cả khi chưa có bằng chứng request tới provider thành công.
3. **Research trì hoãn byte đầu của chat.** Luồng cũ gọi web search trước khi bắt đầu SSE response, nên trình duyệt không nhận tiến độ trong lúc đợi nguồn tìm kiếm.
4. **Trường reasoning được đưa ra giao diện.** Luồng cũ đẩy `reasoning_content`/`reasoning` qua SSE rồi có thể lưu trong `<think>...</think>`. Bản dựng lại chỉ phát status ngắn và nội dung trả lời, không phát trường reasoning này.
5. **Nhiều thao tác phụ thuộc `prompt()`/`confirm()`.** Trải nghiệm dự án và quản lý chat khó mở rộng, không đồng nhất giữa desktop và điện thoại.
6. **Một tệp frontend gộp quá nhiều trách nhiệm.** HTML, CSS và hàng loạt hàm JS nằm trong `index.html`, làm thay đổi UI dễ gây ảnh hưởng lẫn nhau và khó kiểm tra.
7. **Phiên trình duyệt không phải tài khoản.** `X-Session` là bearer token phía trình duyệt; nó cô lập dữ liệu theo phiên, nhưng chưa thay thế đăng nhập thật/OAuth và quản lý phiên người dùng.

## 2. Những thay đổi trong bản này

### Tìm kiếm

- Tách provider adapter vào `search_engine.py` thay vì nhúng vào route Flask.
- Chạy song song Tavily/Brave nếu đã cấu hình key và các nguồn dự phòng DuckDuckGo, Bing, Wikipedia; thêm Google News khi tìm sâu hoặc truy vấn có tính thời sự.
- Chế độ tìm sâu tạo ba nhánh truy vấn: `primary`, `official`, `freshness`. Đây là fan-out truy vấn tìm kiếm song song, không phải tuyên bố rằng ba AI agent tự sửa code độc lập.
- Chuẩn hóa URL, bỏ kết quả trùng theo URL canonical và xếp hạng cơ bản theo từ khóa tiêu đề/nội dung, cùng trọng số tài liệu `.gov`/`.edu`.
- `/api/search` trả `provider_status`, `failed_providers`, `elapsed_ms`, `branches` và `note`; khi không có kết quả, UI không hiển thị kết quả giả.
- Chat gửi status SSE trước khi chờ web search để giao diện biết tác vụ đang chạy.

### Dữ liệu và bảo mật

- `database.py` chứa truy vấn SQLite, tạo schema, truy vấn lịch sử và ràng buộc owner. Những truy vấn dữ liệu đều tham số hóa.
- Khởi tạo DB có đường migrate cho bảng message cũ dùng `conv_id`; chuyển sang `conversation_id`, đồng thời làm sạch khối `<think>` cũ khi đọc lịch sử. Nên sao lưu DB trước khi chạy migrate.
- Rate limit theo phiên cho chat và tìm kiếm. Cấu hình Render dùng một worker để bộ đếm trong bộ nhớ nhất quán trong tiến trình; nếu tăng worker, nên chuyển rate limit sang Redis/DB.
- Workspace giới hạn kích thước tệp, quota tổng, đường dẫn archive, số lượng tệp giải nén và kích thước giải nén; chỉ trích xuất tệp thường, bỏ qua symlink và đường dẫn traversal.
- `APP_PASSWORD` là cổng truy cập tùy chọn. Nó hữu ích cho một demo cá nhân, nhưng là mật khẩu dùng chung chứ không phải xác thực nhiều người dùng.

### Giao diện

- Tách `index.html`, `static/app.css`, `static/app.js`.
- Sidebar: chat, search, workspace và dự án; khu vực trung tâm dùng cho chat hoặc research; inspector bên phải xem HTML/SVG/Markdown hoặc code.
- Status của các nguồn tìm kiếm hiển thị riêng, giúp phân biệt lỗi provider search với lỗi API AI.
- Nội dung từ model được escape khi dựng HTML; preview code chạy trong iframe sandbox không cấp `allow-same-origin`.

## 3. Kiểm tra đã chạy trong môi trường dựng gói

- `python -m py_compile app.py database.py search_engine.py tests/test_app.py tests/test_search_engine.py`: đạt.
- `node --check static/app.js`: đạt.
- `python -m unittest discover -s tests -p 'test_search_engine.py' -v`: 5/5 test đạt.
- Smoke test SQLite cho truy vấn wildcard, project scope và cô lập owner: đạt.
- Smoke test migrate schema cũ dùng `messages.conv_id` và loại `<think>` khi đọc dữ liệu: đạt.
- Kiểm tra HTML parser: 64 ID tĩnh, không trùng; CSS/JS đường dẫn tồn tại.

**Chưa kiểm chứng trong môi trường này:** test HTTP tích hợp Flask, kết nối API AI thật, tìm kiếm web thật từ mạng Render và kiểm thử trên trình duyệt desktop/mobile. Container hiện không có Flask/OpenAI và không truy cập được package index khi thử cài; các dependencies được khai báo trong `requirements.txt` để Render cài lúc deploy. Vì thế không coi phần đó là đã pass.

## 4. Hạng mục cần làm tiếp nếu dùng như dịch vụ nhiều người dùng

- Đăng nhập thật, Google OAuth, secure server-side session, CSRF/secure cookies và thu hồi phiên.
- Kiểm tra end-to-end trình duyệt, log có correlation ID, giám sát và cảnh báo nguồn search.
- Dùng provider tìm kiếm có SLA/khóa API cho độ tin cậy cao hơn scraping HTML công khai.
- Nếu muốn agent tự chạy test/build, cần sandbox container tách biệt, allowlist lệnh, giới hạn tài nguyên, diff review và quyền truy cập kho mã; phiên bản này chưa chạy mã tùy ý.
- Nếu tăng số worker hoặc scale ngang, thay rate limiter trong RAM và SQLite bằng dịch vụ phù hợp (Redis + PostgreSQL).
