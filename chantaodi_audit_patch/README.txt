Chantaodi / MotAPI Studio v3 — audit patch

The GitHub connector allowed repository reads but denied branch creation with HTTP 403, so no remote changes were committed from this session.

1. Download/clone your repository into a local workspace with write access.
2. Keep the working tree clean and copy apply_audit_fixes.py outside or into the checkout.
3. Dry-run first:
   python apply_audit_fixes.py /path/to/Chantaodi
4. Inspect the script and dry-run output. Apply only when ready:
   python apply_audit_fixes.py /path/to/Chantaodi --apply
5. Inspect `git diff`; run:
   python -m unittest -v test_app
   python -m py_compile server.py store.py files_routes.py export_routes.py test_app.py
6. Verify with a real key set only in server-side environment: `/api/health`, `/api/models`, API diagnostics, send one chat, reopen its history.

Patch scope:
- Removes the unverified hard-coded model catalog from server and UI.
- `/api/models` now returns only provider-confirmed model IDs, and fails closed if the key/catalog is unavailable.
- The UI disables send/test-API when no verified model is available.
- Adds regression tests and audit addenda to PROJECT_STATUS.md, IMPLEMENTATION_ROADMAP.md, and HANDOFF.md; creates AUDIT_FINDINGS.md.

The script defaults to dry-run, refuses a dirty Git worktree, and validates all expected source fragments before writing any file. It does not install dependencies, deploy, or handle secrets.
