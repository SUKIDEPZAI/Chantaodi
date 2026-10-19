# Chantaodi — AI Workspace (Codex-inspired rebuild)

Bản dựng lại gọn hơn theo mô hình **workspace AI**: sidebar cho hội thoại/dự án, chat streaming ở trung tâm, tìm kiếm web nhiều nguồn, workspace tệp và inspector để xem trước code. Đây là giao diện lấy cảm hứng từ cách tổ chức công việc của các coding assistant hiện đại; không sao chép mã nguồn hay nhận diện chính thức của Codex.

## Chức năng đã có trong mã nguồn

- Chat streaming qua API tương thích OpenAI (`MOTAPIS_API_KEY` + `MOTAPIS_BASE_URL`, hoặc `OPENAI_API_KEY` + `OPENAI_BASE_URL`).
- Tùy chọn model; thử kết nối API ở `/api/diagnostics`.
- Web search riêng trong UI và chế độ Research tích hợp vào chat.
- Fan-out tìm kiếm theo nhiều nguồn song song: Tavily/Brave khi có key, cùng DuckDuckGo, Bing, Wikipedia; nhánh tìm sâu bổ sung truy vấn tài liệu chính thức và Google News cho nội dung mới.
- Hiển thị rõ nguồn nào thành công/thất bại, loại URL trùng, xếp hạng cơ bản theo độ liên quan; endpoint search vẫn trả thông tin chẩn đoán nếu không có nguồn nào phản hồi.
- Hội thoại bền vững bằng SQLite, đổi tên, ghim, lưu trữ, xóa, tìm kiếm lịch sử và tách dữ liệu theo mã phiên trình duyệt.
- Dự án với hướng dẫn riêng cho AI.
- Tải tệp vào workspace, đọc/xóa/tải về; giải nén ZIP/TAR/TGZ an toàn với giới hạn đường dẫn, số tệp, dung lượng đầu ra và tổng quota workspace.
- Đọc nội dung TXT/CSV/JSON/code, PDF, DOCX, XLSX và gửi ảnh dưới dạng input ảnh nếu model API hỗ trợ.
- Xem trước HTML/SVG/Markdown ở iframe sandbox; sao chép/tải code; xuất DOCX/XLSX/PPTX và văn bản/JSON/CSV/HTML; in sang PDF qua hộp thoại trình duyệt.
- Layout responsive cho desktop và điện thoại; hộp thoại thay nhiều thao tác `prompt()` cũ; tiến trình không phát lộ trường reasoning thô của model.

## Cấu trúc tệp

```text
Chantaodi/
├── app.py                  # Flask API, chat streaming, projects, workspace, export
├── database.py             # SQLite và truy vấn có ràng buộc owner
├── search_engine.py        # Adapters tìm kiếm song song, ranking và chẩn đoán
├── index.html              # Shell UI
├── static/
│   ├── app.css             # Thiết kế giao diện responsive
│   └── app.js              # UI, stream, project, search, workspace
├── tests/
│   ├── test_app.py         # API tests (AI/search mock)
│   └── test_search_engine.py
├── requirements.txt
├── render.yaml
├── .env.example
└── .gitignore
```

## Chạy cục bộ

Cần Python 3.11+ (khuyến nghị Python 3.12). Mở terminal ở thư mục này:

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\\Scripts\\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Cài thư viện và khởi chạy:

```bash
pip install -r requirements.txt
```

Sao chép `.env.example` thành `.env`, sau đó điền ít nhất một khóa API:

```dotenv
MOTAPIS_API_KEY=khóa_của_bạn
MOTAPIS_BASE_URL=https://motapis.com/v1
DEFAULT_MODEL=gpt-6-astra
APP_PASSWORD=mật_khẩu_dài_và_khó_đoán
DATABASE_PATH=data/chantaodi.sqlite3
WORKSPACE_DIR=data/workspace
```

Hoặc dùng API chính thức tương thích OpenAI:

```dotenv
OPENAI_API_KEY=khóa_của_bạn
OPENAI_BASE_URL=https://api.openai.com/v1
DEFAULT_MODEL=gpt-4.1-mini
```

Khóa API chỉ đặt trong biến môi trường, không ghi vào JavaScript hoặc commit lên GitHub. Khởi chạy:

```bash
python app.py
```

Mở `http://127.0.0.1:10000`.

## Cài trên GitHub + Render Web Service

