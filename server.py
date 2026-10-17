
import os
import json
import base64
import mimetypes
import logging

from io import BytesIO
from flask import Flask, request, jsonify, send_from_directory
from openai import (
    OpenAI,
    APIStatusError,
    APIConnectionError,
    APITimeoutError,
)
from werkzeug.exceptions import RequestEntityTooLarge

ROOT = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("highway-ai")

app = Flask(__name__, static_folder=None)

# Tổng dung lượng upload của một request.
# Có thể điều chỉnh MAX_UPLOAD_MB trong Render Environment.
MAX_UPLOAD_MB = max(
    1, int(os.getenv("MAX_UPLOAD_MB", "25"))
)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

DEFAULT_BASE_URL = "https://api.highwayapi.ai/openai/v1"
DEFAULT_MODEL = "gpt-6-astra"


def get_client():
    """Khởi tạo client bằng API key lưu trên Render."""
    api_key = os.getenv("HIGHWAY_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError(
            "Chưa cấu hình HIGHWAY_API_KEY trong "
            "Render Dashboard > Environment."
        )

    base_url = os.getenv(
        "HIGHWAY_BASE_URL", DEFAULT_BASE_URL
    ).strip().rstrip("/")

    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=float(os.getenv("AI_TIMEOUT", "120")),
        max_retries=0,
    )


def extract_document(upload):
    """
    Đọc tệp văn bản, PDF, DOCX hoặc ảnh.
    Tệp được xử lý trong bộ nhớ, không lưu lâu dài.
    """
    filename = upload.filename or "uploaded_file"
    extension = os.path.splitext(filename)[1].lower()

    mime = (
        upload.mimetype
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    ).lower()

    raw = upload.read()

    text_extensions = {
        ".txt", ".md", ".csv", ".json", ".py",
        ".js", ".ts", ".html", ".css", ".xml",
        ".yaml", ".yml", ".log", ".sql", ".toml",
        ".ini", ".sh", ".java", ".c", ".cpp",
        ".h", ".hpp", ".rs", ".go", ".php",
        ".rb", ".vue", ".jsx", ".tsx"
    }

    if extension in text_extensions:
        return {
            "kind": "text",
            "name": filename,
            "text": raw.decode("utf-8", errors="replace"),
        }

    if extension == ".pdf" or mime == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(raw))
            content = "\n".join(
                page.extract_text() or ""
                for page in reader.pages
            )

            return {
                "kind": "text",
                "name": filename,
                "text": content or (
                    "[PDF không có lớp văn bản trích xuất được. "
                    "PDF scan cần OCR.]"
                ),
            }
        except Exception:
            logger.exception("PDF extraction failed")
            return {
                "kind": "text",
                "name": filename,
                "text": "[Không đọc được nội dung PDF.]",
            }

    if extension == ".docx":
        try:
            from docx import Document

            document = Document(BytesIO(raw))
            paragraphs = [
                paragraph.text
                for paragraph in document.paragraphs
            ]

            return {
                "kind": "text",
                "name": filename,
                "text": "\n".join(paragraphs),
            }
        except Exception:
            logger.exception("DOCX extraction failed")
            return {
                "kind": "text",
                "name": filename,
                "text": "[Không đọc được nội dung DOCX.]",
            }

    if mime.startswith("image/") or extension in {
        ".png", ".jpg", ".jpeg", ".webp", ".gif"
    }:
        if not mime.startswith("image/"):
            mime = mimetypes.guess_type(filename)[0] or "image/jpeg"

        encoded = base64.b64encode(raw).decode("ascii")

        return {
            "kind": "image",
            "name": filename,
            "url": f"data:{mime};base64,{encoded}",
        }

    return {
        "kind": "text",
        "name": filename,
        "text": (
            f"[Tệp {filename}, {len(raw)} byte. "
            "Định dạng này chưa được trích xuất tự động.]"
        ),
    }


