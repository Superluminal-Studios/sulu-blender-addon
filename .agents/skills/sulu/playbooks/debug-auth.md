# Debug Playbook: Auth / Login / Token problems

## Primary paths

- password login operator: `operators.py::SUPERLUMINAL_OT_Login.execute`
- browser login operator: `operators.py::SUPERLUMINAL_OT_LoginBrowser.execute`
  - spawns `_browser_login_thread_v2(txn)` which polls `/api/cli/token`
- request wrapper: `pocketbase_auth.py::authorized_request`
- storage: `storage.py::Storage.data` and `session.json`

## Symptoms → likely causes

### “Login succeeded but job list empty”

- token stored but:
  - projects not fetched (`first_login()` not called / failed mid-way)
  - org_id / user_key missing
  - farm endpoint rejected `Auth-Token` (wrong org_id / key)
  - `fetch_jobs()` called with wrong project_id

### “I keep getting logged out / NotAuthenticated”

- backend returns 401 → `authorized_request()` clears session
- token refresh logic:
  - refresh happens when `time.time() - user_token_time > 10`
  - ensure `user_token_time` is set on login (`first_login` sets it)

### “Resource not found” thrown

- `authorized_request()` treats any `status_code >= 404` as NotAuthenticated("Resource not found")
  - If you want proper error propagation for 404, change this behavior carefully.

## Fast repro checklist

1. Confirm Storage has token (don’t paste it):
   - is `Storage.data["user_token"]` non-empty?
2. Confirm projects loaded:
   - `Storage.data["projects"]` list non-empty
3. Confirm org_id + user_key:
   - set during `first_login()` from first project
4. Confirm jobs endpoint:
   - `utils/request_utils.request_jobs()` uses `/farm/{org_id}/api/job_list` with header `Auth-Token: user_key`

## Safe instrumentation

- Print booleans and counts, not secrets:
  - token present? (True/False)
  - projects count
  - jobs keys count
  - HTTP status codes only

## Fix patterns

- Never call network in `draw()` except guarded one-shot cases (login-only).
- Prefer an operator button (“Refresh”) for network actions.
- If adding new auth fields, store only tokens; WM password must stay runtime-only.