1. Tải ZIP bản dựng lại này, giải nén và đưa **các tệp bên trong** vào một repository GitHub. Nên tạo branch/repository thử nghiệm trước thay vì ghi đè ngay ứng dụng cũ.
2. Render → **New → Web Service** → kết nối repository mới. Không cần Blueprint riêng; `render.yaml` chỉ là cấu hình tùy chọn.
3. Build command: `pip install -r requirements.txt`.
4. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180`.
5. Trong Render → Environment, đặt `MOTAPIS_API_KEY` và `MOTAPIS_BASE_URL` (hoặc `OPENAI_API_KEY` / `OPENAI_BASE_URL`). Đặt `DEFAULT_MODEL` là model mà nhà cung cấp của bạn thực sự cho phép. Khuyến nghị cấu hình `APP_PASSWORD` nếu dịch vụ được public.
6. Deploy xong, mở trang và kiểm tra biểu tượng trạng thái; dùng `/api/health` để kiểm tra cấu hình và nút “Kiểm tra API” nếu cần.

### Dữ liệu có bền sau khi Render restart không?

Cấu hình mặc định dùng thư mục `data/`, phù hợp chạy local và không đòi ổ đĩa riêng. Trên Render, filesystem thông thường có thể bị thay mới khi deploy/restart. Nếu muốn giữ lịch sử và workspace lâu dài, gắn Persistent Disk tại `/var/data` trong cấu hình dịch vụ, rồi đặt:

```dotenv
DATABASE_PATH=/var/data/chantaodi.sqlite3
WORKSPACE_DIR=/var/data/chantaodi-workspace
```

Kiểm tra lại quyền ghi sau khi gắn ổ đĩa.

## Khắc phục lỗi tìm kiếm

**UI hiển thị “Không lấy được kết quả từ web”** là lỗi trả về có chủ ý, không phải kết quả giả. Trang tìm kiếm sẽ chỉ rõ provider nào thành công/thất bại. Kiểm tra theo thứ tự:

1. Gửi POST tới `/api/search` (qua giao diện) và xem `provider_status`, `failed_providers`, `elapsed_ms`.
2. Nếu DuckDuckGo/Bing/Wikipedia cùng timeout, kiểm tra log Render và chính sách outbound networking. Các nguồn miễn phí không đảm bảo luôn cho phép traffic từ máy chủ cloud.
3. Để tăng độ ổn định, thêm `TAVILY_API_KEY` và/hoặc `BRAVE_SEARCH_API_KEY` trong Render Environment. Sau đó deploy lại. Không cần khóa API trong frontend.
4. Đối với câu hỏi cần thông tin mới, bật Research; hệ thống sẽ chạy thêm nhánh freshness và Google News. Hệ thống chỉ nói đã tìm nếu có kết quả thực sự.
5. Nếu API AI hoạt động nhưng Research thất bại, lỗi nằm ở provider tìm kiếm/network hoặc parser, không phải API chat.

`/api/health` chỉ xác nhận tính sẵn sàng/configuration tổng quát; endpoint `/api/search` là phép thử thực tế cho các nguồn tìm kiếm.

## Kiểm thử

```bash
python -m py_compile app.py database.py search_engine.py
node --check static/app.js
python -m unittest discover -s tests -v
```

Test tìm kiếm dùng mock và không tiêu tốn credit. `tests/test_app.py` cần cài Flask/OpenAI từ `requirements.txt`; các lần chat/diagnostics trong test không gọi nhà cung cấp thật. Để xác nhận triển khai production, cần thử thêm với API key/model thật và kiểm tra log Render.

## Giới hạn cần biết

- Session hiện tại là mã ngẫu nhiên lưu trong trình duyệt, chưa phải đăng nhập thật hay Google OAuth. Không nên dùng làm SaaS nhiều người dùng có dữ liệu nhạy cảm nếu chưa thêm auth, CSRF và quản lý phiên máy chủ.
- Không có sandbox chạy code tùy ý. AI có thể tạo/sửa mã và tệp nhưng không tự chạy build/test trong container ứng dụng.
- Bộ tìm kiếm HTML công khai vẫn có thể thay đổi markup hoặc rate-limit. Cấu hình API search có khóa giúp ổn định hơn.
- Chat history và workspace gắn với phiên trình duyệt này; xóa localStorage sẽ làm mất mã phiên truy cập dữ liệu phiên cũ.
- Khi chuyển bản dựng lại vào production, sao lưu SQLite/workspace cũ trước. Bộ khởi tạo hỗ trợ migrate bảng `messages` từ schema cũ dùng `conv_id` sang `conversation_id` và giữ `motapiSid` cũ để mở lại hội thoại cùng phiên. Hãy thử trên bản sao database trước; workspace cũ cần tiếp tục dùng `WORKSPACE_DIR` trước đây hoặc tự sao chép tệp sang workspace mới.
