# CODE REVIEW — SUKIDEPZAI/Chantaodi (MotAPI Studio v3)

Review basis: public source on branch `main` inspected on 2026-10-19. File line numbers below refer to the version fetched during this review; check the current branch before applying patches.

- [`server.py`](https://github.com/SUKIDEPZAI/Chantaodi/blob/main/server.py) — 348 lines
- [`index.html`](https://github.com/SUKIDEPZAI/Chantaodi/blob/main/index.html) — 182 lines, many sections minified into very long lines
- [`store.py`](https://github.com/SUKIDEPZAI/Chantaodi/blob/main/store.py) — 261 lines
- [`files_routes.py`](https://github.com/SUKIDEPZAI/Chantaodi/blob/main/files_routes.py) — 234 lines
- [`export_routes.py`](https://github.com/SUKIDEPZAI/Chantaodi/blob/main/export_routes.py) — 80 lines
- [`test_app.py`](https://github.com/SUKIDEPZAI/Chantaodi/blob/main/test_app.py) — 77 lines
- [`requirements.txt`](https://github.com/SUKIDEPZAI/Chantaodi/blob/main/requirements.txt), [`render.yaml`](https://github.com/SUKIDEPZAI/Chantaodi/blob/main/render.yaml), [`PROJECT_STATUS.md`](https://github.com/SUKIDEPZAI/Chantaodi/blob/main/PROJECT_STATUS.md), [`IMPLEMENTATION_ROADMAP.md`](https://github.com/SUKIDEPZAI/Chantaodi/blob/main/IMPLEMENTATION_ROADMAP.md)

## Priority findings

| Priority | Location | Finding | Risk / impact | Proposed treatment |
|---|---|---|---|---|
| P0 | `store.py` owner/session helpers; `server.py` `gate()` | `X-Session` is a client-generated owner token, not real authentication. `APP_PASSWORD` is one shared gate if configured. | Fine for a personal prototype; not suitable for multiple unrelated users or private data. A leaked session identifier can expose that session's conversations/files. | Add real sign-in, server-side sessions, CSRF protection, logout/revocation and per-user authorization before opening to the public. Not automatically fabricated by this patch. |
| P1 | `server.py:100-137`, `server.py:258+` | Search scraping uses fixed regular expressions, gathers results from providers regardless of relevance, and performs the search before the stream response begins. | Provider page changes can break extraction; duplicated/off-topic results; long wait before the browser sees progress. | Included in upgrade script: concurrent provider/branch searches, query expansion in Research mode, deduplication, relevance scoring, time budget, streamed progress. Network availability and provider changes still need live tests. |
| P1 | `server.py:139-163` | URL input validates the initial hostname/IP, but urllib's automatic redirects were not revalidated. | A public URL could redirect to a private/internal target. DNS rebinding is a residual consideration even after redirect checks. | Included: re-check redirect targets. For higher-assurance deployments, fetch through an isolated proxy that pins DNS resolution and blocks internal ranges at the network layer. |
| P1 | `files_routes.py:~120-170` | After archive extraction, the code could only emit a warning if total workspace usage exceeded `MAX_TOTAL`; extracted files were already written. | Workspace can exceed configured total size, increasing disk pressure. | Included: remove extracted output and retain the original archive if extraction crosses the workspace limit. Separate risk remains around archive formats that call `extractall()` before post-processing. |
| P1 | `export_routes.py:10-20` and `server.py` stream handler | The output protocol explicitly instructed the model to write `<think>…</think>`, while the main system prompt says not to disclose internal reasoning. `server.py` also streamed `reasoning_content`/`reasoning` fields to the browser. | Conflicting instructions; raw reasoning may appear in the UI and be saved to history. | Included: remove the contradictory `<think>` instruction, stop forwarding/saving provider reasoning fields, and hide legacy `<think>` blocks in the UI. |
| P1 | `store.py:~20-70`, `server.py:/api/chat` | SQLite path defaults to the temporary directory; rate limiting is process-local. Conversations are persisted, but a Render restart can lose data unless a persistent disk/path is configured. | Data loss on ephemeral storage; rate limit can be bypassed across multiple workers or by changing sessions. | Set `DATABASE_PATH` and `WORKSPACE_DIR` to a mounted Render Disk. Keep one worker until a shared rate-limit backend and DB concurrency are tested; use Redis/PostgreSQL for multi-instance production. |
| P1 | `files_routes.py:/api/files/zip` | The entire ZIP archive is assembled in `BytesIO`. | Exporting a large workspace can use substantial RAM and cause worker OOM. | Use a temporary file or streamed archive for large workspaces and set a maximum export size. Not automatically changed by this patch. |
| P1 | `files_routes.py` `.7z` / `.rar` branches | The code calls archive library `extractall()` into a temporary directory before checking/adopting output files. | Defense depends on library/tool behavior for path traversal and link entries; post-checks may be too late if extraction escapes the temporary directory. | Before public use, validate every member path and link metadata before extraction or disable these formats; use a patched extractor and test traversal/zip-bomb fixtures. This residual risk is not claimed solved by the included patch. |
| P2 | `index.html:56-75` | Markdown renderer is a custom subset rather than a full Markdown implementation. | Tables/lists/nested Markdown and uncommon syntax may render inconsistently. | Keep the sanitizer/escaping, but consider a maintained Markdown renderer with raw HTML disabled and a safe-link policy. |
| P2 | `index.html:125-150` | Several project/conversation actions still use `prompt()`/`confirm()`. Archive list, message feedback and artifact version APIs are not fully wired into the UI. | Feels less like a polished coding workspace; errors and destructive actions have limited context. | Replace with accessible dialogs/context menus; wire existing API endpoints after UI testing. The current patch focuses on visual layout/search, not those missing product surfaces. |
| P2 | `server.py:/api/models`, `README.md` | Fallback model list is a static list. Actual model availability depends on the configured provider and endpoint compatibility. | A displayed model may be unavailable or reject parameters. | Use `/api/models` output when it is valid; keep fallback models visibly marked unverified. Test actual IDs/stream formats with a working provider key. |
| P2 | `test_app.py` | Tests mock the AI provider and cover API behavior, but do not test a real provider, browser rendering, Render deployment, actual web engine HTML or performance under load. | Passing tests do not prove live API/search/UI works. | Run the new regression tests plus real API smoke tests and browser E2E before calling the deployment production-ready. |

## Module-by-module reading notes

### `server.py`

- **Lines 1–35:** imports, Flask setup, request size limit, route registration, password gate and OpenAI-compatible client. Provider is configured by environment variables; no secret should be committed. `APP_PASSWORD` is optional, so it must be set for a public demo that could otherwise spend API credit.
- **Lines 38–54:** error mapping helps users understand common auth/quota/model failures, but intentionally hides most exception details. Keep detailed tracebacks out of HTTP responses; improve server-side structured logs with a request ID.
- **Lines 57–137:** HTML cleanup and search providers. The provider response extraction is brittle; `web_search` also had little relevance ranking and blocked before streaming. The bundled patch replaces this block with branch-aware, parallel queries and result scoring.
- **Lines 139–163:** URL fetch / SSRF boundary. The original validates public IPs before opening the URL but does not validate redirect destinations. The patch revalidates redirects, but a network-level egress policy is stronger protection.
- **Lines 165–213:** attachments and workspace context. Files are truncated to limit prompt size, but parsers can still consume resources on compressed or malformed documents. Keep per-file, per-format and aggregate extraction limits.
- **Lines 215–257:** health, diagnostics, model list and search route. `/api/health` reports configured status rather than proving that each provider is reachable. `/api/diagnostics` is the meaningful API-key/model smoke test; it still needs to be run with a real key.
- **Lines 258–342:** chat request assembly, owner checks, project context, SSE response and persistence. Search now runs after the first SSE progress event. The bundled change deliberately streams only user-facing tokens and persists only the answer text—not provider `reasoning_content`.
- **Lines 343–348:** 413 handler and local server startup. Production startup comes from `render.yaml`/Gunicorn; keep the web process and long-running generation timeouts aligned.

### `index.html`

- **Lines 1–35:** page head, theme variables, layout and responsive CSS. Styles were compact but visually closer to a general chatbot than a coding-task workspace. The patch injects `codex.css` at the Flask home route rather than requiring a frontend build step.
- **Lines 37–45:** sidebar, model/status top bar, starter cards, composer, file panel and preview iframe. Existing IDs are retained so the JavaScript wiring continues to target the same controls. The patch adds two starter prompts for multi-branch research and code review.
- **Lines 47–55:** the browser creates an `X-Session` and stores the optional shared password in `localStorage`. This is not user sign-in; do not treat a random client-side ID as proof of identity.
- **Lines 57–94:** Markdown/code fence parser, file export, code panel and preview. `esc()` reduces HTML injection risk for rendered text; preview is sandboxed without `allow-same-origin`, which is a good boundary to preserve.
- **Lines 96–124:** message rendering, progress indicator, send/stop/regen. Previously the progress box could display raw reasoning. The patch strips legacy reasoning blocks from the UI; backend changes stop sending the provider reasoning fields going forward.
- **Lines 125–150:** history/project UI. It already calls server APIs for list/open/rename/pin/archive/delete/project files, but `prompt()`/`confirm()` are still used and archive browsing is missing.
- **Lines 151–182:** mode wiring, uploads, API health/model loading, speech recognition, workspace, migration and startup. Browser speech recognition is not supported uniformly; UI should degrade gracefully. Several fetch errors are caught silently; a future pass should surface a diagnostic to users and logs.

### `store.py`

- **Lines 1–43:** schema, index definitions and SQLite helpers. SQL queries are parameterized, foreign keys are enabled on each connection, and writes are committed. Add schema migrations/versioning before more schema changes.
- **Lines 46–70:** rate-limit helper and conversation persistence helpers. In-memory rate limits are per process and `_hits` can retain keys indefinitely. `add_msg()` performs message insertion and conversation timestamp update as separate writes, rather than one transaction.
- **Lines 70–130:** owner-scoped conversation list/get/patch/delete, feedback and project endpoints. Owner checks generally scope reads/writes; conversation search escapes SQL LIKE wildcard characters.
- **Lines 130–190:** project CRUD and path association. The file association filters paths through `ws_path()` to ensure selected files exist in that session's workspace.
- **Lines 190–230:** artifact creation/list/detail/version endpoints. APIs exist for versioning, but the current UI does not fully surface version browsing/restore.
- **Lines 230–261:** get prior artifact version and migrate legacy localStorage conversations. Import is bounded to 100 chats and 400 messages/chat, which helps limit request amplification.

### `files_routes.py`

- **Lines 1–45:** session-specific workspace roots and `_inside()` path containment. The containment check helps prevent basic `../` traversal, but the workspace owner is still a client-supplied session ID.
- **Lines 47–120:** archive classifiers, byte/file budget and ZIP/TAR/GZIP extraction. ZIP symlinks are skipped and output paths are checked; archive paths should be treated as hostile input.
- **Lines 120–170:** 7z/RAR extraction, file adoption and upload loop. `extractall()` is the main residual archive-security concern; the bundled patch additionally enforces `MAX_TOTAL` after extraction.
- **Lines 170–234:** list/read/download/save/delete/zip. Reads have a 300 KB cap and save validates path segments; ZIP export is memory-backed and should be changed for large workspaces.

### `export_routes.py`

- **Lines 1–20:** export imports and `FILE_PROTOCOL`. The original instruction requiring `<think>` conflicted with the app's system policy; the patch replaces it with a plan-summary instruction. File protocol conventions should be treated as output formatting only—not a source of privileged instructions.
- **Lines 22–79:** Word, Excel, PowerPoint and RTF generation with size-limited content and safe filename characters. Documents are built in memory; failures return generic messages. PDF is generated in browser print flow, not on the backend.

### `test_app.py` and deployment configuration

- Tests build a temporary SQLite DB and fake the provider. They cover owner isolation, retry IDs, regenerate, project file scoping/traversal, search wildcard escaping, pin/archive/delete, artifact versions, rate limiting and import. The patch adds a regression test ensuring provider reasoning is not streamed or persisted.
- `requirements.txt` lists Flask/Gunicorn/OpenAI SDK and document/archive libraries. `rarfile` and an `unrar` binary are intentionally not included even though the UI notes that RAR support requires extra dependencies.
- `render.yaml` configures a Python web service and one Gunicorn worker. For durable data, set a mounted disk and point `DATABASE_PATH`/`WORKSPACE_DIR` at it. A production service should also have working API credentials, a shared password or real auth, rate limits and live health checks.

## Included changes versus remaining work

Included in `apply_upgrade.py`: Codex-inspired responsive CSS overlay; two added starter cards; concurrent multi-branch search in Research mode; dedupe and relevance ranking; first SSE progress event before search; link-redirect validation; workspace total-size guard after extraction; removal of contradictory `<think>` output instructions; no backend forwarding/persistence of provider reasoning fields; hide legacy `<think>` blocks; regression test.

Not included: actual Google login, real account system, OAuth provider setup, PostgreSQL migration, execution sandbox, agent that edits arbitrary repositories, real provider key validation, full browser E2E, 7z/RAR member-by-member extractor hardening, large-workspace streamed ZIP export, project/artifact UI completion. These require additional design or external credentials and are not safe to declare finished without testing.
