import os
import json
import base64
import mimetypes
from io import BytesIO
from flask import Flask, request, jsonify, send_from_directory
from openai import OpenAI

ROOT = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=None)
# No app-level file-count limit. Hosting providers and memory still impose practical limits.
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024

def client():
    key = os.getenv("HIGHWAY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Chưa cấu hình biến môi trường HIGHWAY_API_KEY trên Render.")
    return OpenAI(api_key=key, base_url=os.getenv(
        "HIGHWAY_BASE_URL", "https://api.highwayapi.ai/openai/v1"
    ))

def extract_document(file):
    name = file.filename or "file"
    raw = file.read()
    mime = (file.mimetype or mimetypes.guess_type(name)[0] or "").lower()
    ext = os.path.splitext(name)[1].lower()
    if ext in {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".css", ".xml", ".yaml", ".yml", ".log", ".sql"}:
        return {"kind": "text", "name": name, "text": raw.decode("utf-8", errors="replace")}
    if ext == ".pdf" or mime == "application/pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(raw))
            return {"kind": "text", "name": name, "text": "\n".join(p.extract_text() or "" for p in reader.pages)}
        except Exception as e:
            return {"kind": "text", "name": name, "text": f"[Không đọc được PDF: {e}]"}
    if ext == ".docx":
        try:
            from docx import Document
            doc = Document(BytesIO(raw))
            return {"kind": "text", "name": name, "text": "\n".join(p.text for p in doc.paragraphs)}
        except Exception as e:
            return {"kind": "text", "name": name, "text": f"[Không đọc được DOCX: {e}]"}
    if mime.startswith("image/") or ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        mime = mime if mime.startswith("image/") else (mimetypes.guess_type(name)[0] or "image/jpeg")
        encoded = base64.b64encode(raw).decode("ascii")
        return {"kind": "image", "name": name, "url": f"data:{mime};base64,{encoded}"}
    return {"kind": "text", "name": name, "text": f"[Tệp {name}, {len(raw)} byte: định dạng chưa được trích xuất tự động.]"}

@app.get("/")
def home():
    return send_from_directory(ROOT, "index.html")

@app.get("/api/health")
def health():
    return jsonify({"ok": True, "configured": bool(os.getenv("HIGHWAY_API_KEY"))})

@app.post("/api/chat")
def chat():
    try:
        message = request.form.get("message", "").strip()
        try:
            history = json.loads(request.form.get("history", "[]"))
            if not isinstance(history, list):
                history = []
        except json.JSONDecodeError:
            history = []
        attachments = [extract_document(f) for f in request.files.getlist("files")]
        user_content = []
        prompt = message or "Hãy xem xét các tệp/ảnh đính kèm và hỗ trợ tôi."
        # Images use OpenAI-compatible vision content format. Provider/model must support images.
        user_content.append({"type": "text", "text": prompt})
        for item in attachments:
            if item["kind"] == "image":
                user_content.append({"type": "image_url", "image_url": {"url": item["url"]}})
            else:
                # Keep each file's extracted content clearly labelled.
                user_content[0]["text"] += f"\n\n--- Tệp: {item['name']} ---\n{item['text']}"
        messages = [{"role": "system", "content": os.getenv(
            "AI_SYSTEM_PROMPT", "Bạn là trợ lý AI hữu ích. Trả lời bằng tiếng Việt khi phù hợp."
        )}]
        for m in history[-12:]:
            if isinstance(m, dict) and m.get("role") in {"user", "assistant"} and isinstance(m.get("content"), str):
                messages.append({"role": m["role"], "content": m["content"][:12000]})
        messages.append({"role": "user", "content": user_content})
        response = client().chat.completions.create(
            model=os.getenv("HIGHWAY_MODEL", "gpt-6-astra"),
            messages=messages,
            temperature=float(os.getenv("AI_TEMPERATURE", "1")),
            max_tokens=int(os.getenv("AI_MAX_TOKENS", "4096"))
        )
        reply = response.choices[0].message.content or ""
        return jsonify({"reply": reply})
    except Exception as e:
        app.logger.exception("Chat API failed")
        return jsonify({"error": str(e)}), 500

@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": f"Tệp tải lên vượt giới hạn máy chủ ({app.config['MAX_CONTENT_LENGTH']//(1024*1024)} MB mỗi yêu cầu). Có thể đổi MAX_UPLOAD_MB trong Render."}), 413

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
