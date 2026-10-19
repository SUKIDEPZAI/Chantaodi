#!/usr/bin/env python3
"""Apply a narrowly scoped, guarded MotAPI Studio model-catalog fix.

Usage:
  python apply_audit_fixes.py /path/to/Chantaodi          # dry-run
  python apply_audit_fixes.py /path/to/Chantaodi --apply  # write changes

The script intentionally refuses unexpected source versions and dirty Git trees.
It does not install dependencies, change deployment settings, or contact providers.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import subprocess
import sys

AUDIT_MARKER = "## Audit addendum — verified model catalog (2026-10-19)"

SERVER_MODELS = '''@app.get('/api/models')
def models():
    key = os.getenv('MOTAPIS_API_KEY', '').strip()
    if not key:
        return jsonify(models=[], source='blocked', error='Chưa cấu hình MOTAPIS_API_KEY.'), 503
    try:
        raw = _get(BASE() + '/models', 12, {'Authorization': f'Bearer {key}'})
        payload = json.loads(raw.decode('utf-8', 'replace'))
        records = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise ValueError('Invalid model catalog response')
        ids, seen = [], set()
        for item in records:
            if not isinstance(item, dict):
                continue
            model_id = item.get('id')
            if not isinstance(model_id, str):
                continue
            model_id = model_id.strip()
            if model_id and len(model_id) <= 120 and model_id not in seen:
                seen.add(model_id)
                ids.append(model_id)
        if not ids:
            return jsonify(models=[], source='provider-model-list', error='MộtAPI không trả về model khả dụng.'), 502
        return jsonify(models=[{'id': model_id, 'available': True} for model_id in ids], source='provider-model-list')
    except Exception as e:
        logging.warning('Model list unavailable: %s', type(e).__name__)
        return jsonify(models=[], source='unavailable', error='Không tải được danh sách model đã xác minh từ MộtAPI.'), 502
'''

INDEX_INIT_OLD = '''let list=FB;try{const d=await(await fetch('/api/models')).json(),l=(d.models||[]).map(x=>typeof x==='string'?x:x.id).filter(Boolean);if(l.length)list=l}catch{}
list.forEach(id=>{const o=document.createElement('option');o.value=o.textContent=id;modelEl.append(o)});modelEl.value=list.includes('gpt-6-astra')?'gpt-6-astra':list[0]}'''
INDEX_INIT_NEW = '''modelEl.disabled=true;modelEl.replaceChildren(new Option('Đang tải model…',''));
try{
const r=await fetch('/api/models'),d=await r.json();
const list=r.ok&&d.source==='provider-model-list'&&Array.isArray(d.models)?d.models.filter(x=>x&&x.available===true&&typeof x.id==='string').map(x=>x.id):[];
if(!list.length)throw new Error(d.error||'Không có model đã xác minh từ MộtAPI.');
modelEl.replaceChildren();list.forEach(id=>modelEl.add(new Option(id,id)));
modelEl.value=list.includes('gpt-6-astra')?'gpt-6-astra':list[0];modelEl.disabled=false;$('#send').disabled=false;
}catch(e){modelEl.replaceChildren(new Option('Không có model đã xác minh',''));modelEl.disabled=true;$('#send').disabled=true;$('#sideSt').textContent='Không tải được danh sách model';}
}'''

STATUS_ADDENDUM = '''

## Audit addendum — verified model catalog (2026-10-19)

- **Xác minh từ source:** Flask backend ở `server.py`; UI/CSS/JS nằm trong `index.html`; SQLite và API v2 ở `store.py`; workspace ở `files_routes.py`; xuất file ở `export_routes.py`; test tích hợp ở `test_app.py`.
- **Sửa trong patch này:** `/api/models` chỉ trả về các `id` nhận được trực tiếp từ `GET {MOTAPIS_BASE_URL}/models`, đánh dấu `available: true` cho các ID trong phản hồi đó, và trả lỗi rõ ràng khi thiếu key / không đọc được catalog. UI không còn dùng danh sách model hard-code làm fallback và khóa thao tác gửi khi không có model đã xác minh.
- **Bằng chứng hiện có:** MộtAPI docs mô tả `GET /v1/models` với Bearer API key; tests hiện tại mock provider. Thử nghiệm với MộtAPI thật vẫn cần `MOTAPIS_API_KEY` trong môi trường triển khai.
- **Chưa được xác minh trong phiên audit:** test suite đầy đủ, trình duyệt thật, tích hợp MộtAPI thật, deploy Render. Không coi patch là đã kiểm thử cho đến khi chạy lệnh ở README.
- **Rủi ro P0 còn lại:** `APP_PASSWORD` là cổng mật khẩu dùng chung và tùy chọn; `X-Session` do trình duyệt tự tạo và gửi về server, chưa phải đăng nhập/phiên xác thực có danh tính. Không coi cơ chế này là bảo vệ dữ liệu đủ dùng cho triển khai nhiều người dùng.
'''

ROADMAP_ADDENDUM = '''

## Audit addendum — next verified work (2026-10-19)

### Gói hiện tại: catalog model chỉ từ provider
- [x] Loại bỏ các model ID hard-code khỏi kết quả `/api/models`.
- [x] Không hiển thị model không được MộtAPI xác nhận trong `index.html`.
- [x] Thêm test mock xác minh chỉ hiển thị ID từ catalog provider và fail-closed khi thiếu key.
- [ ] Chạy `python -m unittest -v test_app` trên checkout thật.
- [ ] Khi đã có key: kiểm tra `GET /api/models`, gửi chat end-to-end và xác nhận model ID thật.

### Ưu tiên sau đó
1. **P0 — Authentication:** thiết kế đăng nhập và session cookie server-side; không coi `X-Session` là danh tính. Thêm CSRF protection nếu dùng cookie, rate limit phù hợp và test cô lập người dùng.
2. **P1 — Chat reliability:** kiểm tra retry/idempotency ở cấp request và lưu message khi stream bị hủy/lỗi; thêm test không phát sinh phản hồi trùng.
3. **P1 — UI regression:** kiểm tra trình duyệt cho chat, đổi tên/ghim/lưu trữ/xóa, projects, file workspace, panel preview và trạng thái thiếu API key/model.
4. **P1 — Deploy/data:** xác minh `DATABASE_PATH` và `WORKSPACE_DIR` trỏ đến persistent disk trên Render trước khi dùng dữ liệu quan trọng.
5. **P2 — Product scope:** project detail UI, artifact version controls, coding task orchestration chỉ sau khi các luồng P0/P1 ổn định.
'''

HANDOFF_ADDENDUM = '''

## Audit addendum — 2026-10-19

- **Kết quả đối chiếu:** repository dùng Flask + một `index.html` thuần JS/CSS + SQLite; không có frontend build step trong manifest hiện có. Source liên quan: `server.py`, `store.py`, `files_routes.py`, `export_routes.py`, `test_app.py`, `index.html`.
- **Thay đổi được chuẩn bị:** sửa catalog model để chỉ hiển thị model trả về từ MộtAPI và thêm regression tests. Script mặc định chạy dry-run; cần xem diff trước khi commit.
- **Chưa áp dụng từ phiên này:** GitHub integration từ chối tạo branch với 403 `Resource not accessible by integration`; không có commit nào được tạo từ phiên audit.
- **Kiểm thử:** không chạy được trên checkout remote từ container do môi trường không phân giải được `github.com`. Số test lịch sử trong handoff trước là 11/11 với provider mock; kết quả đó chưa được chạy lại trong phiên này.
- **Bước tiếp theo:** tải repo xuống môi trường có quyền ghi, chạy script này ở chế độ dry-run; xem `git diff`; chạy `python -m unittest -v test_app`; sau đó kiểm thử API thật khi có key. Tiếp theo triển khai authentication thực trước khi chia sẻ app cho nhiều người.
- **Không làm lại:** không đổi stack; không xóa hoặc viết lại schema SQLite; không thay nhà cung cấp AI.
'''

AUDIT_REPORT = '''# Báo cáo tiếp quản — Chantaodi / MotAPI Studio v3

Ngày audit: 2026-10-19  
Repository: https://github.com/SUKIDEPZAI/Chantaodi  
Phạm vi kiểm tra: cấu trúc file, source backend, giao diện, DB, cấu hình deploy, tests và tài liệu hiện có.

## 1. Bản đồ kiến trúc thực tế

| Thành phần | Vị trí | Xác minh |
|---|---|---|
| Tên sản phẩm | `README.md`, `index.html` | MotAPI Studio v3 / title MotAPI Studio |
| Backend + API | `server.py` | Flask, routes `/api/chat`, `/api/models`, `/api/diagnostics`, `/api/search`, `/api/health` |
| UI | `index.html` | HTML/CSS/JS thuần, dark theme, sidebar, chat, model selector, workspace file, context preview |
| Persistence | `store.py` | SQLite; schema tự khởi tạo khi import; API v2 cho conversations/projects/artifacts |
| Workspace files | `files_routes.py` | upload/list/read/download/save/delete/zip và giải nén có giới hạn |
| Export | `export_routes.py` | endpoint `/api/export`, hỗ trợ docx/xlsx/pptx/rtf |
| Tests | `test_app.py` | unittest; provider được mock; test persistence, owner scoping, projects, files, artifacts, rate limit/import |
| Dependencies | `requirements.txt` | Flask, Gunicorn, OpenAI SDK, xử lý PDF/DOCX/XLSX/PPTX/7z |
| Deploy | `render.yaml` | Render Python web service, Gunicorn một worker/bốn threads |
| Cấu hình mẫu | `.env.example` | `MOTAPIS_API_KEY`, `MOTAPIS_BASE_URL`, `APP_PASSWORD`, đường dẫn DB/workspace |

## 2. Trạng thái tính năng

| Hạng mục | Trạng thái | Bằng chứng/vị trí | Việc còn thiếu | Ưu tiên |
|---|---|---|---|---|
| UI shell/sidebar | PARTIAL | `index.html` | Chưa có xác minh browser; sidebar desktop chưa thu gọn chuẩn | P1 |
| Chat/stream/stop | PARTIAL | `server.py` `/api/chat`, `index.html` `send()` | Mock tests có; chưa kiểm tra browser hoặc provider thật | P1 |
| MộtAPI | PARTIAL / BLOCKED live test | `server.py` `client()`, `/api/chat`, `/api/models` | Thiếu key trong môi trường audit; catalog từng trộn ID hard-code | P0/P1 |
| Persistence | DONE theo tests hiện có (mock) | `store.py`, `test_app.py` | Chưa rerun tests; SQLite cần persistent disk khi deploy | P1 |
| Conversation management | PARTIAL UI / API có | `store.py` `/api/v2/conversations*`, `index.html` | Dùng `prompt()`/confirm; archive UI còn thiếu | P1/P2 |
| Projects | PARTIAL | `store.py` project routes, `index.html` | Chưa có project detail page; UI form tạm thời | P1 |
| Files/workspace | PARTIAL (có API) | `files_routes.py`, `index.html` | Workspace theo `X-Session`, không gắn vào identity/login | P1 |
| Artifacts | PARTIAL | `store.py` artifact/version API, preview iframe trong `index.html` | UI chưa hoàn chỉnh cho version/edit/restore | P1 |
| Coding agent/workspace | MISSING | Chưa thấy backend task orchestration trong file được kiểm tra | Task state, allowlist, sandbox và diff apply | P2 |
| Authentication | MISSING | `server.py` `gate()`, `index.html` `X-Session` | `APP_PASSWORD` dùng chung và tùy chọn; chưa có identity/session server-side | P0 khi triển khai công khai/nhiều người dùng |
| Security | PARTIAL | `server.py`, `files_routes.py`, `store.py` | Cần threat-model auth/CSRF, SSRF redirect validation, CSP, audit logging | P0/P1 |
| Tests | PARTIAL | `test_app.py` | Mock-only; chưa có browser E2E, provider thật hoặc deploy smoke test | P1 |

## 3. Lỗi đã xác minh trong source

`server.py` khai báo danh sách `MODELS` hard-code. `/api/models` ghép các model đó với `GET /models` của provider; kể cả khi response provider tồn tại, UI chỉ lấy `id` và không lọc `available: false`. Do đó model không có trong catalog MộtAPI vẫn có thể xuất hiện trong selector. Patch đi kèm sửa hành vi này theo hướng fail-closed và bổ sung regression tests.

## 4. Bảo mật và giới hạn

- `MOTAPIS_API_KEY` dùng phía server qua OpenAI SDK với base URL mặc định `https://motapis.com/v1`; không phát hiện key trong mã UI được xem. Key thật vẫn phải được đặt trong secret manager/Render env, không commit.
- `APP_PASSWORD` là cổng bảo vệ tùy chọn với mật khẩu chung, không thay thế đăng nhập có danh tính.
- Data owner hiện dựa trên `X-Session` do client gửi. Đây là phân vùng theo bearer token do trình duyệt tự sinh, không phải xác thực người dùng; không coi là đủ cho hệ thống nhiều người dùng hoặc dữ liệu nhạy cảm.
- `fetch_links()` có kiểm tra IP ban đầu, nhưng chuyển hướng HTTP cần được kiểm tra lại đích để giảm nguy cơ SSRF qua redirect.
- Cần dùng persistent disk cho `DATABASE_PATH`/`WORKSPACE_DIR` nếu muốn dữ liệu sống sót qua restart trên môi trường có filesystem tạm thời.

## 5. Kiểm tra và giới hạn của audit

- Tài liệu repo nêu lệnh test: `python -m unittest -v test_app`.
- `test_app.py` mock `server.client`; tests lịch sử ghi trong `HANDOFF.md` là 11/11 pass. Phiên audit này không chạy lại được do không thể clone checkout trong môi trường hiện tại.
- Tài liệu MộtAPI hiện mô tả `GET /v1/models` với Bearer auth và `POST /v1/chat/completions` hỗ trợ `stream: true` SSE. Điều đó xác minh giao thức tài liệu, không xác minh credentials hoặc quyền model cụ thể của tài khoản.
- GitHub write operation bị từ chối (403); vì vậy không có thay đổi nào được commit trực tiếp lên repository trong phiên này.

## 6. Lệnh xác minh sau khi áp dụng patch

```bash
python -m unittest -v test_app
python -m py_compile server.py store.py files_routes.py export_routes.py test_app.py
```

Sau khi cấu hình key ở môi trường riêng: kiểm tra `/api/health`, `/api/models`, nút “Kiểm tra API”, một chat thật và mở lại conversation. Không đưa API key vào source, Issue, log công khai hay handoff.
'''


def replace_once(path: Path, src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match for {label} in {path.name}; found {count}. No files were written.")
    return src.replace(old, new, 1)


def prepare(root: Path) -> dict[Path, str]:
    changes: dict[Path, str] = {}

    server_path = root / "server.py"
    server = server_path.read_text(encoding="utf-8")
    models_line = "MODELS = ['DeepSeek-V4-Flash-0731', 'claude-sonnet-4-6', 'claude-sonnet-5', 'claude-sonnet-5-5', 'deepseek-v4-flash', 'glm-5.3-flash', 'gpt-5.6-sol', 'gpt-6-astra', 'gpt-6-luna', 'gpt-6-sol', 'grok-4.5', 'grok-4.6', 'hy3', 'hy4-preview', 'minimax-m2.7', 'minimax-m3', 'qwen3.8-max']\n"
    server = replace_once(server_path, server, models_line, "", "hard-coded MODELS catalog")
    old_models_fn = """@app.get('/api/models')