def normalize_history(raw_history):
    """Chỉ nhận các tin nhắn hợp lệ từ lịch sử trình duyệt."""
    try:
        history = json.loads(raw_history or "[]")
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(history, list):
        return []

    result = []

    for item in history[-12:]:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = item.get("content")

        if role not in ("user", "assistant"):
            continue

        if not isinstance(content, str):
            continue

        result.append({
            "role": role,
            "content": content[:12000],
        })

    return result


def safe_provider_error(exc):
    """
    Chuyển lỗi API thành thông báo dễ hiểu.
    Không trả API key hoặc header xác thực về trình duyệt.
    """
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)

    code = ""
    message = ""

    if isinstance(body, dict):
        code = str(body.get("code", "") or "")
        message = str(
            body.get("message", "")
            or body.get("error", "")
            or ""
        )

        # Một số API đặt mã lỗi bên trong object error.
        nested = body.get("error")
        if isinstance(nested, dict):
            code = str(
                nested.get("code", code) or code
            )
            message = str(
                nested.get("message", message) or message
            )

    raw = str(exc)

    if not code:
        if "NOT_ENOUGH_BALANCE" in raw:
            code = "NOT_ENOUGH_BALANCE"

    if code == "NOT_ENOUGH_BALANCE":
        return {
            "status": 402,
            "code": code,
            "error": (
                "Tài khoản API không đủ số dư. "
                "Hãy kiểm tra credit, hạn mức và trạng thái "
                "thanh toán tại nhà cung cấp Highway AI."
            ),
        }

    if status == 401:
        return {
            "status": 502,
            "code": "UPSTREAM_AUTH_ERROR",
            "error": (
                "Nhà cung cấp từ chối xác thực API. "
                "Kiểm tra HIGHWAY_API_KEY trên Render."
            ),
        }

    if status == 403:
        return {
            "status": 502,
            "code": "UPSTREAM_FORBIDDEN",
            "error": (
                "API từ chối yêu cầu. Kiểm tra số dư, "
                "quyền truy cập model và trạng thái tài khoản."
            ),
        }

    if status == 404:
        return {
            "status": 502,
            "code": "MODEL_OR_ENDPOINT_NOT_FOUND",
            "error": (
                "Không tìm thấy model hoặc endpoint. "
                "Kiểm tra HIGHWAY_MODEL và HIGHWAY_BASE_URL."
            ),
        }

    if status == 429:
        return {
            "status": 429,
            "code": "RATE_LIMIT",
            "error": (
                "API đang giới hạn tần suất hoặc hạn mức. "
                "Hãy kiểm tra quota và thử lại sau."
            ),
        }

    if status in (400, 422):
        return {
            "status": 400,
            "code": "INVALID_REQUEST",
            "error": (
                "API không chấp nhận yêu cầu. "
                "Kiểm tra model, tham số và định dạng ảnh."
            ),
        }

    if status is not None and status >= 500:
        return {
            "status": 502,
            "code": "UPSTREAM_ERROR",
            "error": (
                "Máy chủ API đang gặp lỗi. "
                "Hãy thử lại sau."
            ),
        }

    if isinstance(exc, APITimeoutError):
        return {
            "status": 504,
            "code": "API_TIMEOUT",
            "error": "API phản hồi quá lâu. Hãy thử lại.",
        }

    if isinstance(exc, APIConnectionError):
        return {
            "status": 502,
            "code": "API_CONNECTION_ERROR",
            "error": (
                "Không thể kết nối tới nhà cung cấp API. "
                "Kiểm tra endpoint và kết nối mạng của Render."
            ),
        }

    logger.error(
        "Unexpected API error: %s",
        type(exc).__name__,
    )

    return {
        "status": 502,
        "code": "API_ERROR",
        "error": (
            "Yêu cầu AI thất bại. Kiểm tra log của Render "
            "để biết thêm chi tiết."
        ),
    }


@app.get("/")
def home():
    return send_from_directory(ROOT, "index.html")


