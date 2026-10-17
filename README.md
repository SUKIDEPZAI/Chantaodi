# Highway AI Chat — GitHub + Render Web Service

Ứng dụng web chat AI có giao diện HTML, gửi nhiều tệp trong một yêu cầu, đọc TXT/MD/CSV/JSON/code/PDF/DOCX và đính kèm ảnh theo định dạng OpenAI-compatible.

## 1. Bảo mật API key
**Không chép API key vào `index.html`, GitHub hay mã nguồn.** Key đã dán vào cuộc trò chuyện nên hãy thu hồi/đổi key đó ở nhà cung cấp rồi dùng key mới trong Render Environment. Không commit file `.env`.

## 2. Đưa mã lên GitHub
1. Tải ZIP này và giải nén.
2. Tạo repository GitHub mới.
3. Upload các file ở thư mục này lên root repository: `index.html`, `server.py`, `requirements.txt`, `render.yaml`, `.gitignore`, `README.md`.

## 3. Tạo Render Web Service
1. Render Dashboard → **New +** → **Web Service**.
2. Kết nối repository GitHub.
3. Runtime: Python (nếu được hỏi).
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`
6. Trong **Environment**, thêm:
   - `HIGHWAY_API_KEY` = API key mới của bạn
   - `HIGHWAY_BASE_URL` = `https://api.highwayapi.ai/openai/v1`
   - `HIGHWAY_MODEL` = `gpt-6-astra`
   - `MAX_UPLOAD_MB` = `25`
7. Deploy. Mở URL `https://ten-dich-vu.onrender.com`.

Có thể dùng cấu hình từ `render.yaml`, nhưng vẫn cần tự nhập `HIGHWAY_API_KEY` trong Dashboard vì giá trị này là secret.

## 4. Giới hạn upload
Ứng dụng không đặt giới hạn số lượng tệp ở tầng giao diện/backend, nhưng **không thể bảo đảm tải lên “không giới hạn” thật sự**: Render, trình duyệt, RAM, timeout và API nhà cung cấp đều có giới hạn. Mặc định tổng dữ liệu mỗi lần gửi là 25 MB (`MAX_UPLOAD_MB`); tăng biến này nếu gói dịch vụ và bộ nhớ cho phép. Ảnh được gửi dưới dạng data URL nên tệp lớn có thể dùng nhiều RAM. Tệp lưu tạm trong lúc xử lý, không có kho lưu trữ bền vững.

## 5. Lưu ý tương thích API
Mã dùng endpoint OpenAI-compatible `/chat/completions`. Nếu nhà cung cấp không hỗ trợ model `gpt-6-astra`, tham số `max_tokens`, hoặc nội dung ảnh `image_url`, hãy kiểm tra tài liệu của họ rồi đổi `HIGHWAY_MODEL`/tham số tương ứng trong `server.py`. Tệp PDF scan cần OCR mới đọc được; hiện chỉ trích xuất lớp văn bản.