def models():
    key = os.getenv('MOTAPIS_API_KEY', '').strip(); fallback = jsonify(models=[{'id': m, 'available': None} for m in MODELS], source='configured-list')
    if not key: return fallback
    try:
        d = json.loads(_get(BASE() + '/models', 12, {'Authorization': f'Bearer {key}'}).decode())
        actual = {str(x.get('id')) for x in d.get('data', []) if isinstance(x, dict) and x.get('id')}
        allm = MODELS + [x for x in sorted(actual) if x not in MODELS]
        return jsonify(models=[{'id': m, 'available': (m in actual) if actual else None} for m in allm], source='provider-model-list' if actual else 'configured-list')
    except Exception as e:
        logging.warning('Model list unavailable: %s', type(e).__name__); return fallback
"""
    server = replace_once(server_path, server, old_models_fn, SERVER_MODELS, "model catalog endpoint")
    server = replace_once(server_path, server,
        "d = request.get_json(silent=True) or {}; model = str(d.get('model') or 'gpt-6-astra').strip()[:120]\n",
        "d = request.get_json(silent=True) or {}; model = str(d.get('model') or '').strip()[:120]\n    if not model: return jsonify(ok=False, error='Chọn một model đã xác minh trước khi kiểm tra API.'), 400\n",
        "diagnostics model default")
    server = replace_once(server_path, server,
        "message = request.form.get('message', '').strip(); model = request.form.get('model', 'gpt-6-astra').strip(); mode = request.form.get('mode', 'chat')\n",
        "message = request.form.get('message', '').strip(); model = request.form.get('model', '').strip(); mode = request.form.get('mode', 'chat')\n",
        "chat model default")
    changes[server_path] = server

    index_path = root / "index.html"
    index = index_path.read_text(encoding="utf-8")
    index, n = re.subn(r"const FB=\[[^\n]*\];\n", "", index)
    if n != 1:
        raise RuntimeError(f"Expected exactly one hard-coded frontend model fallback in index.html; found {n}. No files were written.")
    index = replace_once(index_path, index, INDEX_INIT_OLD, INDEX_INIT_NEW, "frontend model initialization")
    index = replace_once(index_path, index,
        "async function send(){const text=prompt_.value.trim();if(!text&&!files.length)return;if(ctl)return toast('Đang xử lý. Hãy đợi hoặc bấm Dừng.');",
        "async function send(){const text=prompt_.value.trim();if(!text&&!files.length)return;if(!modelEl.value)return toast('Chưa có model đã xác minh từ MộtAPI. Kiểm tra API key và tải lại trang.');if(ctl)return toast('Đang xử lý. Hãy đợi hoặc bấm Dừng.');",
        "send guard")
    index = replace_once(index_path, index,
        "finally{clearInterval(tick);cancelAnimationFrame(raf);$('#send').disabled=false;$('#stop').classList.add('hidden');ctl=null;prompt_.focus()}}",
        "finally{clearInterval(tick);cancelAnimationFrame(raf);$('#send').disabled=!modelEl.value;$('#stop').classList.add('hidden');ctl=null;prompt_.focus()}}",
        "send finally button state")
    index = replace_once(index_path, index,
        "$('#testApi').onclick=async()=>{const b=$('#testApi');b.disabled=true;",
        "$('#testApi').onclick=async()=>{if(!modelEl.value)return toast('Chưa có model đã xác minh từ MộtAPI.');const b=$('#testApi');b.disabled=true;",
        "diagnostics UI guard")
    changes[index_path] = index

    test_path = root / "test_app.py"
    tests = test_path.read_text(encoding="utf-8")
    tests = replace_once(test_path, tests,
        "from types import SimpleNamespace as NS\n",
        "from types import SimpleNamespace as NS\nfrom unittest.mock import patch\n",
        "test patch import")
    anchor = "if __name__ == '__main__': unittest.main()"
    extra_tests = '''    def test_models_only_lists_verified_provider_catalog(self):
        payload = b'{"data":[{"id":"model-z"},{"id":"model-a"},{"id":"model-z"}]}'
        with patch.object(server, '_get', return_value=payload):
            r = c.get('/api/models')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual([x['id'] for x in data['models']], ['model-z', 'model-a'])
        self.assertTrue(all(x['available'] is True for x in data['models']))
        self.assertEqual(data['source'], 'provider-model-list')

    def test_models_fail_closed_without_api_key(self):
        with patch.dict(os.environ, {'MOTAPIS_API_KEY': ''}):
            r = c.get('/api/models')
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json()['models'], [])

'''
    tests = replace_once(test_path, tests, anchor, extra_tests + anchor, "model catalog regression tests anchor")
    changes[test_path] = tests

    for name, addendum in (("PROJECT_STATUS.md", STATUS_ADDENDUM),
                           ("IMPLEMENTATION_ROADMAP.md", ROADMAP_ADDENDUM),
                           ("HANDOFF.md", HANDOFF_ADDENDUM)):
        p = root / name
        content = p.read_text(encoding="utf-8")
        if AUDIT_MARKER in content:
            raise RuntimeError(f"Audit addendum already exists in {name}; refusing to duplicate it. No files were written.")
        changes[p] = content.rstrip() + "\n" + addendum

    report_path = root / "AUDIT_FINDINGS.md"
    if report_path.exists():
        raise RuntimeError("AUDIT_FINDINGS.md already exists; refusing to overwrite it. No files were written.")
    changes[report_path] = AUDIT_REPORT
    return changes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo", type=Path, help="Path to a local Chantaodi checkout")
    ap.add_argument("--apply", action="store_true", help="Write changes (otherwise only validate matches)")
    ap.add_argument("--allow-dirty", action="store_true", help="Permit a dirty Git worktree; use only after inspecting it")
    args = ap.parse_args()
    root = args.repo.resolve()
    if not root.is_dir() or not (root / ".git").exists():
        print(f"ERROR: {root} is not a Git checkout.", file=sys.stderr); return 2
    try:
        if not args.allow_dirty:
            result = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], check=True, capture_output=True, text=True)
            if result.stdout.strip():
                print("ERROR: Git worktree is not clean. Review/commit/stash existing work first; no files were written.", file=sys.stderr)
                print(result.stdout, file=sys.stderr); return 2
        changes = prepare(root)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 2

    print("Validated changes:")
    for p in sorted(changes):
        before = p.read_text(encoding="utf-8") if p.exists() else ""
        print(f"  {p.name}: {'new file' if not p.exists() else 'update'} ({len(before)} -> {len(changes[p])} characters)")
    if not args.apply:
        print("\nDry-run only. Review these changes, then rerun with --apply to write them.")
        return 0

    for p, content in changes.items():
        p.write_text(content, encoding="utf-8", newline="\n")
    print("\nApplied. Review with git diff, then run:")
    print("  python -m unittest -v test_app")
    print("  python -m py_compile server.py store.py files_routes.py export_routes.py test_app.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