@app.get("/api/health")
def health():
    # Không gọi API tính phí chỉ để kiểm tra trạng thái.
    return jsonify({
        "ok": True,
        "api_key_configured": bool(
            os.getenv("HIGHWAY_API_KEY", "").strip()
        ),
        "model": os.getenv(
            "HIGHWAY_MODEL", DEFAULT_MODEL
        ),
    })


@app.post("/api/chat")
def chat():
    message = request.form.get("message", "").strip()
    history = normalize_history(
        request.form.get("history", "[]")
    )

    uploaded_files = request.files.getlist("files")

    if not message and not uploaded_files:
        return jsonify({
            "error": "Hãy nhập tin nhắn hoặc đính kèm tệp.",
            "code": "EMPTY_MESSAGE",
        }), 400

    try:
        attachments = [
            extract_document(upload)
            for upload in uploaded_files
            if upload and upload.filename
        ]

        prompt = message or (
            "Hãy xem xét các tệp và ảnh đính kèm, "
            "sau đó hỗ trợ tôi."
        )

        user_content = [{
            "type": "text",
            "text": prompt,
        }]

        for item in attachments:
            if item["kind"] == "image":
                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": item["url"],
                    },
                })
            else:
                user_content[0]["text"] += (
                    f"\n\n--- Tệp: {item['name']} ---\n"
                    f"{item['text']}"
                )

        messages = [{
            "role": "system",
            "content": os.getenv(
                "AI_SYSTEM_PROMPT",
                "Bạn là trợ lý AI hữu ích. "
                "Trả lời bằng tiếng Việt khi phù hợp.",
            ),
        }]

        messages.extend(history)
        messages.append({
            "role": "user",
            "content": user_content,
        })

        model = os.getenv(
            "HIGHWAY_MODEL", DEFAULT_MODEL
        ).strip()

        max_tokens = max(
            1,
            int(os.getenv("AI_MAX_TOKENS", "4096")),
        )

        temperature = float(
            os.getenv("AI_TEMPERATURE", "1")
        )

        api = get_client()

        response = api.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        reply = response.choices[0].message.content

        if not reply:
            reply = "AI không trả về nội dung."

        if not isinstance(reply, str):
            reply = str(reply)

        return jsonify({
            "reply": reply,
            "model": model,
        })

    except APIStatusError as exc:
        result = safe_provider_error(exc)

        logger.warning(
            "Provider API error: status=%s code=%s",
            getattr(exc, "status_code", None),
            result["code"],
        )

        return jsonify({
            "error": result["error"],
            "code": result["code"],
        }), result["status"]

    except (APIConnectionError, APITimeoutError) as exc:
        result = safe_provider_error(exc)

        return jsonify({
            "error": result["error"],
            "code": result["code"],
        }), result["status"]

    except RuntimeError as exc:
        # Ví dụ: chưa cấu hình API key.
        return jsonify({
            "error": str(exc),
            "code": "SERVER_CONFIGURATION_ERROR",
        }), 500

    except Exception:
        logger.exception("Unexpected /api/chat failure")

        return jsonify({
            "error": (
                "Máy chủ xử lý yêu cầu thất bại. "
                "Kiểm tra log của Render."
            ),
            "code": "INTERNAL_SERVER_ERROR",
        }), 500


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(_exc):
    return jsonify({
        "error": (
            f"Tổng dung lượng upload vượt giới hạn "
            f"{MAX_UPLOAD_MB} MB mỗi yêu cầu. "
            "Hãy giảm kích thước tệp hoặc điều chỉnh "
            "MAX_UPLOAD_MB nếu máy chủ cho phép."
        ),
        "code": "UPLOAD_TOO_LARGE",
    }), 413


@app.errorhandler(404)
def handle_not_found(_exc):
    return jsonify({
        "error": "Không tìm thấy đường dẫn yêu cầu.",
        "code": "NOT_FOUND",
    }), 404


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
